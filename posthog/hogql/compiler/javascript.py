import dataclasses
import json
import re
from enum import StrEnum
from typing import Any, Optional

from posthog.hogql import ast
from posthog.hogql.base import AST
from posthog.hogql.context import HogQLContext
from posthog.hogql.errors import QueryError
from posthog.hogql.visitor import Visitor

_JS_GET_GLOBAL = "get_global"
_JS_KEYWORDS = ["var", "let", "const", "function"]
INLINED_JS_STL = {
    "print": """
const escapeCharsMap = { '\\b': '\\\\b', '\\f': '\\\\f', '\\r': '\\\\r', '\\n': '\\\\n', '\\t': '\\\\t', '\\0': '\\\\0', '\\v': '\\\\v', '\\\\': '\\\\\\\\' };
const singlequoteEscapeCharsMap = { ...escapeCharsMap, "'": "\\\\'" };
const backquoteEscapeCharsMap = { ...escapeCharsMap, '`': '\\\\`' };
function escapeString(value) { return `'${value.split('').map((c) => singlequoteEscapeCharsMap[c] || c).join('')}'`; }
function escapeIdentifier(identifier) {
    if (typeof identifier === 'number') return identifier.toString();
    if (/^[A-Za-z_$][A-Za-z0-9_$]*$/.test(identifier)) return identifier;
    return `\\`${identifier.split('').map((c) => backquoteEscapeCharsMap[c] || c).join('')}\\``;
}
function isHogCallable(obj) { return obj && typeof obj === 'object' && '__hogCallable__' in obj && 'argCount' in obj && 'ip' in obj && 'upvalueCount' in obj; }
function isHogClosure(obj) { return obj && typeof obj === 'object' && '__hogClosure__' in obj && 'callable' in obj && 'upvalues' in obj; }
function isHogDate(obj) { return obj && typeof obj === 'object' && '__hogDate__' in obj && 'year' in obj && 'month' in obj && 'day' in obj; }
function isHogDateTime(obj) { return obj && typeof obj === 'object' && '__hogDateTime__' in obj && 'dt' in obj && 'zone' in obj; }
function isHogError(obj) { return obj && typeof obj === 'object' && '__hogError__' in obj && 'type' in obj && 'message' in obj; }
function printHogValue(obj, marked = new Set()) {
    if (typeof obj === 'object' && obj !== null && obj !== undefined) {
        if (marked.has(obj) && !isHogDateTime(obj) && !isHogDate(obj) && !isHogError(obj) && !isHogClosure(obj) && !isHogCallable(obj)) {
            return 'null';
        }
        marked.add(obj);
        try {
            if (Array.isArray(obj)) {
                if (obj.__isHogTuple) {
                    return obj.length < 2 ? `tuple(${obj.map((o) => printHogValue(o, marked)).join(', ')})` : `(${obj.map((o) => printHogValue(o, marked)).join(', ')})`;
                }
                return `[${obj.map((o) => printHogValue(o, marked)).join(', ')}]`;
            }
            if (isHogDateTime(obj)) {
                const millis = String(obj.dt);
                return `DateTime(${millis}${millis.includes('.') ? '' : '.0'}, ${escapeString(obj.zone)})`;
            }
            if (isHogDate(obj)) return `Date(${obj.year}, ${obj.month}, ${obj.day})`;
            if (isHogError(obj)) {
                return `${String(obj.type)}(${escapeString(obj.message)}${obj.payload ? `, ${printHogValue(obj.payload, marked)}` : ''})`;
            }
            if (isHogClosure(obj)) return printHogValue(obj.callable, marked);
            if (isHogCallable(obj)) return `fn<${escapeIdentifier(obj.name ?? 'lambda')}(${printHogValue(obj.argCount)})>`;
            if (obj instanceof Map) {
                return `{${Array.from(obj.entries()).map(([key, value]) => `${printHogValue(key, marked)}: ${printHogValue(value, marked)}`).join(', ')}}`;
            }
            return `{${Object.entries(obj).map(([key, value]) => `${printHogValue(key, marked)}: ${printHogValue(value, marked)}`).join(', ')}}`;
        } finally {
            marked.delete(obj);
        }
    } else if (typeof obj === 'boolean') return obj ? 'true' : 'false';
    else if (obj === null || obj === undefined) return 'null';
    else if (typeof obj === 'string') return escapeString(obj);
    return obj.toString();
}
function printHogStringOutput(obj) { return typeof obj === 'string' ? obj : printHogValue(obj); }
"""
}


@dataclasses.dataclass
class Local:
    name: str
    depth: int
    is_captured: bool


@dataclasses.dataclass
class CompiledJavaScript:
    code: str
    locals: list[Local]


def to_js_expr(expr: str) -> str:
    from posthog.hogql.parser import parse_expr

    return create_javascript(parse_expr(expr)).code


def to_js_program(expr: str) -> str:
    from posthog.hogql.parser import parse_program

    return create_javascript(parse_program(expr)).code


def create_javascript(
    expr: ast.Expr | ast.Statement | ast.Program,
    supported_functions: Optional[set[str]] = None,
    args: Optional[list[str]] = None,
    context: Optional[HogQLContext] = None,
    in_repl: Optional[bool] = False,
    locals: Optional[list[Local]] = None,
) -> CompiledJavaScript:
    supported_functions = supported_functions or set()
    compiler = JavaScriptCompiler(supported_functions, args, context, in_repl, locals)
    code = compiler.visit(expr)
    code = f"{compiler.get_extra_code()}{code}"
    return CompiledJavaScript(code=code, locals=compiler.locals)


def _as_block(node: ast.Statement) -> ast.Block:
    if isinstance(node, ast.Block):
        return node
    return ast.Block(declarations=[node])


def _sanitize_var_name(name: str) -> str:
    if re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", name) and name not in _JS_KEYWORDS:
        return name
    else:
        return f"[{json.dumps(name)}]"


class JavaScriptCompiler(Visitor):
    def __init__(
        self,
        supported_functions: Optional[set[str]] = None,
        args: Optional[list[str]] = None,
        context: Optional[HogQLContext] = None,
        in_repl: Optional[bool] = False,
        locals: Optional[list[Local]] = None,
    ):
        super().__init__()
        self.supported_functions = supported_functions or set()
        self.in_repl = in_repl
        self.locals: list[Local] = locals or []
        self.scope_depth = 0
        self.args = args or []
        self.context = context or HogQLContext(team_id=None)
        self.indent_level = 0
        self.inlined_stl = set()

        # Initialize locals with function arguments
        for arg in self.args:
            self._declare_local(arg)

    def get_extra_code(self):
        return "\n".join(INLINED_JS_STL.get(func, "") for func in self.inlined_stl)

    def _start_scope(self):
        self.scope_depth += 1

    def _end_scope(self):
        self.locals = [local for local in self.locals if local.depth < self.scope_depth]
        self.scope_depth -= 1

    def _declare_local(self, name: str):
        for local in reversed(self.locals):
            if local.depth == self.scope_depth and local.name == name:
                raise QueryError(f"Variable `{name}` already declared in this scope")
        self.locals.append(Local(name=name, depth=self.scope_depth, is_captured=False))

    def _indent(self, code: str) -> str:
        indentation = "    " * self.indent_level
        return "\n".join(indentation + line if line else "" for line in code.split("\n"))

    def visit_and(self, node: ast.And):
        code = " && ".join([self.visit(expr) for expr in node.exprs])
        return f"({code})"

    def visit_or(self, node: ast.Or):
        code = " || ".join([self.visit(expr) for expr in node.exprs])
        return f"({code})"

    def visit_not(self, node: ast.Not):
        expr_code = self.visit(node.expr)
        return f"(!{expr_code})"

    def visit_compare_operation(self, node: ast.CompareOperation):
        left_code = self.visit(node.left)
        right_code = self.visit(node.right)
        op = node.op

        op_map = {
            # TODO: check nulls
            ast.CompareOperationOp.Eq: "===",
            ast.CompareOperationOp.NotEq: "!=",
            ast.CompareOperationOp.Gt: ">",
            ast.CompareOperationOp.GtEq: ">=",
            ast.CompareOperationOp.Lt: "<",
            ast.CompareOperationOp.LtEq: "<=",
        }

        if op in op_map:
            op_str = op_map[op]
            return f"({left_code} {op_str} {right_code})"
        elif op == ast.CompareOperationOp.In:
            return f"({right_code}.includes({left_code}))"
        elif op == ast.CompareOperationOp.NotIn:
            return f"(!{right_code}.includes({left_code}))"
        elif op == ast.CompareOperationOp.Like:
            # TODO: check what's happening here
            # Escape special regex characters in pattern
            pattern_code = f'({right_code}).replace(/[.*+?^${{}}()|[\\]\\\\]/g, "\\\\$&")'
            regex_code = f'new RegExp("^" + {pattern_code}.replace(/%/g, ".*").replace(/_/g, ".") + "$")'
            return f"({regex_code}).test({left_code})"
        elif op == ast.CompareOperationOp.ILike:
            # TODO: check what's happening here
            pattern_code = f'({right_code}).replace(/[.*+?^${{}}()|[\\]\\\\]/g, "\\\\$&")'
            regex_code = f'new RegExp("^" + {pattern_code}.replace(/%/g, ".*").replace(/_/g, ".") + "$", "i")'
            return f"({regex_code}).test({left_code})"
        elif op == ast.CompareOperationOp.NotLike:
            # TODO: check what's happening here
            pattern_code = f'({right_code}).replace(/[.*+?^${{}}()|[\\]\\\\]/g, "\\\\$&")'
            regex_code = f'new RegExp("^" + {pattern_code}.replace(/%/g, ".*").replace(/_/g, ".") + "$")'
            return f"!({regex_code}).test({left_code})"
        elif op == ast.CompareOperationOp.NotILike:
            # TODO: check what's happening here
            pattern_code = f'({right_code}).replace(/[.*+?^${{}}()|[\\]\\\\]/g, "\\\\$&")'
            regex_code = f'new RegExp("^" + {pattern_code}.replace(/%/g, ".*").replace(/_/g, ".") + "$", "i")'
            return f"!({regex_code}).test({left_code})"
        elif op == ast.CompareOperationOp.Regex:
            # TODO: re2?
            return f"new RegExp({right_code}).test({left_code})"
        elif op == ast.CompareOperationOp.IRegex:
            return f'new RegExp({right_code}, "i").test({left_code})'
        elif op == ast.CompareOperationOp.NotRegex:
            return f"!(new RegExp({right_code}).test({left_code}))"
        elif op == ast.CompareOperationOp.NotIRegex:
            return f'!(new RegExp({right_code}, "i").test({left_code}))'
        elif op == ast.CompareOperationOp.InCohort or op == ast.CompareOperationOp.NotInCohort:
            cohort_name = ""
            if isinstance(node.right, ast.Constant):
                if isinstance(node.right.value, int):
                    cohort_name = f" (cohort id={node.right.value})"
                else:
                    cohort_name = f" (cohort: {str(node.right.value)})"
            raise QueryError(
                f"Can't use cohorts in real-time filters. Please inline the relevant expressions{cohort_name}."
            )
        else:
            raise QueryError(f"Unsupported comparison operator: {op}")

    def visit_arithmetic_operation(self, node: ast.ArithmeticOperation):
        left_code = self.visit(node.left)
        right_code = self.visit(node.right)
        op_map = {
            ast.ArithmeticOperationOp.Add: "+",
            ast.ArithmeticOperationOp.Sub: "-",
            ast.ArithmeticOperationOp.Mult: "*",
            ast.ArithmeticOperationOp.Div: "/",
            ast.ArithmeticOperationOp.Mod: "%",
        }
        op_str = op_map[node.op]
        return f"({left_code} {op_str} {right_code})"

    def visit_field(self, node: ast.Field):
        found_local = any(local.name == str(node.chain[0]) for local in self.locals)
        code_parts = []
        for index, element in enumerate(node.chain):
            if index == 0 and not found_local:
                # TODO: make sure js_get_global is unique!
                code_parts.append(f"{_JS_GET_GLOBAL}({json.dumps(element)})")
                continue

            if isinstance(element, int) and not isinstance(element, bool) and index > 0:
                code_parts.append(f"[{element}]")
            elif isinstance(element, str):
                if re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", element):
                    if code_parts:
                        code_parts.append("." + element)
                    else:
                        code_parts.append(element)
                else:
                    element = f"[{json.dumps(element)}]"
                    code_parts.append(element)
            else:
                raise QueryError(f"Unsupported element: {element} ({type(element)})")

        code = "".join(code_parts)
        return code

    def visit_tuple_access(self, node: ast.TupleAccess):
        tuple_code = self.visit(node.tuple)
        index_code = str(node.index)
        adjusted_index = f"(({index_code}) > 0 ? ({index_code} - 1) : (({tuple_code}).length + ({index_code})))"
        if node.nullish:
            return f"({tuple_code}?.[{adjusted_index.strip()}])"
        else:
            return f"{tuple_code}[{adjusted_index.strip()}]"

    def visit_array_access(self, node: ast.ArrayAccess):
        array_code = self.visit(node.array)
        property_code = self.visit(node.property)
        # TODO: this is used for strings and objects as well, we can't assume it's an array
        adjusted_index = (
            f"(({property_code}) > 0 ? ({property_code} - 1) : (({array_code}).length + ({property_code})))"
        )

        if node.nullish:
            return f"({array_code}?.[{adjusted_index.strip()}])"
        else:
            return f"{array_code}[{adjusted_index.strip()}]"

    def visit_constant(self, node: ast.Constant):
        value = node.value
        if value is True:
            return "true"
        elif value is False:
            return "false"
        elif value is None:
            return "null"
        elif isinstance(value, int) or isinstance(value, float) or isinstance(value, str):
            return json.dumps(value)
        else:
            raise QueryError(f"Constant type `{type(value)}` is not supported")

    def visit_call(self, node: ast.Call):
        # Handle special functions
        if node.name == "not" and len(node.args) == 1:
            expr_code = self.visit(node.args[0])
            return f"(!{expr_code})"
        if node.name == "and" and len(node.args) > 1:
            exprs_code = " && ".join([self.visit(arg) for arg in node.args])
            return f"({exprs_code})"
        if node.name == "or" and len(node.args) > 1:
            exprs_code = " || ".join([self.visit(arg) for arg in node.args])
            return f"({exprs_code})"
        if node.name == "if" and len(node.args) >= 2:
            condition_code = self.visit(node.args[0])
            then_code = self.visit(node.args[1])
            else_code = self.visit(node.args[2]) if len(node.args) == 3 else "null"
            return f"({condition_code} ? {then_code} : {else_code})"
        if node.name == "multiIf" and len(node.args) >= 2:
            # Generate nested ternary operators
            def build_nested_if(args):
                condition_code = self.visit(args[0])
                then_code = self.visit(args[1])
                if len(args) == 2:
                    return f"({condition_code} ? {then_code} : null)"
                elif len(args) == 3:
                    else_code = self.visit(args[2])
                    return f"({condition_code} ? {then_code} : {else_code})"
                else:
                    else_code = build_nested_if(args[2:])
                    return f"({condition_code} ? {then_code} : {else_code})"

            return build_nested_if(node.args)
        if node.name == "ifNull" and len(node.args) == 2:
            expr_code = self.visit(node.args[0])
            if_null_code = self.visit(node.args[1])
            return f"({expr_code} ?? {if_null_code})"

        # Handle STL functions
        if node.name == "concat":
            args_code = " + ".join([f"String({self.visit(arg)})" for arg in node.args])
            return f"({args_code})"
        elif node.name == "toString":
            expr_code = self.visit(node.args[0])
            return f"printHogStringOutput({expr_code})"
        elif node.name == "toUUID":
            expr_code = self.visit(node.args[0])
            return f"printHogStringOutput({expr_code})"
        elif node.name == "toInt":
            expr_code = self.visit(node.args[0])
            return f"parseInt({expr_code}, 10)"
        elif node.name == "toFloat":
            expr_code = self.visit(node.args[0])
            return f"parseFloat({expr_code})"
        elif node.name == "length":
            expr_code = self.visit(node.args[0])
            return f"({expr_code}).length"
        elif node.name == "empty":
            expr_code = self.visit(node.args[0])
            return f"(({expr_code}) == null || ({expr_code}).length === 0 || Object.keys({expr_code}).length === 0)"
        elif node.name == "notEmpty":
            expr_code = self.visit(node.args[0])
            return f"(!(({expr_code}) == null || ({expr_code}).length === 0 || Object.keys({expr_code}).length === 0))"
        elif node.name == "tuple":
            items_code = ", ".join([self.visit(arg) for arg in node.args])
            return f"Object.assign([{items_code}], {{ __isHogTuple: true }})"
        elif node.name == "lower":
            expr_code = self.visit(node.args[0])
            return f"({expr_code}).toLowerCase()"
        elif node.name == "upper":
            expr_code = self.visit(node.args[0])
            return f"({expr_code}).toUpperCase()"
        elif node.name == "reverse":
            expr_code = self.visit(node.args[0])
            return f'([...({expr_code})].reverse().join(""))'
        elif node.name == "trim":
            expr_code = self.visit(node.args[0])
            return f"({expr_code}).trim()"
        elif node.name == "trimLeft":
            expr_code = self.visit(node.args[0])
            return f"({expr_code}).trimStart()"
        elif node.name == "trimRight":
            expr_code = self.visit(node.args[0])
            return f"({expr_code}).trimEnd()"
        elif node.name == "keys":
            expr_code = self.visit(node.args[0])
            return f"Object.keys({expr_code})"
        elif node.name == "values":
            expr_code = self.visit(node.args[0])
            return f"Object.values({expr_code})"
        elif node.name == "now":
            return "Date.now()"
        elif node.name == "typeof":
            expr_code = self.visit(node.args[0])
            return f"typeof {expr_code}"
        elif node.name == "base64Encode":
            expr_code = self.visit(node.args[0])
            return f"btoa({expr_code})"
        elif node.name == "base64Decode":
            expr_code = self.visit(node.args[0])
            return f"atob({expr_code})"
        elif node.name == "tryBase64Decode":
            expr_code = self.visit(node.args[0])
            return f"(function(s) {{ try {{ return atob(s); }} catch(e) {{ return ''; }} }})({expr_code})"
        elif node.name == "encodeURLComponent":
            expr_code = self.visit(node.args[0])
            return f"encodeURIComponent({expr_code})"
        elif node.name == "decodeURLComponent":
            expr_code = self.visit(node.args[0])
            return f"decodeURIComponent({expr_code})"
        elif node.name == "jsonParse":
            expr_code = self.visit(node.args[0])
            return f"JSON.parse({expr_code})"
        elif node.name == "jsonStringify":
            expr_code = self.visit(node.args[0])
            return f"JSON.stringify({expr_code})"
        elif node.name == "isValidJSON":
            expr_code = self.visit(node.args[0])
            return (
                f"(function(s) {{ try {{ JSON.parse(s); return true; }} catch (e) {{ return false; }} }})({expr_code})"
            )
        elif node.name == "JSONHas":
            obj_expr = self.visit(node.args[0])
            path_exprs = [self.visit(arg) for arg in node.args[1:]]
            # Build dynamic access
            path_code = "".join([f"[{arg}]" for arg in path_exprs])
            return f"(({obj_expr}{path_code}) !== undefined)"
        elif node.name == "JSONLength":
            obj_expr = self.visit(node.args[0])
            path_exprs = [self.visit(arg) for arg in node.args[1:]]
            path_code = "".join([f"[{arg}]" for arg in path_exprs])
            return f"(Object.keys({obj_expr}{path_code} || {{}}).length)"
        elif node.name == "JSONExtractBool":
            obj_expr = self.visit(node.args[0])
            path_exprs = [self.visit(arg) for arg in node.args[1:]]
            path_code = "".join([f"[{arg}]" for arg in path_exprs])
            return f"(!!({obj_expr}{path_code}))"
        elif node.name == "replaceOne":
            string_expr = self.visit(node.args[0])
            search_expr = self.visit(node.args[1])
            replace_expr = self.visit(node.args[2])
            return f"({string_expr}).replace({search_expr}, {replace_expr})"
        elif node.name == "replaceAll":
            string_expr = self.visit(node.args[0])
            search_expr = self.visit(node.args[1])
            replace_expr = self.visit(node.args[2])
            return f"({string_expr}).split({search_expr}).join({replace_expr})"
        elif node.name == "splitByString":
            separator_expr = self.visit(node.args[0])
            string_expr = self.visit(node.args[1])
            max_splits_expr = self.visit(node.args[2]) if len(node.args) > 2 else None
            if max_splits_expr:
                return f"({string_expr}).split({separator_expr}, {max_splits_expr})"
            else:
                return f"({string_expr}).split({separator_expr})"
        elif node.name == "generateUUIDv4":
            return "crypto.randomUUID()"
        elif node.name == "has":
            arr_expr = self.visit(node.args[0])
            elem_expr = self.visit(node.args[1])
            return f"({arr_expr}).includes({elem_expr})"
        elif node.name == "indexOf":
            arr_expr = self.visit(node.args[0])
            elem_expr = self.visit(node.args[1])
            return f"(({arr_expr}).indexOf({elem_expr}) + 1)"
        elif node.name == "arrayPushBack":
            arr_expr = self.visit(node.args[0])
            item_expr = self.visit(node.args[1])
            return f"([...{arr_expr}, {item_expr}])"
        elif node.name == "arrayPushFront":
            arr_expr = self.visit(node.args[0])
            item_expr = self.visit(node.args[1])
            return f"([{item_expr}, ...{arr_expr}])"
        elif node.name == "arrayPopBack":
            arr_expr = self.visit(node.args[0])
            return f"({arr_expr}).slice(0, -1)"
        elif node.name == "arrayPopFront":
            arr_expr = self.visit(node.args[0])
            return f"({arr_expr}).slice(1)"
        elif node.name == "arraySort":
            arr_expr = self.visit(node.args[0])
            return f"([...{arr_expr}].sort())"
        elif node.name == "arrayReverse":
            arr_expr = self.visit(node.args[0])
            return f"([...{arr_expr}].reverse())"
        elif node.name == "arrayReverseSort":
            arr_expr = self.visit(node.args[0])
            return f"([...{arr_expr}].sort().reverse())"
        elif node.name == "arrayStringConcat":
            arr_expr = self.visit(node.args[0])
            separator_expr = self.visit(node.args[1]) if len(node.args) > 1 else '""'
            return f"({arr_expr}).join({separator_expr})"
        elif node.name == "arrayCount":
            arr_expr = self.visit(node.args[1])
            func_expr = self.visit(node.args[0])
            return f"({arr_expr}).filter({func_expr}).length"
        elif node.name == "arrayExists":
            arr_expr = self.visit(node.args[1])
            func_expr = self.visit(node.args[0])
            return f"({arr_expr}).some({func_expr})"
        elif node.name == "arrayFilter":
            arr_expr = self.visit(node.args[1])
            func_expr = self.visit(node.args[0])
            return f"({arr_expr}).filter({func_expr})"
        elif node.name == "arrayMap":
            arr_expr = self.visit(node.args[1])
            func_expr = self.visit(node.args[0])
            return f"({arr_expr}).map({func_expr})"
        elif node.name == "md5Hex":
            expr_code = self.visit(node.args[0])
            return f"md5({expr_code})"  # Assuming md5 function is available
        elif node.name == "sha256Hex":
            expr_code = self.visit(node.args[0])
            return f"sha256({expr_code})"  # Assuming sha256 function is available
        elif node.name == "sha256HmacChainHex":
            args_code = ", ".join([self.visit(arg) for arg in node.args])
            return f"sha256HmacChainHex([{args_code}])"
        elif node.name == "position":
            str_expr = self.visit(node.args[0])
            substr_expr = self.visit(node.args[1])
            return f"({str_expr}).indexOf({substr_expr}) + 1"
        elif node.name == "positionCaseInsensitive":
            str_expr = self.visit(node.args[0])
            substr_expr = self.visit(node.args[1])
            return f"({str_expr}).toLowerCase().indexOf(({substr_expr}).toLowerCase()) + 1"
        elif node.name == "print":
            args_code = ", ".join([f"printHogStringOutput({self.visit(arg)})" for arg in node.args])
            self.inlined_stl.add("print")
            return f"console.log({args_code})"
        elif node.name == "like":
            str_expr = self.visit(node.args[0])
            pattern_expr = self.visit(node.args[1])
            regex_expr = f'new RegExp("^" + {pattern_expr}.replace(/[.*+?^${{}}()|[\\]\\\\]/g, "\\\\$&").replace(/%/g, ".*").replace(/_/g, ".") + "$")'
            return f"({regex_expr}).test({str_expr})"
        elif node.name == "ilike":
            str_expr = self.visit(node.args[0])
            pattern_expr = self.visit(node.args[1])
            regex_expr = f'new RegExp("^" + {pattern_expr}.replace(/[.*+?^${{}}()|[\\]\\\\]/g, "\\\\$&").replace(/%/g, ".*").replace(/_/g, ".") + "$", "i")'
            return f"({regex_expr}).test({str_expr})"
        elif node.name == "notLike":
            str_expr = self.visit(node.args[0])
            pattern_expr = self.visit(node.args[1])
            regex_expr = f'new RegExp("^" + {pattern_expr}.replace(/[.*+?^${{}}()|[\\]\\\\]/g, "\\\\$&").replace(/%/g, ".*").replace(/_/g, ".") + "$")'
            return f"!({regex_expr}).test({str_expr})"
        elif node.name == "notILike":
            str_expr = self.visit(node.args[0])
            pattern_expr = self.visit(node.args[1])
            regex_expr = f'new RegExp("^" + {pattern_expr}.replace(/[.*+?^${{}}()|[\\]\\\\]/g, "\\\\$&").replace(/%/g, ".*").replace(/_/g, ".") + "$", "i")'
            return f"!({regex_expr}).test({str_expr})"
        elif node.name == "match":
            str_expr = self.visit(node.args[0])
            regex_expr = self.visit(node.args[1])
            return f"new RegExp({regex_expr}).test({str_expr})"
        elif node.name == "toUnixTimestamp":
            input_expr = self.visit(node.args[0])
            return f"(Date.parse({input_expr}) / 1000)"
        elif node.name == "fromUnixTimestamp":
            input_expr = self.visit(node.args[0])
            return f"new Date({input_expr} * 1000)"
        elif node.name == "toUnixTimestampMilli":
            input_expr = self.visit(node.args[0])
            return f"Date.parse({input_expr})"
        elif node.name == "fromUnixTimestampMilli":
            input_expr = self.visit(node.args[0])
            return f"new Date({input_expr})"
        elif node.name == "toDate":
            input_expr = self.visit(node.args[0])
            return f"new Date({input_expr})"
        elif node.name == "toDateTime":
            input_expr = self.visit(node.args[0])
            return f"new Date({input_expr})"
        elif node.name == "formatDateTime":
            input_expr = self.visit(node.args[0])
            format_expr = self.visit(node.args[1])
            # Note: For proper date formatting, consider using a library like 'date-fns' or 'moment.js'
            return f"formatDateTime({input_expr}, {format_expr})"  # Assuming formatDateTime is defined
        elif node.name in ["HogError", "Error", "RetryError", "NotImplementedError"]:
            message_expr = self.visit(node.args[0]) if len(node.args) > 0 else '"Error"'
            return f"new Error({message_expr})"
        else:
            # Regular function calls
            args = node.params if node.params is not None else node.args
            args_code = ", ".join([self.visit(arg) for arg in args])
            return f"{node.name}({args_code})"

    def visit_expr_call(self, node: ast.ExprCall):
        func_code = self.visit(node.expr)
        args_code = ", ".join([self.visit(arg) for arg in node.args])
        return f"{func_code}({args_code})"

    def visit_program(self, node: ast.Program):
        code_lines = []
        self._start_scope()
        for declaration in node.declarations:
            code = self.visit(declaration)
            code_lines.append(self._indent(code))
        self._end_scope()
        return "\n".join(code_lines)

    def visit_block(self, node: ast.Block):
        code_lines = []
        self._start_scope()
        self.indent_level += 1
        for declaration in node.declarations:
            code = self.visit(declaration)
            code_lines.append(self._indent(code))
        self.indent_level -= 1
        self._end_scope()
        return "{\n" + "\n".join(code_lines) + "\n" + ("    " * self.indent_level) + "}"

    def visit_expr_statement(self, node: ast.ExprStatement):
        if node.expr is None:
            return ""
        expr_code = self.visit(node.expr)
        return expr_code + ";"

    def visit_return_statement(self, node: ast.ReturnStatement):
        if node.expr:
            return f"return {self.visit(node.expr)};"
        else:
            return "return null;"

    def visit_throw_statement(self, node: ast.ThrowStatement):
        return f"throw {self.visit(node.expr)};"

    def visit_try_catch_statement(self, node: ast.TryCatchStatement):
        try_code = self.visit(_as_block(node.try_stmt))
        code = "try " + try_code + " catch (__error) { "
        for index, catch in enumerate(node.catches):
            catch_var = catch[0] or "e"
            catch_type = str(catch[1])
            catch_declarations = _as_block(catch[2])
            catch_code = "".join(self._indent(self.visit(d)) for d in catch_declarations.declarations)
            if index > 0:
                code += " else "
            if catch_type and catch_type != "Error":
                code += (
                    f"if (__error.name === {json.dumps(catch_type)}) {{ let {_sanitize_var_name(catch_var)} = __error;\n"
                    f"{catch_code}\n"
                    f"}}\n"
                )
            else:
                f"if (true) {{ let {_sanitize_var_name(catch_var)} = __error;\n"
                f"{catch_code}\n"
                f"}}\n"
        code += "}"

        if node.finally_stmt:
            finally_code = self.visit(_as_block(node.finally_stmt))
            code += " finally " + finally_code
        return code

    def visit_if_statement(self, node: ast.IfStatement):
        expr_code = self.visit(node.expr)
        then_code = self.visit(_as_block(node.then))
        code = f"if ({expr_code}) {then_code}"
        if node.else_:
            else_code = self.visit(_as_block(node.else_))
            code += f" else {else_code}"
        return code

    def visit_while_statement(self, node: ast.WhileStatement):
        expr_code = self.visit(node.expr)
        body_code = self.visit(_as_block(node.body))
        return f"while ({expr_code}) {body_code}"

    def visit_for_statement(self, node: ast.ForStatement):
        init_code = self.visit(node.initializer) if node.initializer else ""
        init_code = init_code[:-1] if init_code.endswith(";") else init_code
        condition_code = self.visit(node.condition) if node.condition else ""
        condition_code = condition_code[:-1] if condition_code.endswith(";") else condition_code
        increment_code = self.visit(node.increment) if node.increment else ""
        increment_code = increment_code[:-1] if increment_code.endswith(";") else increment_code
        body_code = self.visit(_as_block(node.body))
        return f"for ({init_code}; {condition_code}; {increment_code}) {body_code}"

    def visit_for_in_statement(self, node: ast.ForInStatement):
        expr_code = self.visit(node.expr)
        body_code = self.visit(_as_block(node.body))
        if node.keyVar and node.valueVar:
            return f"for (let {_sanitize_var_name(node.keyVar)} in {expr_code}) {{\n    let {_sanitize_var_name(node.valueVar)} = {expr_code}[{_sanitize_var_name(node.keyVar)}];\n{self._indent(body_code)}\n}}"
        elif node.valueVar:
            return f"for (let {_sanitize_var_name(node.valueVar)} of {expr_code}) {body_code}"
        else:
            raise QueryError("ForInStatement requires at least a valueVar")

    def visit_variable_declaration(self, node: ast.VariableDeclaration):
        self._declare_local(node.name)
        if node.expr:
            expr_code = self.visit(node.expr)
            return f"let {_sanitize_var_name(node.name)} = {expr_code};"
        else:
            return f"let {_sanitize_var_name(node.name)};"

    def visit_variable_assignment(self, node: ast.VariableAssignment):
        left_code = self.visit(node.left)
        right_code = self.visit(node.right)
        return f"{left_code} = {right_code};"

    def visit_function(self, node: ast.Function):
        self._declare_local(node.name)
        params_code = ", ".join(_sanitize_var_name(p) for p in node.params)
        self._start_scope()
        for arg in node.params:
            self._declare_local(arg)
        body_code = self.visit(_as_block(node.body))
        self._end_scope()
        return f"function {_sanitize_var_name(node.name)}({params_code}) {body_code}"

    def visit_lambda(self, node: ast.Lambda):
        params_code = ", ".join(_sanitize_var_name(p) for p in node.args)
        self._start_scope()
        for arg in node.args:
            self._declare_local(arg)
        expr_code = self.visit(node.expr)
        self._end_scope()
        return f"({params_code}) => {expr_code}"

    def visit_dict(self, node: ast.Dict):
        items_code = ", ".join([f"{self.visit(key)}: {self.visit(value)}" for key, value in node.items])
        return f"{{{items_code}}}"

    def visit_array(self, node: ast.Array):
        items_code = ", ".join([self.visit(expr) for expr in node.exprs])
        return f"[{items_code}]"

    def visit_tuple(self, node: ast.Tuple):
        items_code = ", ".join([self.visit(expr) for expr in node.exprs])
        return f"[{items_code}]"

    def visit_hogqlx_tag(self, node: ast.HogQLXTag):
        # Assuming HogQLXTag corresponds to JSX-like syntax
        kind_code = node.kind
        attrs_code = " ".join([f"{attr.name}={{{self.visit(attr.value)}}}" for attr in node.attributes])
        return f"<{kind_code} {attrs_code} />"

    def _visit_hogqlx_value(self, value: Any) -> str:
        if isinstance(value, AST):
            return self.visit(value)
        if isinstance(value, list):
            elems = ", ".join([self._visit_hogqlx_value(v) for v in value])
            return f"[{elems}]"
        if isinstance(value, dict):
            items = ", ".join(
                [f"{self._visit_hogqlx_value(k)}: {self._visit_hogqlx_value(v)}" for k, v in value.items()]
            )
            return f"{{{items}}}"
        if isinstance(value, StrEnum):
            return '"' + str(value.value) + '"'
        if isinstance(value, int):
            return str(value)
        if isinstance(value, float):
            return str(value)
        if isinstance(value, str):
            return '"' + value.replace('"', '\\"') + '"'
        if value is True:
            return "true"
        if value is False:
            return "false"
        return "null"
