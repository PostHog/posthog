from typing import Optional

from posthog.hogql import ast
from posthog.hogql.errors import QueryError
from posthog.hogql.visitor import CloningVisitor, TraversingVisitor


def replace_placeholders(node: ast.Expr, placeholders: Optional[dict[str, ast.Expr]]) -> ast.Expr:
    return ReplacePlaceholders(placeholders).visit(node)


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
        if True:  # TODO: HOG_PLACEHOLDERS feature flag
            from hogvm.python.execute import execute_bytecode
            from posthog.hogql.bytecode import create_bytecode

            bytecode = create_bytecode(node.expr)
            response = execute_bytecode(bytecode, self.placeholders)
            if isinstance(response.result, ast.Expr):
                return response.result
            else:
                return ast.Constant(value=response.result)
        else:
            if not self.placeholders:  # type: ignore
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
