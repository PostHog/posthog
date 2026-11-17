from functools import lru_cache
from typing import Optional

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr

from posthog.exceptions_capture import capture_exception


def _extract_join_key_field(expr: ast.Expr) -> Optional[ast.Field]:
    if isinstance(expr, ast.Field):
        return expr

    if isinstance(expr, ast.Alias):
        return _extract_join_key_field(expr.expr)

    if isinstance(expr, ast.Call):
        # The field can be in any argument, not just the first: e.g. `if(cond, field, NULL)` carries
        # it in args[1], with a non-field condition in args[0].
        for arg in expr.args:
            field = _extract_join_key_field(arg)
            if field is not None:
                return field

    return None


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

    field.chain = [table_name, *field.chain]
    return expr
