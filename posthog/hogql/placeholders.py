from typing import Optional

from posthog.hogql import ast
from posthog.hogql.errors import QueryError
from posthog.hogql.visitor import CloningVisitor, TraversingVisitor


def replace_placeholders(node: ast.Expr, placeholders: Optional[dict[str, ast.Expr]]) -> ast.Expr:
    return ReplacePlaceholders(placeholders).visit(node)


def find_placeholders(node: ast.Expr) -> list[str]:
    finder = FindPlaceholders()
    finder.visit(node)
    return list(finder.found)


class FindPlaceholders(TraversingVisitor):
    def __init__(self):
        super().__init__()
        self.found: set[str] = set()

    def visit_cte(self, node: ast.CTE):
        super().visit(node.expr)

    def visit_block(self, node: ast.Block):
        # TODO: remove all this when we can use bytecode in placeholders
        if len(node.declarations) > 1:
            raise QueryError("Placeholders can only contain a single declaration")
        declaration = node.declarations[0]
        if not isinstance(declaration, ast.ExprStatement) and not isinstance(declaration, ast.ReturnStatement):
            raise QueryError("Placeholders can only contain a simple expression")
        if not isinstance(declaration.expr, ast.Field):
            raise QueryError("Placeholders can only contain a single field expression")
        self.found.add(".".join(str(c) for c in declaration.expr.chain))


class ReplacePlaceholders(CloningVisitor):
    def __init__(self, placeholders: Optional[dict[str, ast.Expr]]):
        super().__init__()
        self.placeholders = placeholders

    def visit_block(self, node: ast.Block):
        field = node.placeholder_chain
        if not field:
            raise QueryError("Placeholder must be a field expression")
        if not self.placeholders:
            raise QueryError(f"Unresolved placeholder: {{{field}}}")
        if field in self.placeholders and self.placeholders[field] is not None:
            new_node = self.placeholders[field]
            new_node.start = node.start
            new_node.end = node.end
            return new_node
        raise QueryError(
            f"Placeholder {{{field}}} is not available in this context. You can use the following: "
            + ", ".join(f"{placeholder}" for placeholder in self.placeholders)
        )
