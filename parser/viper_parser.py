#!/usr/bin/env python3.6

import sys
import ast
import types

from typing import List

from decimal import Decimal


class ParserException(Exception):
    pass


def get_original_if_0x_prefixed(expr):
    context_slice = inputLines[expr.lineno - 1][expr.col_offset:]
    if context_slice[:2] != '0x':
        return None
    t = 0
    while t + 2 < len(context_slice) and context_slice[t + 2] in '0123456789abcdefABCDEF':
        t += 1
    return context_slice[:t + 2]


def parse(code):
    o = ast.parse(code)
    # todo fix those
    # decorate_ast_with_source(o, code)
    # o = resolve_negative_literals(o)
    return o.body


def parseList(nodeList, parseElement: types.FunctionType, separator, initSeparator="", emptyCase=""):
    rez = ""
    first = True
    for node in nodeList:
        if first:
            first = False
            rez += initSeparator
        else:
            rez += separator
        rez += parseElement(node)
    return rez if rez != "" else emptyCase


#    syntax BaseType      ::= "%bool"
#                           | NumericType | "%num256"  | "%signed256"
#                           | "%bytes32" | "%address"
#
# syntax PureNumType   ::= "%num" | "%decimal"
def parseBaseType(name):  # value is Str. NumericType not yet supported
    if type(name) == ast.Name:
        return "%" + name.id
    else:
        raise ParserException("BaseType parsing not yet implemented for: " + str(id))


# syntax Type          ::= "%void"
#                           | BaseType
#                           | ByteArrayType
#                           | ListType
#                           | MappingType
#                           | StructType
#
# syntax ListType      ::= "%listT"   "(" Type "," Int ")"
#
# syntax MappingType   ::= "%mapT"    "(" Type "," BaseType ")"
#
# example:
#   %mapT(%num256, %address)
def parseType(param):
    if param is None:
        return "%void"
    elif type(param) == ast.Name:
        return parseBaseType(param)
    elif type(param) == ast.Subscript:
        if type(param.slice.value) == ast.Num:
            return "%listT({}, {})".format(parseType(param.value), parseConst(param.slice.value))
        else:
            return "%mapT({}, {})".format(parseType(param.value), parseType(param.slice.value))
    else:
        raise ParserException("Type parsing not yet implemented for: " + str(param))


# EventParam ::= "%eparam" "(" Id "," Type "," Bool /*indexed?*/ ")"
# example:
#   _from: indexed(address)
#   =>
#   %eparam(_from, %address, true)
def parseEventParam(key, value):  # value is Call
    rez = "%eparam(" + key.id + ", "
    if type(value) == ast.Call and value.func.id == "indexed":
        rez += parseType(value.args[0]) + ", true)"
    elif type(value) == ast.Name:
        rez += parseType(value) + ", false)"
    else:
        raise ParserException("Unsupported EventParam format: " + str(key) + " -> " + str(value))
    return rez


def parseEventParams(params):  # arg is ast.Dict
    rez = ""
    for i in range(0, len(params.keys)):
        key = params.keys[i]
        value = params.values[i]
        if rez != "":
            rez += " "
        rez += parseEventParam(key, value)
    return rez


# syntax Event    ::= "%event" "(" Id "," EventParams ")"
# syntax Events ::= List{Event, ""}
def parseEvent(node):  # node.annotation is ast.Call
    return "  %event(" + node.target.id + ", " + parseEventParams(node.annotation.args[0]) + ")"


#    syntax Global   ::= "%svdecl" "(" Id "," Type "," Visibility ")"
#    syntax Globals  ::= List{Global, ""}
#
# example:
#   %svdecl(balances, %mapT(%num256, %address), %private)
def parseGlobal(node):
    return "  %svdecl(" + node.target.id + ", " + parseType(node.annotation) + ", %private)"


#    syntax Decorator  ::= "%@constant" | "%@payable" | "%@internal" | "%@public"
#    syntax Decorators ::= List{Decorator, ""}
def parseDecorator(name):
    return "%@" + name.id


def parseDecorators(decorator_list):
    return parseList(decorator_list, parseDecorator, " ")


# syntax Param    ::= "%param" "(" Id "," Type ")"
#
# example: %param(_value, %num256)
def parseParam(arg: ast.arg):
    return "%param({}, {})".format(arg.arg, parseType(arg.annotation))


# syntax Params   ::= List{Param, ""}
def parseParams(args: List[ast.arg]):
    return parseList(args, parseParam, " ")


#    syntax Var      ::= "%var"      "(" Id ")"
#                      | "%svar"     "(" Id ")"
#                      | "%mem"      "(" Var "," Id   ")"  // struct field access
#                      | "%listelem" "(" Var "," Expr ")"  // list element
#                      | "%mapelem"  "(" Var "," Expr ")"  // map element
#
# examples:
#   %var(_value)
#   %svar(balances)
#   self.balances[_sender]  =>  %mapelem(%svar(balances), %var(_sender))
def parseVar(var):
    if type(var) == ast.Name:
        return "%var(" + var.id + ")"
    elif type(var) == ast.Index:  # same as ast.Name
        return parseVar(var.value)
    elif type(var) == ast.Attribute and var.value.id == "self":
        return "%svar(" + var.attr + ")"
    elif type(var) == ast.Subscript:
        return "%mapelem(" + parseVar(var.value) + ", " + parseExpr(var.slice) + ")"
    else:
        raise ParserException("Unsupported Var format: " + str(var))


# taken from viper compiler.
DECIMAL_DIVISOR = 10000000000


def parseFixed10Const(node):
    num = Decimal(node.n)
    divisor = 1
    while num % 1 != 0 and divisor < DECIMAL_DIVISOR:
        num *= 10
        divisor *= 10
    return "%fixed10({0:.0f}, {1})".format(num, divisor)


# syntax Const    ::= Int
#                   | "%hex"     "(" String ")"
#                   | "%fixed10" "(" Int "," Int ")"  // decimal fixed point value with a precision of 10 decimal places
#                                                     // %fixed10(A, B) = A/B and B is a power of 10.
#                   | String
#                   | Bool
#
def parseConst(node):
    if type(node) == ast.Num and type(node.n) == int:
        hexFormat = get_original_if_0x_prefixed(node)
        if hexFormat is None:
            return str(node.n)
        else:
            return "%hex(\"{}\")".format(hexFormat[2:])
    elif type(node) == ast.Num and type(node.n == float):
        return parseFixed10Const(node)
    elif type(node) == ast.Name and node.id in ["true", "false"]:
        return node.id
    else:
        raise ParserException("Unsupported Const format: " + str(node))


# Only ReservedFunc at the moment
#    syntax ReservedFunc  ::= "%as_num128"    "(" Expr ")"
#                           | "%as_num256"    "(" Expr ")"
#                           | "%as_wei_value" "(" Expr "," Id   ")"
#                           | "%num256_add"   "(" Expr "," Expr ")"
#                           | "%num256_sub"   "(" Expr "," Expr ")"
#
# example:
#   %as_num256(%msg.value)
#
#   num256_add(self.balances[_sender], _value)
#   =>
#   %num256_add(%mapelem(%svar(balances), %var(_sender)), %var(_value))
#
#   %as_wei_value(%as_num128(%var(_value)), wei)
def parseCallExpr(expr):
    if expr.func.id == "as_wei_value":
        return "%as_wei_value({}, {})".format(parseExpr(expr.args[0]), expr.args[1].id)
    else:
        return "%{}({})".format(expr.func.id, parseExprs(expr.args, ", "))


# syntax ReservedExpr  ::= "%msg.sender" | "%msg.value" | "%msg.gas"
#                        | "%block.difficulty" | "%block.timestamp" | "%block.coinbase" | "%block.number"
#                        | "%block.prevhash"
#                        | "%tx.origin"
def parseReservedExpr(expr):
    return "%" + expr.value.id + "." + expr.attr


# syntax Expr     ::= Const
#                   | Var
#                   | ListExpr
#                   | "%self"
#                   | "%binop"     "(" BinOp     "," Expr "," Expr ")"
#                   | "%compareop" "(" CompareOp "," Expr "," Expr ")"
#                   | "%boolop"    "(" BoolOp    "," Expr "," Expr ")"
#                   | "%unaryop"   "(" UnaryOp   "," Expr ")"
#                   | "%icall"     "(" Id        "," Exprs ")"  // internal contract call
#                   | "%ecall"     "(" Id        "," Exprs ")"  // external contract call
#                   | ReservedExpr
#                   | ReservedFunc  // expr dispatch table
#
# syntax ListExpr      ::= "%list" "(" Exprs ")"
#
# examples:
#   %var(_sender)
#   %as_num256(%msg.value)
#   %msg.value
#   %mapelem(%svar(balances), %var(_sender))
#   %binop(+, %var(x), 10)
def parseExpr(expr):
    if type(expr) == ast.Num or (type(expr) == ast.Name and expr.id in ["true", "false"]):
        return parseConst(expr)
    elif type(expr) == ast.Name and expr.id == "self":
        return "%self"
    elif type(expr) == ast.BinOp:
        return "%binop({}, {}, {})".format(parseBinOp(expr.op), parseExpr(expr.left), parseExpr(expr.right))
    elif type(expr) == ast.Name or type(expr) == ast.Index or type(expr) == ast.Subscript \
            or (type(expr) == ast.Attribute and expr.value.id == "self"):
        return parseVar(expr)
    elif type(expr) == ast.List:
        return "%list({})".format(parseExprs(expr.elts))
    elif type(expr) == ast.Attribute:
        return parseReservedExpr(expr)
    elif type(expr) == ast.Call:
        return parseCallExpr(expr)
    else:
        raise ParserException("Unsupported Expr format: " + str(expr))


# syntax Exprs    ::= List{Expr, ""}
def parseExprs(exprs, separator=" "):
    return parseList(exprs, parseExpr, separator)


# syntax BinOp         ::= "+" | "-" | "*" | "/" | "%" | "**"
#
# we'll support all operators from Python.
def parseBinOp(op: ast.operator):
    opType = type(op)
    if opType == ast.Add:
        return "+"
    elif opType == ast.BitAnd:
        return "&"
    elif opType == ast.BitOr:
        return "|"
    elif opType == ast.BitXor:
        return "^"
    elif opType == ast.Div:
        return "/"
    elif opType == ast.FloorDiv:
        return "//"
    elif opType == ast.LShift:
        return "<<"
    elif opType == ast.MatMult:
        return "@"
    elif opType == ast.Mod:
        return "%"
    elif opType == ast.Mult:
        return "*"
    elif opType == ast.Pow:
        return "**"
    elif opType == ast.RShift:
        return ">>"
    elif opType == ast.Sub:
        return "-"
    else:
        raise ParserException("Unsupported AugAssign operator: " + str(op))


# syntax AugAssignOp ::= "+=" | "-=" | "*=" | "/=" | "%="
def parseAugAssignOp(op: ast.operator):
    return "{}=".format(parseBinOp(op))


# syntax Stmt     ::= VarDecl                                              // annotated assign
#                   | "%assign"    "(" Var "," Expr ")"
#                   | "%augassign" "(" AugAssignOp "," Var "," Expr ")"
#                   | "%if"        "(" Expr "," Stmts "," Stmts ")"
#                   | "%if"        "(" Expr "," Stmts ")"
#                   | "%forrange"  "(" Id "," Int  "," Stmts ")"            // for i in range(rounds)
#                   | "%forrange"  "(" Id "," Expr "," Expr  "," Stmts ")"  // for i in range(start, start + rounds)
#                   | "%forlist"   "(" Id "," Expr "," Stmts ")"            // for i in list()
#                   | "%break"
#                   | "%pass"
#                   | "%return"
#                   | "%return"    "(" Expr ")"
#                   | "%assert"    "(" Expr ")"
#                   | "%throw"
#                   | "%log"       "(" Id "," Exprs ")"
#                   // stmt dispatch table
#                   | "%send"      "(" Expr  "," Expr ")"
#                   | "%selfdestruct" "(" Expr ")"
#
# examples:
#   _value = as_num256(msg.value)
#   =>
#   %assign(%var(_value), %as_num256(%msg.value))
#
#   log.Transfer(0x0000000000000000000000000000000000000000, _sender, _value)
#   =>
#   %log(Transfer, %hex("0000000000000000000000000000000000000000"), %var(_sender), %var(_value)))
#
#   send(_sender, as_wei_value(as_num128(_value), wei))
#   =>
#   %send(%var(_sender), %as_wei_value(%as_num128(%var(_value)), wei))
#
# %augassign(+=, %var(z), %var(y))
#
#  %if(%var(i),
#    %return(5),
#    %return(7))
#
# %forrange(i, 10, %pass)
def parseStmt(stmt):
    if type(stmt) == ast.Assign:
        return "%assign({}, {})".format(parseVar(stmt.targets[0]), parseExpr(stmt.value))
    elif type(stmt) == ast.AugAssign:
        return "%augassign({}, {}, {})".format(parseAugAssignOp(stmt.op), parseVar(stmt.target),
                                               parseExpr(stmt.value))
    elif type(stmt) == ast.Expr and type(stmt.value) == ast.Call:
        if type(stmt.value.func) == ast.Attribute and stmt.value.func.value.id == "log":
            return "%log({}, {})".format(stmt.value.func.attr, parseExprs(stmt.value.args))
        elif type(stmt.value.func) == ast.Name and stmt.value.func.id == "send":
            return "%send({})".format(parseExprs(stmt.value.args, ", "))
        else:
            return ""  # todo temp to see results
    elif type(stmt) == ast.If:
        if stmt.orelse is None:
            return "%if({},{})".format(parseExpr(stmt.test), parseStmts(stmt.body))
        else:
            return "%if({},{},{})".format(parseExpr(stmt.test), parseStmts(stmt.body), parseStmts(stmt.orelse))
    elif type(stmt) == ast.For and stmt.iter.func.id == "range":
        if len(stmt.iter.args) == 1:
            return "%forrange({}, {},{})".format(stmt.target.id, parseExpr(stmt.iter.args[0]), parseStmts(stmt.body))
        else:
            return "%forrange({}, {}, {},{})".format(stmt.target.id, parseExpr(stmt.iter.args[0]),
                                                     parseExpr(stmt.iter.args[1]), parseStmts(stmt.body))
    elif type(stmt) == ast.Pass:
        return "%pass"
    elif type(stmt) == ast.Return:
        if stmt.value is None:
            return "%return"
        else:
            return "%return({})".format(parseExpr(stmt.value))
    else:
        return ""  # todo temp to see results
        # raise ParserException("Unsupported Stmt format: " + str(stmt))


stmtsIndent = "  "


# syntax Stmts    ::= List{Stmt, ""}
def parseStmts(body):
    global stmtsIndent
    oldStmtsIndent = stmtsIndent
    stmtsIndent += "  "
    rez = parseList(body, parseStmt, "\n" + stmtsIndent, "\n" + stmtsIndent)
    stmtsIndent = oldStmtsIndent
    return rez


#    syntax Def      ::= "%fdecl" "(" Decorators "," Id "," Params "," Type "," Stmts ")"
#    syntax Defs     ::= List{Def, ""}
#
# ex:
#  %fdecl(%@public %@payable, deposit, ,%void,
#    %assign(%var(_value), %as_num256(%msg.value))
#    ...)
def parseDef(node):
    return "  %fdecl({}, {}, {}, {},{})".format(
        parseDecorators(node.decorator_list),
        node.name,
        parseParams(node.args.args),
        parseType(node.returns),
        parseStmts(node.body)
    )


# Pgm ::= "%pgm" "(" Events "," Globals "," Defs ")"
def parseProgram(nodeList):
    events = []
    globals = []
    defs = []
    for node in nodeList:
        if type(node) == ast.AnnAssign and type(node.annotation) == ast.Call:
            events.append(node)
        elif type(node) == ast.AnnAssign:
            globals.append(node)
        elif type(node) == ast.FunctionDef:
            defs.append(node)
        else:
            raise ParserException("Unsupported top level node: " + str(node))
    return "%pgm({},{},{}\n)".format(
        parseList(events, parseEvent, "\n", "\n"),
        parseList(globals, parseGlobal, "\n", "\n", " "),
        parseList(defs, parseDef, "\n", "\n", " "))


inputLines: List[str]

if __name__ == '__main__':
    if len(sys.argv) != 2:
        print("One argument expected: the file name.")
        sys.exit(1)
    fileName = sys.argv[1]
    with open(fileName, "r") as fin:
        input = fin.read()
    inputLines = input.splitlines()
    astList = parse(input)
    print(parseProgram(astList))