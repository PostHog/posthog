from collections.abc import Callable
from typing import TypeGuard

from posthog.hogql import ast

from posthog.dataclasses import frozen

WHOLE_DAY_INTERVAL_FUNCTIONS = frozenset(
    {"tointervalday", "tointervalweek", "tointervalmonth", "tointervalquarter", "tointervalyear"}
)


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


def date_moved_by_whole_days(
    node: ast.Expr, *, resolve_type: Callable[[ast.Expr], ast.ConstantType | None]
) -> ast.DateType | None:
    operands = _sum_or_difference(node)
    if operands is None:
        return None
    date, interval = operands.left, operands.right
    if not operands.subtract and _is_whole_day_interval(date):
        date, interval = interval, date
    date_type = resolve_type(date)
    if not isinstance(date_type, ast.DateType) or not _is_whole_day_interval(interval):
        return None
    amount_types = [resolve_type(amount) for amount in interval.args]
    return ast.DateType(
        nullable=date_type.nullable or any(amount_type and amount_type.nullable for amount_type in amount_types)
    )


@frozen
class _SumOrDifference:
    left: ast.Expr
    right: ast.Expr
    subtract: bool


def _sum_or_difference(node: ast.Expr) -> _SumOrDifference | None:
    if isinstance(node, ast.ArithmeticOperation) and node.op in (
        ast.ArithmeticOperationOp.Add,
        ast.ArithmeticOperationOp.Sub,
    ):
        return _SumOrDifference(left=node.left, right=node.right, subtract=node.op == ast.ArithmeticOperationOp.Sub)
    if isinstance(node, ast.Call) and node.name.lower() in {"plus", "minus"} and len(node.args) == 2:
        return _SumOrDifference(left=node.args[0], right=node.args[1], subtract=node.name.lower() == "minus")
    return None


def _is_whole_day_interval(node: ast.Expr) -> TypeGuard[ast.Call]:
    return isinstance(node, ast.Call) and node.name.lower() in WHOLE_DAY_INTERVAL_FUNCTIONS
