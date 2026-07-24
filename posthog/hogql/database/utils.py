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
        # The field isn't always the first argument. For conditional keys like
        # `if(event = 'X', properties.domain, NULL)` the field sits in a later argument,
        # so search every argument and return the first one that resolves to a Field.
        for arg in expr.args:
            field = _extract_join_key_field(arg)
            if field is not None:
                return field

    return None


def get_join_field_chain(key: str) -> Optional[list[str | int]]:
    expr = parse_expr(key)
    field = _extract_join_key_field(expr)
    if field is not None:
        return field.chain

    capture_exception(Exception(f"Data Warehouse Join HogQL expression should be a Field or Call node: {key}"))
    return None


def qualify_join_key_expr(key: str, table_name: str) -> Optional[ast.Expr]:
    expr = parse_expr(key)
    field = _extract_join_key_field(expr)
    if field is None:
        return None

    field.chain = [table_name, *field.chain]
    return expr
