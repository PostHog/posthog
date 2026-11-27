from collections.abc import Callable

from posthog.hogql import ast

from posthog.dataclasses import frozen


@frozen
class DateOffset:
    date: ast.Expr
    amount: ast.Expr
    subtract: bool
    date_type: ast.DateType | ast.DateTimeType

    @property
    def unit(self) -> str:
        return "day" if isinstance(self.date_type, ast.DateType) else "second"


def date_offset(
    left: ast.Expr,
    right: ast.Expr,
    *,
    subtract: bool,
    resolve_type: Callable[[ast.Expr], ast.ConstantType | None],
    is_numeric: Callable[[ast.Expr], bool],
) -> DateOffset | None:
    """Read `left + right` or `left - right` as a date and a number of days, or of seconds for a datetime.

    ClickHouse accepts the number on either side of a sum. Trino has no such operator, so the printer needs the
    date and the amount apart. A number minus a date is an error in ClickHouse, so it is not an offset.
    """
    left_type = resolve_type(left)
    if isinstance(left_type, (ast.DateType, ast.DateTimeType)) and is_numeric(right):
        return DateOffset(date=left, amount=right, subtract=subtract, date_type=left_type)
    right_type = resolve_type(right)
    if not subtract and isinstance(right_type, (ast.DateType, ast.DateTimeType)) and is_numeric(left):
        return DateOffset(date=right, amount=left, subtract=False, date_type=right_type)
    return None
