from functools import lru_cache
from typing import Optional

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr
from posthog.hogql.visitor import TraversingVisitor

from posthog.exceptions_capture import capture_exception


def _extract_join_key_field(expr: ast.Expr) -> Optional[ast.Field]:
    if isinstance(expr, ast.Field):
        return expr

    if isinstance(expr, ast.Alias):
        return _extract_join_key_field(expr.expr)

    if isinstance(expr, ast.Call):
        # The field is not always the first argument: in `if(event = 'x', properties.domain, NULL)`
        # the first argument is a comparison, so take the first argument that holds a field.
        for arg in expr.args:
            field = _extract_join_key_field(arg)
            if field is not None:
                return field

    return None


class _JoinKeyQualifier(TraversingVisitor):
    def __init__(self, table_name: str) -> None:
        super().__init__()
        self.table_name = table_name
        self.lambda_args: list[str] = []

    def visit_lambda(self, node: ast.Lambda) -> None:
        outer_args = self.lambda_args
        self.lambda_args = [*outer_args, *node.args]
        self.visit(node.expr)
        self.lambda_args = outer_args

    def visit_field(self, node: ast.Field) -> None:
        if node.chain and node.chain[0] in self.lambda_args:
            return
        node.chain = [self.table_name, *node.chain]


@lru_cache(maxsize=4096)
def _cached_join_field_chain(key: str) -> Optional[tuple[str | int, ...]]:
    """Parse each join key once and store only its immutable field chain."""
    expr = parse_expr(key)
    field = _extract_join_key_field(expr)
    if field is not None:
        return tuple(field.chain)

    capture_exception(Exception(f"Data Warehouse Join HogQL expression should be a Field or Call node: {key}"))
    return None


def get_join_field_chain(key: str) -> Optional[list[str | int]]:
    chain = _cached_join_field_chain(key)
    return list(chain) if chain is not None else None


def qualify_join_key_expr(key: str, table_name: str) -> Optional[ast.Expr]:
    expr = parse_expr(key)
    field = _extract_join_key_field(expr)
    if field is None:
        return None

    # Qualify every field, so that a field in a condition also resolves against the source table.
    _JoinKeyQualifier(table_name).visit(expr)
    return expr
