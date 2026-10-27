from collections.abc import Sequence

from posthog.hogql import ast

# In non-nullable materialized columns these stored strings are treated as NULL.
MAT_COL_NULL_SENTINELS: tuple[str, ...] = ("", "null")


def null_if_sentinels(expr: ast.Expr, sentinels: Sequence[str] = MAT_COL_NULL_SENTINELS) -> ast.Expr:
    """`expr` with each of `sentinels` read as NULL, the way HogQL reads a non-nullable materialized column.

    The sentinels render inline, so the printed SQL matches the JSON-extract read of the same property.
    """
    for sentinel in sentinels:
        expr = ast.Call(name="nullIf", args=[expr, ast.Constant(value=sentinel, inline_sentinel=True)])
    return expr
