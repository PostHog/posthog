from typing import Dict

from posthog.hogql import ast
from posthog.hogql.errors import HogQLException
from posthog.hogql.visitor import CloningVisitor


def replace_placeholders(node: ast.Expr, placeholders: Dict[str, ast.Expr]) -> ast.Expr:
    return ReplacePlaceholders(placeholders).visit(node)


class ReplacePlaceholders(CloningVisitor):
    def __init__(self, placeholders: Dict[str, ast.Expr]):
        super().__init__()
        self.placeholders = placeholders

    def visit_placeholder(self, node):
        if node.field in self.placeholders:
            new_node = self.placeholders[node.field]
            new_node.start = node.start
            new_node.end = node.end
            return new_node
        raise HogQLException(
            f"Placeholder '{node.field}' not found in provided dict: {', '.join(list(self.placeholders))}"
        )


def assert_no_placeholders(node: ast.Expr):
    AssertNoPlaceholders().visit(node)


class AssertNoPlaceholders(CloningVisitor):
    def visit_placeholder(self, node):
        raise HogQLException(f"Placeholder '{node.field}' not allowed in this context")
