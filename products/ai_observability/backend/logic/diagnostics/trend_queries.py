from posthog.hogql import ast
from posthog.hogql.parser import parse_expr

from .trends import DECREASE_MIN_PERCENT, INCREASE_MIN_PERCENT, TREND_MIN_OCCURRENCES, Trend


def trend_expression(current: ast.Expr, previous: ast.Expr | None) -> ast.Expr:
    """The trend's string value from this period's occurrences against the previous window's, `previous` being None
    when the range has no previous window. A null `previous` is a group that did not occur in the previous window."""
    if previous is None:
        return ast.Constant(value=Trend.STEADY.value)
    return parse_expr(
        """
        multiIf(
            {current} >= {min_occurrences} AND {current} * 100 >= {previous} * {increase_ratio}, {increasing},
            {previous} >= {min_occurrences} AND {current} * 100 <= {previous} * {decrease_ratio}, {decreasing},
            {steady}
        )
        """,
        placeholders={
            "current": current,
            "previous": ast.Call(name="ifNull", args=[previous, ast.Constant(value=0)]),
            "min_occurrences": ast.Constant(value=TREND_MIN_OCCURRENCES),
            "increase_ratio": ast.Constant(value=100 + INCREASE_MIN_PERCENT),
            "decrease_ratio": ast.Constant(value=100 - DECREASE_MIN_PERCENT),
            "increasing": ast.Constant(value=Trend.INCREASING.value),
            "decreasing": ast.Constant(value=Trend.DECREASING.value),
            "steady": ast.Constant(value=Trend.STEADY.value),
        },
    )
