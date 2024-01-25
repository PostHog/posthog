from typing import Dict, Optional, List

from posthog.hogql import ast
from posthog.hogql.errors import HogQLException
from posthog.hogql.visitor import CloningVisitor, TraversingVisitor


def replace_placeholders(node: ast.Expr, placeholders: Optional[Dict[str, ast.Expr]]) -> ast.Expr:
    return ReplacePlaceholders(placeholders).visit(node)


def find_placeholders(node: ast.Expr) -> List[str]:
    finder = FindPlaceholders()
    finder.visit(node)
    return list(finder.found)


class FindPlaceholders(TraversingVisitor):
    def __init__(self):
        super().__init__()
        self.found: set[str] = set()

    def visit_placeholder(self, node: ast.Placeholder):
        self.found.add(node.field)


class ReplacePlaceholders(CloningVisitor):
    def __init__(self, placeholders: Optional[Dict[str, ast.Expr]]):
        super().__init__()
        self.placeholders = placeholders

    def visit_placeholder(self, node):
        if not self.placeholders:
            raise HogQLException(f"Placeholders, such as {{{node.field}}}, are not supported in this context")
        if node.field in self.placeholders and self.placeholders[node.field] is not None:
            new_node = self.placeholders[node.field]
            new_node.start = node.start
            new_node.end = node.end
            return new_node
        else:
            return None
