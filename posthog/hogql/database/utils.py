from typing import Optional

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr

from posthog.exceptions_capture import capture_exception


def _extract_field_chain(expr: ast.Expr) -> Optional[list[str | int]]:
    if isinstance(expr, ast.Field):
        return expr.chain

    if isinstance(expr, ast.Alias):
        return _extract_field_chain(expr.expr)

    if isinstance(expr, ast.Call) and len(expr.args) > 0:
        # We always descend into the first argument; the join-key field is expected to be args[0].
        return _extract_field_chain(expr.args[0])

    return None


def get_join_field_chain(key: str) -> Optional[list[str | int]]:
    field = parse_expr(key)
    field_chain = _extract_field_chain(field)
    if field_chain is not None:
        return field_chain

    capture_exception(Exception(f"Data Warehouse Join HogQL expression should be a Field or Call node: {key}"))
    return None
