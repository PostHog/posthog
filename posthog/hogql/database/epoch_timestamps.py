"""Reading integer warehouse columns as epoch timestamps.

Sources routinely deliver time columns as raw epoch integers (Stripe and Clerk among
them), and an integer column alone doesn't say whether it holds seconds, milliseconds,
microseconds, or nanoseconds. The unit is recoverable from magnitude instead: for any
timestamp between 1973 and 5138 the four units occupy disjoint bands, so each value can
be converted by the band it falls in rather than by guessing a single unit up front.
"""

from posthog.hogql import ast
from posthog.hogql.visitor import clone_expr

# Band boundaries: 1e11 is 1973-03 in milliseconds but the year 5138 in seconds, and the
# same thousand-fold relation separates each unit from the next one up.
_MILLISECONDS_LOWER_BOUND = 100_000_000_000
_MICROSECONDS_LOWER_BOUND = 100_000_000_000_000
_NANOSECONDS_LOWER_BOUND = 100_000_000_000_000_000

_INTEGER_CLICKHOUSE_TYPES = {
    "Int8",
    "Int16",
    "Int32",
    "Int64",
    "Int128",
    "Int256",
    "UInt8",
    "UInt16",
    "UInt32",
    "UInt64",
    "UInt128",
    "UInt256",
}


def is_integer_clickhouse_type(clickhouse_type: str | None) -> bool:
    """Whether a ClickHouse column type string, optionally Nullable-wrapped, is an integer type."""
    if clickhouse_type is None:
        return False
    unwrapped = clickhouse_type.strip()
    if unwrapped.startswith("Nullable(") and unwrapped.endswith(")"):
        unwrapped = unwrapped[len("Nullable(") : -1]
    return unwrapped in _INTEGER_CLICKHOUSE_TYPES


def epoch_to_datetime_expr(expr: ast.Expr) -> ast.Expr:
    """Convert an integer epoch expression to a DateTime, picking the unit per value by magnitude.

    Sub-second units are truncated to whole seconds with intDiv, which is enough for
    insight bucketing and date range filters.
    """

    def _at_least(bound: int) -> ast.Expr:
        return ast.CompareOperation(
            op=ast.CompareOperationOp.GtEq,
            left=clone_expr(expr),
            right=ast.Constant(value=bound),
        )

    def _seconds_scaled_by(divisor: int) -> ast.Expr:
        return ast.Call(
            name="toDateTime",
            args=[ast.Call(name="intDiv", args=[clone_expr(expr), ast.Constant(value=divisor)])],
        )

    return ast.Call(
        name="multiIf",
        args=[
            _at_least(_NANOSECONDS_LOWER_BOUND),
            _seconds_scaled_by(1_000_000_000),
            _at_least(_MICROSECONDS_LOWER_BOUND),
            _seconds_scaled_by(1_000_000),
            _at_least(_MILLISECONDS_LOWER_BOUND),
            _seconds_scaled_by(1_000),
            ast.Call(name="toDateTime", args=[clone_expr(expr)]),
        ],
    )
