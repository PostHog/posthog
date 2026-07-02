from typing import Optional

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr
from posthog.hogql.visitor import GetFieldsTraverser


def _extract_join_key_field(expr: ast.Expr) -> Optional[ast.Field]:
    if isinstance(expr, ast.Field):
        return expr

    if isinstance(expr, ast.Alias):
        return _extract_join_key_field(expr.expr)

    if isinstance(expr, ast.Call):
        # Descend into the arguments and return the first field we find. This handles both
        # wrapper calls like toString(field) and conditional/multi-arg keys like
        # if(cond, field, NULL), where the field lives in a branch rather than args[0].
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

    # An unsupported user-configured join key is a known limitation, not an internal error,
    # so we don't capture it — join validation surfaces it to the user instead.
    return None


def qualify_join_key_expr(key: str, table_name: str) -> Optional[ast.Expr]:
    expr = parse_expr(key)
    fields = GetFieldsTraverser(expr).fields
    if not fields:
        return None

    # Qualify every field reference in the key with the table name so multi-field keys
    # (e.g. if(event = 'x', properties.y, NULL)) resolve against the right table.
    for field in fields:
        field.chain = [table_name, *field.chain]
    return expr
