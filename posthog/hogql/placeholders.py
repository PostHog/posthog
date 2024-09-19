from typing import Optional

from hogvm.python.execute import execute_bytecode
from posthog.hogql import ast
from posthog.hogql.errors import QueryError
from posthog.hogql.visitor import CloningVisitor, TraversingVisitor


def replace_placeholders(node: ast.Expr, placeholders: Optional[dict[str, ast.Expr]]) -> ast.Expr:
    return ReplacePlaceholders(placeholders).visit(node)


def find_placeholders(node: ast.Expr) -> list[ast.Placeholder]:
    finder = FindPlaceholders()
    finder.visit(node)
    return list(finder.found)


class FindPlaceholders(TraversingVisitor):
    def __init__(self):
        super().__init__()
        self.found: list[ast.Placeholder] = []

    def visit_cte(self, node: ast.CTE):
        super().visit(node.expr)

    def visit_placeholder(self, node: ast.Placeholder):
        self.found.append(node)


class ReplacePlaceholders(CloningVisitor):
    def __init__(self, placeholders: Optional[dict[str, ast.Expr]]):
        super().__init__()
        self.placeholders = placeholders

    def visit_placeholder(self, node):
        from posthog.hogql.bytecode import create_bytecode

        bytecode = create_bytecode(expr=ast.ReturnStatement(expr=node.expr))

        # TODO: add some real values
        self.placeholders["vars"] = {"team_id": 1, "zone": 3, "limit": 10, "message": "Believe in Pasta!"}

        result = execute_bytecode(bytecode, globals=self.placeholders).result
        if (
            result is None
            or isinstance(result, bool)
            or isinstance(result, int)
            or isinstance(result, float)
            or isinstance(result, str)
        ):
            return ast.Constant(value=result)
        elif isinstance(result, ast.AST):
            return result
        elif isinstance(result, dict) and "__hx_ast" in result:
            return ast.deserialize_hx_ast(result)
        else:
            raise QueryError(f"Expected a constant value, but got {result}")
