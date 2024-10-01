from typing import Optional

from posthog.hogql import ast
from posthog.hogql.errors import QueryError
from posthog.hogql.visitor import CloningVisitor, TraversingVisitor, clone_expr


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

    def _visit_placeholder_via_bytecode(self, node):
        from hogvm.python.execute import execute_bytecode
        from posthog.hogql.bytecode import create_bytecode

        bytecode = create_bytecode(node.expr)
        response = execute_bytecode(bytecode, self.placeholders)
        if isinstance(response.result, ast.Expr):
            expr = clone_expr(response.result)
            expr.start = node.start
            expr.end = node.end
            return expr
        else:
            return ast.Constant(value=response.result, start=node.start, end=node.end)

    def _visit_placeholder_via_fields(self, node):
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

    def visit_placeholder(self, node):
        # TODO: HOG_PLACEHOLDERS feature flag
        bytecode_result = self._visit_placeholder_via_bytecode(node)
        fields_result = self._visit_placeholder_via_fields(node)
        if bytecode_result != fields_result:
            print("------")  # noqa: T201
            print(node)  # noqa: T201
            print(bytecode_result)  # noqa: T201
            print(fields_result)  # noqa: T201
            print(bytecode_result == fields_result)  # noqa: T201
        # return bytecode_result
        return fields_result
