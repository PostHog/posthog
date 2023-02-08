from typing import Dict

from posthog.hogql import ast
from posthog.hogql.visitor import EverythingVisitor


def replace_placeholders(node: ast.Expr, placeholders: Dict[str, ast.Expr]) -> ast.Expr:
    return ReplacePlaceholders(placeholders).visit(node)


class ReplacePlaceholders(EverythingVisitor):
    def __init__(self, placeholders: Dict[str, ast.Expr]):
        self.placeholders = placeholders

    def visit_placeholder(self, node):
        if node.field in self.placeholders:
            return self.placeholders[node.field]
        raise ValueError(f"Placeholder '{node.field}' not found in provided dict: {', '.join(list(self.placeholders))}")
