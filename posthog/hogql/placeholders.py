from typing import Optional

from posthog.hogql import ast
from posthog.hogql.errors import QueryError
from posthog.hogql.utils import is_simple_value, deserialize_hx_ast
from posthog.hogql.visitor import CloningVisitor, TraversingVisitor


class FindPlaceholders(TraversingVisitor):
    def __init__(self):
        super().__init__()
        self.has_expr_placeholders = False
        self.has_filters = False
        self.field_strings: set[str] = set()

    def visit_cte(self, node: ast.CTE):
        super().visit(node.expr)

    def visit_placeholder(self, node: ast.Placeholder):
        field = node.field
        if field:
            if field == "filters" or field.startswith("filters."):
                self.has_filters = True
            else:
                self.field_strings.add(field)
        else:
            self.has_expr_placeholders = True


def find_placeholders(node: ast.Expr) -> FindPlaceholders:
    finder = FindPlaceholders()
    finder.visit(node)
    return finder


class ReplacePlaceholders(CloningVisitor):
    def __init__(self, placeholders: Optional[dict[str, ast.Expr]]):
        super().__init__()
        self.placeholders = placeholders

    def visit_placeholder(self, node):
        # avoid circular imports
        from common.hogvm.python.execute import execute_bytecode
        from posthog.hogql.compiler.bytecode import create_bytecode

        bytecode = create_bytecode(node.expr)
        response = execute_bytecode(bytecode.bytecode, self.placeholders)

        if isinstance(response.result, dict) and ("__hx_ast" in response.result or "__hx_tag" in response.result):
            response.result = deserialize_hx_ast(response.result)

        if (
            isinstance(response.result, ast.Expr)
            or isinstance(response.result, ast.SelectQuery)
            or isinstance(response.result, ast.SelectSetQuery)
            or isinstance(response.result, ast.HogQLXTag)
        ):
            expr = response.result
            expr.start = node.start
            expr.end = node.end
            return expr
        elif is_simple_value(response.result):
            return ast.Constant(value=response.result, start=node.start, end=node.end)
        raise QueryError(
            f"Placeholder returned an unexpected type: {type(response.result).__name__}. "
            "Expected an AST node or a simple value."
        )


def replace_placeholders(node: ast.Expr, placeholders: Optional[dict[str, ast.Expr]]) -> ast.Expr:
    return ReplacePlaceholders(placeholders).visit(node)
