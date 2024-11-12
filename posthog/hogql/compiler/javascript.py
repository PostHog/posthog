import dataclasses
from enum import StrEnum
from typing import Any, Optional

from posthog.hogql import ast
from posthog.hogql.base import AST
from posthog.hogql.context import HogQLContext
from posthog.hogql.errors import QueryError
from posthog.hogql.visitor import Visitor


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
    return CompiledJavaScript(code=code, locals=compiler.locals)


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

        # Initialize locals with function arguments
        for arg in self.args:
            self._declare_local(arg)

    def _start_scope(self):
        self.scope_depth += 1

    def _end_scope(self):
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
            ast.CompareOperationOp.Eq: "==",
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
            # Escape special regex characters in pattern
            pattern_code = f'({right_code}).replace(/[.*+?^${{}}()|[\\]\\\\]/g, "\\\\$&")'
            regex_code = f'new RegExp("^" + {pattern_code}.replace(/%/g, ".*").replace(/_/g, ".") + "$")'
            return f"({regex_code}).test({left_code})"
        elif op == ast.CompareOperationOp.ILike:
            pattern_code = f'({right_code}).replace(/[.*+?^${{}}()|[\\]\\\\]/g, "\\\\$&")'
            regex_code = f'new RegExp("^" + {pattern_code}.replace(/%/g, ".*").replace(/_/g, ".") + "$", "i")'
            return f"({regex_code}).test({left_code})"
        elif op == ast.CompareOperationOp.NotLike:
            pattern_code = f'({right_code}).replace(/[.*+?^${{}}()|[\\]\\\\]/g, "\\\\$&")'
            regex_code = f'new RegExp("^" + {pattern_code}.replace(/%/g, ".*").replace(/_/g, ".") + "$")'
            return f"!({regex_code}).test({left_code})"
        elif op == ast.CompareOperationOp.NotILike:
            pattern_code = f'({right_code}).replace(/[.*+?^${{}}()|[\\]\\\\]/g, "\\\\$&")'
            regex_code = f'new RegExp("^" + {pattern_code}.replace(/%/g, ".*").replace(/_/g, ".") + "$", "i")'
            return f"!({regex_code}).test({left_code})"
        elif op == ast.CompareOperationOp.Regex:
            return f"new RegExp({right_code}).test({left_code})"
        elif op == ast.CompareOperationOp.IRegex:
            return f'new RegExp({right_code}, "i").test({left_code})'
        elif op == ast.CompareOperationOp.NotRegex:
            return f"!new RegExp({right_code}).test({left_code})"
        elif op == ast.CompareOperationOp.NotIRegex:
            return f'!new RegExp({right_code}, "i").test({left_code})'
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
        code_parts = []
        for element in node.chain:
            if isinstance(element, str):
                if code_parts:
                    code_parts.append("." + element)
                else:
                    code_parts.append(element)
            elif isinstance(element, int):
                code_parts.append(f"[{element}]")
            else:
                raise QueryError(f"Unsupported field element type: {type(element)}")
        code = "".join(code_parts)
        return code

    def visit_tuple_access(self, node: ast.TupleAccess):
        tuple_code = self.visit(node.tuple)
        index_code = str(node.index)

        # Adjust index for 1-based indexing and handle negative indices
        adjusted_index = f"""(
            ({index_code}) > 0
                ? ({index_code} - 1)
                : (({tuple_code}).length + ({index_code}))
        )"""

        if node.nullish:
            return f"({tuple_code}?.[{adjusted_index.strip()}])"
        else:
            return f"{tuple_code}[{adjusted_index.strip()}]"

    def visit_array_access(self, node: ast.ArrayAccess):
        array_code = self.visit(node.array)
        property_code = self.visit(node.property)

        # Adjust index for 1-based indexing and handle negative indices
        adjusted_index = f"""(
            ({property_code}) > 0
                ? ({property_code} - 1)
                : (({array_code}).length + ({property_code}))
        )"""

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
        elif isinstance(value, int):
            return str(value)
        elif isinstance(value, float):
            return str(value)
        elif isinstance(value, str):
            return '"' + value.replace('"', '\\"') + '"'
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
            else_code = self.visit(node.args[2]) if len(node.args) == 3 else "undefined"
            return f"({condition_code} ? {then_code} : {else_code})"
        if node.name == "multiIf" and len(node.args) >= 2:
            # Generate nested ternary operators
            def build_nested_if(args):
                if len(args) == 2:
                    condition_code = self.visit(args[0])
                    then_code = self.visit(args[1])
                    return f"({condition_code} ? {then_code} : undefined)"
                elif len(args) == 3:
                    condition_code = self.visit(args[0])
                    then_code = self.visit(args[1])
                    else_code = self.visit(args[2])
                    return f"({condition_code} ? {then_code} : {else_code})"
                else:
                    condition_code = self.visit(args[0])
                    then_code = self.visit(args[1])
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
            return f"String({expr_code})"
        elif node.name == "toUUID":
            expr_code = self.visit(node.args[0])
            return f"String({expr_code})"
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
            args_code = ", ".join([self.visit(arg) for arg in node.args])
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
            expr_code = self.visit(node.expr)
            return f"return {expr_code};"
        else:
            return "return;"

    def visit_throw_statement(self, node: ast.ThrowStatement):
        expr_code = self.visit(node.expr)
        return f"throw {expr_code};"

    def visit_try_catch_statement(self, node: ast.TryCatchStatement):
        try_code = self.visit(node.try_stmt)
        code = "try " + try_code
        for catch in node.catches:
            catch_var = catch[0] or "e"
            catch_type = catch[1]
            catch_stmt = catch[2]
            catch_code = self.visit(catch_stmt)
            if catch_type and catch_type != "Error":
                code += (
                    f" catch ({catch_var}) {{\n"
                    f'    if ({catch_var}.name === "{catch_type}") {{\n'
                    f"{self._indent(catch_code)}\n"
                    f"    }} else throw {catch_var};\n"
                    f"}}"
                )
            else:
                code += f" catch ({catch_var}) " + catch_code
        if node.finally_stmt:
            finally_code = self.visit(node.finally_stmt)
            code += " finally " + finally_code
        return code

    def visit_if_statement(self, node: ast.IfStatement):
        expr_code = self.visit(node.expr)
        then_code = self.visit(node.then)
        code = f"if ({expr_code}) {then_code}"
        if node.else_:
            else_code = self.visit(node.else_)
            code += f" else {else_code}"
        return code

    def visit_while_statement(self, node: ast.WhileStatement):
        expr_code = self.visit(node.expr)
        body_code = self.visit(node.body)
        return f"while ({expr_code}) {body_code}"

    def visit_for_statement(self, node: ast.ForStatement):
        init_code = self.visit(node.initializer) if node.initializer else ""
        condition_code = self.visit(node.condition) if node.condition else ""
        increment_code = self.visit(node.increment) if node.increment else ""
        body_code = self.visit(node.body)
        return f"for ({init_code}; {condition_code}; {increment_code}) {body_code}"

    def visit_for_in_statement(self, node: ast.ForInStatement):
        expr_code = self.visit(node.expr)
        body_code = self.visit(node.body)
        if node.keyVar and node.valueVar:
            return f"for (let {node.keyVar} in {expr_code}) {{\n    let {node.valueVar} = {expr_code}[{node.keyVar}];\n{self._indent(body_code)}\n}}"
        elif node.valueVar:
            return f"for (let {node.valueVar} of {expr_code}) {body_code}"
        else:
            raise QueryError("ForInStatement requires at least a valueVar")

    def visit_variable_declaration(self, node: ast.VariableDeclaration):
        self._declare_local(node.name)
        if node.expr:
            expr_code = self.visit(node.expr)
            return f"let {node.name} = {expr_code};"
        else:
            return f"let {node.name};"

    def visit_variable_assignment(self, node: ast.VariableAssignment):
        left_code = self.visit(node.left)
        right_code = self.visit(node.right)
        return f"{left_code} = {right_code};"

    def visit_function(self, node: ast.Function):
        self._declare_local(node.name)
        params_code = ", ".join(node.params)
        body_code = self.visit(node.body)
        return f"function {node.name}({params_code}) {body_code}"

    def visit_lambda(self, node: ast.Lambda):
        params_code = ", ".join(node.args)
        expr_code = self.visit(node.expr)
        return f"({params_code}) => {expr_code}"

    def visit_dict(self, node: ast.Dict):
        items_code = ", ".join([f"{self.visit(key)}: {self.visit(value)}" for key, value in node.items])
        return f"{{ {items_code} }}"

    def visit_array(self, node: ast.Array):
        items_code = ", ".join([self.visit(expr) for expr in node.exprs])
        return f"[ {items_code} ]"

    def visit_tuple(self, node: ast.Tuple):
        items_code = ", ".join([self.visit(expr) for expr in node.exprs])
        return f"[ {items_code} ]"

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
            return f"[ {elems} ]"
        if isinstance(value, dict):
            items = ", ".join(
                [f"{self._visit_hogqlx_value(k)}: {self._visit_hogqlx_value(v)}" for k, v in value.items()]
            )
            return f"{{ {items} }}"
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
