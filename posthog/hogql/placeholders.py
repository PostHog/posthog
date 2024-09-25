from typing import Optional, cast

from posthog.hogql import ast
from posthog.hogql.errors import QueryError
from posthog.hogql.visitor import CloningVisitor, TraversingVisitor


def replace_placeholders(node: ast.Expr, placeholders: Optional[dict[str | None, ast.Expr]]) -> ast.Expr:
    return ReplacePlaceholders(placeholders).visit(node)


def find_placeholders(node: ast.Expr) -> list[str | None]:
    finder = FindPlaceholders()
    finder.visit(node)
    return list(finder.found)


class FindPlaceholders(TraversingVisitor):
    def __init__(self):
        super().__init__()
        self.found: set[str | None] = set()

    def visit_cte(self, node: ast.CTE):
        super().visit(node.expr)

    def visit_placeholder(self, node: ast.Placeholder):
        self.found.add(node.field)


class ReplacePlaceholders(CloningVisitor):
    def __init__(self, placeholders: Optional[dict[str, ast.Expr]]):
        super().__init__()
        self.placeholders = placeholders

    # Lambdas in the form x -> {placeholder} need special handling
    def visit_block(self, node):
        if self.placeholders and len(node.declarations) == 1 and isinstance(node.declarations[0], ast.ExprStatement):
            expr = cast(ast.ExprStatement, node.declarations[0]).expr
            if isinstance(expr, ast.Field):
                field = ".".join(str(f) for f in expr.chain)
                if field in self.placeholders and self.placeholders[field] is not None:
                    new_node = self.placeholders[field]
                    new_node.start = node.start
                    new_node.end = node.end
                    return new_node
        return super().visit_block(node)

    def visit_placeholder(self, node):
        if node.field is None:
            raise QueryError("Placeholder expressions are not yet supported")
        if not self.placeholders:
            raise QueryError(f"Unresolved placeholder: {{{node.field}}}")
        if node.field in self.placeholders and self.placeholders[node.field] is not None:
            new_node = self.placeholders[node.field]
            new_node.start = node.start
            new_node.end = node.end
            return new_node
        raise QueryError(
            f"Placeholder {{{node.field}}} is not available in this context. You can use the following: "
            + ", ".join(f"{placeholder}" for placeholder in self.placeholders)
        )
