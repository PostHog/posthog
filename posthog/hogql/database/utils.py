from typing import Optional

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr

from posthog.exceptions_capture import capture_exception


def get_join_field_chain(key: str) -> Optional[list[str | int]]:
    field = parse_expr(key)
    if isinstance(field, ast.Field):
        return field.chain

    if isinstance(field, ast.Alias) and isinstance(field.expr, ast.Call) and isinstance(field.expr.args[0], ast.Field):
        return field.expr.args[0].chain

    if isinstance(field, ast.Call) and isinstance(field.args[0], ast.Field):
        return field.args[0].chain

    capture_exception(Exception(f"Data Warehouse Join HogQL expression should be a Field or Call node: {key}"))
    return None
