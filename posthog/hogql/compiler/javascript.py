import re
import json
import dataclasses
from enum import StrEnum
from typing import Any, Optional

from posthog.hogql import ast
from posthog.hogql.base import AST
from posthog.hogql.compiler.javascript_stl import STL_FUNCTIONS, import_stl_functions
from posthog.hogql.errors import QueryError
from posthog.hogql.parser import parse_expr, parse_program
from posthog.hogql.visitor import Visitor

_JS_GET_GLOBAL = "__getGlobal"
_JS_KEYWORDS = {
    "await",
    "break",
    "case",
    "catch",
    "class",
    "const",
    "continue",
    "debugger",
    "default",
    "delete",
    "do",
    "else",
    "enum",
    "export",
    "extends",
    "false",
    "finally",
    "for",
    "function",
    "if",
    "import",
    "in",
    "instanceof",
    "new",
    "null",
    "return",
    "super",
    "switch",
    "this",
    "throw",
    "true",
    "try",
    "typeof",
    "var",
    "void",
    "while",
    "with",
    "yield",
    "implements",
    "interface",
    "let",
    "package",
    "private",
    "protected",
    "public",
    "static",
    "arguments",
    "eval",
    "Error",
    _JS_GET_GLOBAL,  # don't let this get overridden
}


@dataclasses.dataclass
class Local:
    name: str
    depth: int


def to_js_program(code: str) -> str:
    compiler = JavaScriptCompiler()
    code = compiler.visit(parse_program(code))
    imports = compiler.get_stl_code()
    return imports + ("\n\n" if imports else "") + code


def to_js_expr(expr: str | ast.Expr) -> str:
    if isinstance(expr, str):
        expr = parse_expr(expr)
    return JavaScriptCompiler().visit(expr)


def _as_block(node: ast.Statement) -> ast.Block:
    if isinstance(node, ast.Block):
        return node
    return ast.Block(declarations=[node])


def _sanitize_identifier(name: str | int) -> str:
    name = str(name)
    if re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", name):
        if name in _JS_KEYWORDS:
            return f"__x_{name}"
        if name.startswith("__x_"):
            # add a second __x_ to avoid conflicts with our internal variables
            return f"__x_{name}"
        return name
    else:
        return f"[{json.dumps(name)}]"


class JavaScriptCompiler(Visitor):
    def __init__(
        self,
        args: Optional[list[str]] = None,
        locals: Optional[list[Local]] = None,
    ):
        super().__init__()
        self.locals: list[Local] = locals or []
        self.scope_depth = 0
        self.args = args or []
        self.indent_level = 0
        self.stl_functions: set[str] = set()
        self.mode: str = "hog"

        # Initialize locals with function arguments
        for arg in self.args:
            self._declare_local(arg)

    def get_stl_code(self) -> str:
        return import_stl_functions(self.stl_functions)

    def _start_scope(self):
        self.scope_depth += 1

    def _end_scope(self):
        self.locals = [local for local in self.locals if local.depth < self.scope_depth]
        self.scope_depth -= 1

    def _declare_local(self, name: str):
        for local in reversed(self.locals):
            if local.depth == self.scope_depth and local.name == name:
                raise QueryError(f"Variable `{name}` already declared in this scope")
        self.locals.append(Local(name=name, depth=self.scope_depth))

    def _indent(self, code: str) -> str:
        indentation = "    " * self.indent_level
        return "\n".join(indentation + line if line else "" for line in code.split("\n"))

    def visit(self, node: ast.AST | None):
        # In "hog" mode we compile AST nodes to bytecode.
        # In "ast" mode we pass through as they are.
        # You may enter "ast" mode with `sql()` or `(select ...)`
        if self.mode == "hog" or isinstance(node, ast.Placeholder):
            return super().visit(node)
        return self._visit_hog_ast(node)

    def _visit_hog_ast(self, node: AST | None) -> str:
        if node is None:
            return "null"
        if isinstance(node, ast.HogQLXTag):
            tag_name = node.kind
            tag_is_callable = any(local for local in self.locals if local.name == tag_name)
            if tag_is_callable:
                return self.visit_hogqlx_tag(node)

        fields = [f'"__hx_ast": {json.dumps(node.__class__.__name__)}']
        for field in dataclasses.fields(node):
            if field.name in ["start", "end", "type"]:
                continue
            value = getattr(node, field.name)
            if value is None:
                continue
            fields.append(f"{json.dumps(field.name)}: {self._visit_hogqlx_value(value)}")
        return "{" + ", ".join(fields) + "}"

    def visit_and(self, node: ast.And):
        code = " && ".join([self.visit(expr) for expr in node.exprs])
        return f"!!({code})"

    def visit_or(self, node: ast.Or):
        code = " || ".join([self.visit(expr) for expr in node.exprs])
        return f"!!({code})"

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
            return f"({left_code} {op_map[op]} {right_code})"
        elif op == ast.CompareOperationOp.In:
            return f"({right_code}.includes({left_code}))"
        elif op == ast.CompareOperationOp.NotIn:
            return f"(!{right_code}.includes({left_code}))"
        elif op == ast.CompareOperationOp.Like:
            self.stl_functions.add("like")
            return f"like({left_code}, {right_code})"
        elif op == ast.CompareOperationOp.ILike:
            self.stl_functions.add("ilike")
            return f"ilike({left_code}, {right_code})"
        elif op == ast.CompareOperationOp.NotLike:
            self.stl_functions.add("like")
            return f"!like({left_code}, {right_code})"
        elif op == ast.CompareOperationOp.NotILike:
            self.stl_functions.add("ilike")
            return f"!ilike({left_code}, {right_code})"
        elif op == ast.CompareOperationOp.Regex:
            self.stl_functions.add("match")
            return f"match({left_code}, {right_code})"
        elif op == ast.CompareOperationOp.IRegex:
            self.stl_functions.add("__imatch")
            return f"__imatch({left_code}, {right_code})"
        elif op == ast.CompareOperationOp.NotRegex:
            self.stl_functions.add("match")
            return f"!match({left_code}, {right_code})"
        elif op == ast.CompareOperationOp.NotIRegex:
            self.stl_functions.add("__imatch")
            return f"!__imatch({left_code}, {right_code})"
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

    def visit_between_expr(self, node: ast.BetweenExpr):
        self._start_scope()
        expr = self.visit(node.expr)
        low = self.visit(node.low)
        high = self.visit(node.high)
        if node.negated:
            comparison = f"expr < {low} || expr > {high}"
        else:
            comparison = f"expr >= {low} && expr <= {high}"
        code = f"(() => {{ const expr=({expr}), low=({low}), high=({high}); return expr !== null && expr !== undefined && low !== null && low !== undefined && high !== null && high !== undefined && !!({comparison}); }})()"

        self._end_scope()
        return code

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
        array_code = ""
        for index, element in enumerate(node.chain):
            if index == 0:
                if found_local:
                    array_code = _sanitize_identifier(element)
                elif element in STL_FUNCTIONS:
                    self.stl_functions.add(str(element))
                    array_code = f"{_sanitize_identifier(element)}"
                else:
                    array_code = f"{_JS_GET_GLOBAL}({json.dumps(element)})"
                continue

            if (isinstance(element, int) and not isinstance(element, bool)) or isinstance(element, str):
                self.stl_functions.add("__getProperty")
                array_code = f"__getProperty({array_code}, {json.dumps(element)}, true)"
            else:
                raise QueryError(f"Unsupported element: {element} ({type(element)})")
        return array_code

    def visit_tuple_access(self, node: ast.TupleAccess):
        tuple_code = self.visit(node.tuple)
        index_code = str(node.index)
        self.stl_functions.add("__getProperty")
        return f"__getProperty({tuple_code}, {index_code}, {json.dumps(node.nullish)})"

    def visit_array_access(self, node: ast.ArrayAccess):
        array_code = self.visit(node.array)
        property_code = self.visit(node.property)
        self.stl_functions.add("__getProperty")
        return f"__getProperty({array_code}, {property_code}, {json.dumps(node.nullish)})"

    def visit_constant(self, node: ast.Constant):
        value = node.value
        if value is True:
            return "true"
        elif value is False:
            return "false"
        elif value is None:
            return "null"
        elif isinstance(value, int | float | str):
            return json.dumps(value)
        else:
            raise QueryError(f"Unsupported constant type: {type(value)}")

    def visit_call(self, node: ast.Call):
        # HogQL functions can come as name(params)(args), or name(args) if no params
        # If node.params is not None, it means we actually have something like name(params)(args).
        if node.params is not None:
            return self.visit(ast.ExprCall(expr=ast.Call(name=node.name, args=node.params), args=node.args or []))

        # Handle special functions
        if node.name == "not" and len(node.args) == 1:
            expr_code = self.visit(node.args[0])
            return f"(!{expr_code})"
        if node.name == "and" and len(node.args) > 1:
            exprs_code = " && ".join([self.visit(arg) for arg in node.args])
            return f"!!({exprs_code})"
        if node.name == "or" and len(node.args) > 1:
            exprs_code = " || ".join([self.visit(arg) for arg in node.args])
            return f"!!({exprs_code})"
        if node.name == "if" and len(node.args) >= 2:
            condition_code = self.visit(node.args[0])
            then_code = self.visit(node.args[1])
            else_code = self.visit(node.args[2]) if len(node.args) == 3 else "null"
            return f"({condition_code} ? {then_code} : {else_code})"
        if node.name == "multiIf" and len(node.args) >= 2:

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
        if node.name == "sql" and len(node.args) == 1:
            self.mode = "ast"
            response = self.visit(node.args[0])
            self.mode = "hog"
            return response

        if node.name in STL_FUNCTIONS:
            self.stl_functions.add(node.name)
            name = _sanitize_identifier(node.name)
            args_code = ", ".join(self.visit(arg) for arg in node.args)
            return f"{name}({args_code})"
        else:
            # Regular function calls
            name = _sanitize_identifier(node.name)
            args_code = ", ".join([self.visit(arg) for arg in node.args or []])
            return f"{name}({args_code})"

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
        has_catch_all = False
        for index, catch in enumerate(node.catches):
            catch_var = catch[0] or "e"
            self._start_scope()
            self._declare_local(catch_var)
            catch_type = str(catch[1]) if catch[1] is not None else None
            catch_declarations = _as_block(catch[2])
            catch_code = "".join(self._indent(self.visit(d)) for d in catch_declarations.declarations)
            if index > 0:
                code += " else "
            if catch_type is not None and catch_type != "Error":
                code += (
                    f"if (__error.type === {json.dumps(catch_type)}) {{ let {_sanitize_identifier(catch_var)} = __error;\n"
                    f"{catch_code}\n"
                    f"}}\n"
                )
            else:
                has_catch_all = True
                code += f"if (true) {{ let {_sanitize_identifier(catch_var)} = __error;\n" f"{catch_code}\n" f"}}\n"
            self._end_scope()
        if not has_catch_all:
            code += " else { throw __error; }"
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
        self._start_scope()
        init_code = self.visit(node.initializer) if node.initializer else ""
        init_code = init_code[:-1] if init_code.endswith(";") else init_code
        condition_code = self.visit(node.condition) if node.condition else ""
        condition_code = condition_code[:-1] if condition_code.endswith(";") else condition_code
        increment_code = self.visit(node.increment) if node.increment else ""
        increment_code = increment_code[:-1] if increment_code.endswith(";") else increment_code
        body_code = self.visit(_as_block(node.body))
        self._end_scope()
        return f"for ({init_code}; {condition_code}; {increment_code}) {body_code}"

    def visit_for_in_statement(self, node: ast.ForInStatement):
        expr_code = self.visit(node.expr)
        if node.keyVar and node.valueVar:
            self._start_scope()
            self._declare_local(node.keyVar)
            self._declare_local(node.valueVar)
            body_code = self.visit(_as_block(node.body))
            self.stl_functions.add("keys")
            resp = f"for (let {_sanitize_identifier(node.keyVar)} of keys({expr_code})) {{ let {_sanitize_identifier(node.valueVar)} = {expr_code}[{_sanitize_identifier(node.keyVar)}]; {body_code} }}"
            self._end_scope()
            return resp
        elif node.valueVar:
            self._start_scope()
            self._declare_local(node.valueVar)
            body_code = self.visit(_as_block(node.body))
            self.stl_functions.add("values")
            resp = f"for (let {_sanitize_identifier(node.valueVar)} of values({expr_code})) {body_code}"
            self._end_scope()
            return resp
        else:
            raise QueryError("ForInStatement requires at least a valueVar")

    def visit_variable_declaration(self, node: ast.VariableDeclaration):
        self._declare_local(node.name)
        if node.expr:
            expr_code = self.visit(node.expr)
            return f"let {_sanitize_identifier(node.name)} = {expr_code};"
        else:
            return f"let {_sanitize_identifier(node.name)};"

    def visit_variable_assignment(self, node: ast.VariableAssignment):
        if isinstance(node.left, ast.TupleAccess):
            tuple_code = self.visit(node.left.tuple)
            index = node.left.index
            right_code = self.visit(node.right)
            self.stl_functions.add("__setProperty")
            return f"__setProperty({tuple_code}, {index}, {right_code});"

        elif isinstance(node.left, ast.ArrayAccess):
            array_code = self.visit(node.left.array)
            property_code = self.visit(node.left.property)
            right_code = self.visit(node.right)
            self.stl_functions.add("__setProperty")
            return f"__setProperty({array_code}, {property_code}, {right_code});"

        elif isinstance(node.left, ast.Field):
            chain = node.left.chain
            name = chain[0]
            is_local = any(local.name == name for local in self.locals)

            if is_local:
                array_code = ""
                for index, element in enumerate(chain):
                    if index == 0:
                        array_code = _sanitize_identifier(element)
                        if len(chain) == 1:
                            array_code = f"{array_code} = {self.visit(node.right)}"
                    elif (isinstance(element, int) and not isinstance(element, bool)) or isinstance(element, str):
                        if index == len(chain) - 1:
                            right_code = self.visit(node.right)
                            self.stl_functions.add("__setProperty")
                            array_code = f"__setProperty({array_code}, {json.dumps(element)}, {right_code})"
                        else:
                            self.stl_functions.add("__getProperty")
                            array_code = f"__getProperty({array_code}, {json.dumps(element)}, true)"
                    else:
                        raise QueryError(f"Unsupported element: {element} ({type(element)})")
                return array_code

            else:
                # Cannot assign to undeclared variables or globals
                raise QueryError(f'Variable "{name}" not declared in this scope. Cannot assign to globals.')

        else:
            left_code = self.visit(node.left)
            right_code = self.visit(node.right)
            return f"{left_code} = {right_code};"

    def visit_function(self, node: ast.Function):
        self._declare_local(_sanitize_identifier(node.name))
        params_code = ", ".join(_sanitize_identifier(p) for p in node.params)
        self._start_scope()
        for arg in node.params:
            self._declare_local(arg)
        if isinstance(node.body, ast.Placeholder):
            body_code = ast.Block(declarations=[ast.ExprStatement(expr=node.body.expr), ast.ReturnStatement(expr=None)])
        else:
            body_code = self.visit(_as_block(node.body))
        self._end_scope()
        return f"function {_sanitize_identifier(node.name)}({params_code}) {body_code}"

    def visit_lambda(self, node: ast.Lambda):
        params_code = ", ".join(_sanitize_identifier(p) for p in node.args)
        self._start_scope()
        for arg in node.args:
            self._declare_local(arg)
        if isinstance(node.expr, ast.Placeholder):
            expr_code = self.visit(
                ast.Block(declarations=[ast.ExprStatement(expr=node.expr.expr), ast.ReturnStatement(expr=None)])
            )
        elif isinstance(node.expr, ast.Dict) or isinstance(node.expr, ast.HogQLXTag):
            expr_code = f"({self.visit(node.expr)})"
        else:
            expr_code = self.visit(node.expr)
        self._end_scope()
        self.stl_functions.add("__lambda")
        # we wrap it in __lambda() to make the function anonymous (a true lambda without a name)
        return f"__lambda(({params_code}) => {expr_code})"

    def visit_dict(self, node: ast.Dict):
        items = []
        for key, value in node.items:
            key_code = self.visit(key)
            if not isinstance(key, ast.Constant) or not isinstance(key.value, str):
                key_code = f"[{key_code}]"
            value_code = self.visit(value)
            items.append(f"{key_code}: {value_code}")
        items_code = ", ".join(items)
        return f"{{{items_code}}}"

    def visit_array(self, node: ast.Array):
        items_code = ", ".join([self.visit(expr) for expr in node.exprs])
        return f"[{items_code}]"

    def visit_tuple(self, node: ast.Tuple):
        items_code = ", ".join([self.visit(expr) for expr in node.exprs])
        self.stl_functions.add("tuple")
        return f"tuple({items_code})"

    def visit_hogqlx_tag(self, node: ast.HogQLXTag):
        if any(local for local in self.locals if local.name == node.kind):
            attrs = []
            for attr in node.attributes:
                attrs.append(f'"{attr.name}": {self._visit_hogqlx_value(attr.value)}')
            return f'{self.visit_field(ast.Field(chain=[node.kind]))}({{{", ".join(attrs)}}})'
        else:
            attrs = [f'"__hx_tag": {json.dumps(node.kind)}']
            for attr in node.attributes:
                attrs.append(f'"{attr.name}": {self._visit_hogqlx_value(attr.value)}')
            return f'{{{", ".join(attrs)}}}'

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
        if value is True:
            return "true"
        if value is False:
            return "false"
        if isinstance(value, int | float):
            return str(value)
        if isinstance(value, str):
            return json.dumps(value)
        return "null"

    def visit_placeholder(self, node: ast.Placeholder):
        if self.mode == "ast":
            self.mode = "hog"
            result = self.visit(node.expr)
            self.mode = "ast"
            return result
        raise QueryError("Placeholders are not allowed in this context")

    def _visit_select_query(self, node: ast.SelectQuery | ast.SelectSetQuery) -> str:
        # Select queries always trigger "ast" mode
        last_mode = self.mode
        self.mode = "ast"
        try:
            return self._visit_hog_ast(node)
        finally:
            self.mode = last_mode

    def visit_select_query(self, node: ast.SelectQuery):
        return self._visit_select_query(node)

    def visit_select_set_query(self, node: ast.SelectSetQuery):
        return self._visit_select_query(node)
