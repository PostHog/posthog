from typing import Optional

from posthog.hogql import ast
from posthog.hogql.errors import QueryError
from posthog.hogql.utils import deserialize_hx_ast, is_simple_value
from posthog.hogql.visitor import CloningVisitor, TraversingVisitor


class FindPlaceholders(TraversingVisitor):
    def __init__(self):
        super().__init__()
        self.has_filters = False  # Legacy fallback: treat filters as before
        self.placeholder_fields: list[list[str | int]] = []  # Did we find simple fields
        self.placeholder_expressions: list[ast.Expr] = []  # Did we find complex expressions

    def visit_cte(self, node: ast.CTE):
        super().visit(node.expr)

    def visit_placeholder(self, node: ast.Placeholder):
        if chain := node.chain:
            if chain[0] == "filters":
                self.has_filters = True
            else:
                self.placeholder_fields.append(chain)
        else:
            self.placeholder_expressions.append(node.expr)


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
        from posthog.hogql.compiler.bytecode import create_bytecode

        from common.hogvm.python.execute import execute_bytecode

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
