"""Find the timestamp bounds a query puts on the events table, and evaluate them to dates.

The classification says whether ClickHouse can skip data with the lower bound, which is what the
``no_start_date`` finding reports. The evaluated range is the denominator for the event ratio: the
job counts the project's events between those dates and compares that to the rows the query read.

HogQL has no evaluator that turns a form like ``now() - interval 30 day`` into a date, so this
module carries a small one. It returns ``None`` for anything it does not cover, which only widens
the range. A form it cannot evaluate is still a start date, so it stays apart from a bound that
reads another column, which is the one ClickHouse cannot skip data with.
"""

from datetime import UTC, date, datetime, timedelta
from typing import Literal

from dateutil.relativedelta import relativedelta

from posthog.hogql import ast

from posthog.dataclasses import frozen
from posthog.query_scan.tree import (
    EventsRead,
    collect_conditions,
    depends_on_data,
    find_events_reads,
    is_column_of,
    strip_aliases,
)

StartDateClass = Literal["bound", "column", "none"]
StartDateReason = Literal["column", "filters"]

_TIMESTAMP_COLUMN = "timestamp"

# Date functions that collapse their argument to the start of an interval, with the interval
# each one covers. An upper bound through one of them admits the whole interval, not just the
# instant it names.
_TRUNCATION_PERIODS: dict[str, timedelta | relativedelta] = {
    "toDate": timedelta(days=1),
    "toStartOfDay": timedelta(days=1),
    "toStartOfHour": timedelta(hours=1),
    "toStartOfMinute": timedelta(minutes=1),
    "toStartOfMonth": relativedelta(months=1),
    "toStartOfQuarter": relativedelta(months=3),
    "toStartOfWeek": timedelta(days=7),
    "toStartOfYear": relativedelta(years=1),
}

# Date functions that keep the order of their argument, so a bound through one of them is
# still a bound on the raw column. The truncating ones above plus the rest of the list
# IsSimpleTimestampFieldExpressionVisitor.visit_call accepts.
_MONOTONE_DATE_FUNCTIONS = frozenset(_TRUNCATION_PERIODS) | frozenset(
    {
        "assumeNotNull",
        "parseDateTime64BestEffortOrNull",
        "toDateTime",
        "toDateTime64",
        "toTimeZone",
    }
)

_INTERVAL_UNITS_AS_DELTA = {
    "toIntervalSecond": "seconds",
    "toIntervalMinute": "minutes",
    "toIntervalHour": "hours",
    "toIntervalDay": "days",
    "toIntervalWeek": "weeks",
}
_INTERVAL_UNITS_AS_RELATIVE = {
    "toIntervalMonth": 1,
    "toIntervalQuarter": 3,
    "toIntervalYear": 12,
}

# ``subtractDays(now(), 7)`` is ClickHouse's shorthand for ``now() - interval 7 day``.
_SHIFT_FUNCTIONS: dict[str, tuple[int, str]] = {
    f"{prefix}{unit}s": (sign, f"toInterval{unit}")
    for prefix, sign in (("add", 1), ("subtract", -1))
    for unit in ("Second", "Minute", "Hour", "Day", "Week", "Month", "Quarter", "Year")
}

_CLASS_ORDER: tuple[StartDateClass, ...] = ("none", "column", "bound")

_BoundSide = Literal["lower", "upper"]


@frozen(eq=False)
class StartDateOutcome:
    classification: StartDateClass
    reason: StartDateReason | None = None
    clause: ast.Expr | None = None
    date_from: date | None = None
    date_to: date | None = None
    # The evaluated bounds the dates were rounded out from, so the count query can use the exact
    # instants where they are known instead of whole days.
    lower: datetime | None = None
    upper: datetime | None = None


@frozen(eq=False)
class _TimestampBound:
    """One bound a condition puts on a read's timestamp column.

    ``value`` is None when the evaluator could not produce it. ``data_dependent`` tells the two
    causes apart: a bound against a column has no fixed value at all, one against an unsupported
    fixed expression does.
    """

    side: _BoundSide
    value: datetime | None
    clause: ast.Expr
    data_dependent: bool


@frozen(eq=False)
class _ReadBounds:
    classification: StartDateClass
    clause: ast.Expr | None
    lower: datetime | None
    upper: datetime | None


def check_start_date(tree: ast.AST, *, has_filters_placeholder: bool = False) -> StartDateOutcome:
    # Naive UTC throughout, so a bound parsed with an offset and one built from now() compare.
    moment = datetime.now(UTC).replace(tzinfo=None)
    reads = find_events_reads(tree)
    if not reads:
        # A query that never touches the events table has no start date to report on.
        return StartDateOutcome(classification="bound", date_from=None, date_to=moment.date())

    bounds = [_bounds_for_read(read, collect_conditions(tree, read), moment) for read in reads]
    worst = min(bounds, key=lambda item: _CLASS_ORDER.index(item.classification))

    # One read without a bound makes the whole count unbounded on that side, because the query
    # still read everything that read touched.
    lowers = [item.lower for item in bounds if item.lower is not None]
    lower = min(lowers) if len(lowers) == len(bounds) else None
    uppers = [item.upper for item in bounds if item.upper is not None]
    upper = max(uppers) if len(uppers) == len(bounds) else None
    date_from = lower.date() if lower is not None else None
    date_to = upper.date() if upper is not None else moment.date()

    reason: StartDateReason | None = None
    if worst.classification == "column":
        reason = "column"
    elif worst.classification == "none" and has_filters_placeholder and _no_read_is_bounded(bounds):
        # The query asked for a date range through {filters} and none was supplied, so the fix is
        # on the insight, not in the SQL. A read that did get a bound says a range was supplied and
        # the placeholder only reaches part of the query, so that read is told to bound itself.
        reason = "filters"

    return StartDateOutcome(
        classification=worst.classification,
        reason=reason,
        clause=worst.clause,
        date_from=date_from,
        date_to=date_to,
        lower=lower,
        upper=upper,
    )


def _no_read_is_bounded(bounds: list[_ReadBounds]) -> bool:
    return all(item.classification == "none" for item in bounds)


def _bounds_for_read(read: EventsRead, conditions: list[ast.Expr], now: datetime) -> _ReadBounds:
    lowers: list[datetime] = []
    uppers: list[datetime] = []
    unevaluable_lower: ast.Expr | None = None
    has_fixed_lower = False

    for term in conditions:
        for bound in _timestamp_bounds(term, read, now):
            if bound.value is not None:
                if bound.side == "lower":
                    lowers.append(bound.value)
                else:
                    uppers.append(bound.value)
            elif bound.side == "lower" and bound.data_dependent:
                if unevaluable_lower is None:
                    unevaluable_lower = bound.clause
            elif bound.side == "lower":
                has_fixed_lower = True

    if lowers:
        # Several lower bounds narrow each other, so the effective one is the latest.
        return _ReadBounds(
            classification="bound", clause=None, lower=max(lowers), upper=min(uppers) if uppers else None
        )
    if has_fixed_lower:
        # The query bounds the read at a fixed point in time, so ClickHouse can skip data with it.
        # Only the value is out of reach, which leaves the range open at the bottom.
        return _ReadBounds(classification="bound", clause=None, lower=None, upper=min(uppers) if uppers else None)
    if unevaluable_lower is not None:
        return _ReadBounds(
            classification="column",
            clause=unevaluable_lower,
            lower=None,
            upper=min(uppers) if uppers else None,
        )
    return _ReadBounds(classification="none", clause=None, lower=None, upper=min(uppers) if uppers else None)


def _timestamp_bounds(term: ast.Expr, read: EventsRead, now: datetime) -> list[_TimestampBound]:
    """Bounds this top-level term puts on the read's timestamp column.

    A ``None`` value means the evaluator could not produce one, either because the term bounds
    the column against the data or because the fixed expression it uses is not supported.
    """
    term = strip_aliases(term)

    if isinstance(term, ast.BetweenExpr):
        truncations = _timestamp_side_truncations(term.expr, read)
        if term.negated or truncations is None:
            return []
        return [
            _TimestampBound(
                side="lower",
                value=_evaluate(term.low, now),
                clause=term,
                data_dependent=depends_on_data(term.low),
            ),
            _TimestampBound(
                side="upper",
                value=_end_of_interval(_evaluate(term.high, now), truncations),
                clause=term,
                data_dependent=depends_on_data(term.high),
            ),
        ]

    if not isinstance(term, ast.CompareOperation):
        return []

    for field_side, value_side, flipped in ((term.left, term.right, False), (term.right, term.left, True)):
        truncations = _timestamp_side_truncations(field_side, read)
        if truncations is None:
            continue
        sides = _bound_sides(term.op, flipped=flipped)
        if not sides:
            return []
        value = _evaluate(value_side, now)
        data_dependent = depends_on_data(value_side)
        # A truncation only moves a timestamp backwards, so it leaves a lower bound alone and
        # widens an upper one.
        return [
            _TimestampBound(
                side=side,
                value=_end_of_interval(value, truncations) if side == "upper" else value,
                clause=term,
                data_dependent=data_dependent,
            )
            for side in sides
        ]
    return []


def _bound_sides(op: ast.CompareOperationOp, *, flipped: bool) -> tuple[_BoundSide, ...]:
    if op == ast.CompareOperationOp.Eq:
        return ("lower", "upper")
    lower_ops = (ast.CompareOperationOp.Gt, ast.CompareOperationOp.GtEq)
    upper_ops = (ast.CompareOperationOp.Lt, ast.CompareOperationOp.LtEq)
    if flipped:
        lower_ops, upper_ops = upper_ops, lower_ops
    if op in lower_ops:
        return ("lower",)
    if op in upper_ops:
        return ("upper",)
    return ()


def _timestamp_side_truncations(expr: ast.Expr, read: EventsRead) -> frozenset[str] | None:
    """The truncating functions wrapping the read's timestamp column, empty for the bare column,
    or ``None`` when ``expr`` is not that column at all."""
    unwrapped = _unwrap_monotone(expr)
    if unwrapped is None:
        return None
    inner, truncations = unwrapped
    if not is_column_of(inner, read, _TIMESTAMP_COLUMN):
        return None
    return truncations


def _unwrap_monotone(expr: ast.Expr) -> tuple[ast.Expr, frozenset[str]] | None:
    truncations: set[str] = set()
    for _ in range(8):
        expr = strip_aliases(expr)
        if isinstance(expr, ast.TypeCast | ast.TryCast):
            expr = expr.expr
            continue
        if isinstance(expr, ast.Call) and expr.name in _MONOTONE_DATE_FUNCTIONS and expr.args:
            if expr.name in _TRUNCATION_PERIODS:
                truncations.add(expr.name)
            expr = expr.args[0]
            continue
        return expr, frozenset(truncations)
    return None


def _end_of_interval(value: datetime | None, truncations: frozenset[str]) -> datetime | None:
    """The end of the interval a truncated upper bound admits.

    ``toStartOfMonth(timestamp) <= '2026-03-15'`` matches every timestamp in March, so the bound on
    the raw column is the start of April, not March 15. Two different truncations shift the value
    twice over, which this does not model, so those leave the bound unknown and widen the range
    instead of narrowing it wrongly.
    """
    if value is None or not truncations:
        return value
    if len(truncations) > 1:
        return None
    name = next(iter(truncations))
    if name == "toStartOfWeek":
        return _end_of_week(value)
    start = _truncate(name, value)
    return _shift(start, _TRUNCATION_PERIODS[name]) if start is not None else None


def _end_of_week(value: datetime) -> datetime | None:
    """The end of the week ``toStartOfWeek`` puts ``value`` in, under either week mode.

    Which mode applies is the team's setting, and the evaluator cannot see it. The two modes start
    the week on different days, so take the later of the two ends and let the range be too wide
    rather than too narrow.
    """
    start_of_day = value.replace(hour=0, minute=0, second=0, microsecond=0)
    days_into_week = min(value.weekday(), (value.weekday() + 1) % 7)
    return _shift(start_of_day, timedelta(days=7 - days_into_week))


def _shift(moment: datetime, amount: timedelta | relativedelta, *, sign: int = 1) -> datetime | None:
    """``None`` for a shift that leaves the range ``datetime`` covers, which is an unknown bound."""
    try:
        return moment + amount * sign
    except (OverflowError, ValueError):
        return None


def _evaluate(expr: ast.Expr, now: datetime) -> datetime | None:
    """The fixed point in time ``expr`` stands for, or ``None`` for a shape not covered here.

    Every form below bottoms out in a constant or in ``now()``, so a value can only come back
    for an expression that holds no column.
    """
    expr = strip_aliases(expr)

    if isinstance(expr, ast.TypeCast | ast.TryCast):
        return _evaluate(expr.expr, now)

    if isinstance(expr, ast.Constant):
        return _parse_constant(expr.value)

    if isinstance(expr, ast.ArithmeticOperation):
        return _evaluate_arithmetic(expr.op, expr.left, expr.right, now)

    if not isinstance(expr, ast.Call):
        return None

    if expr.name in ("now", "now64"):
        return now
    if expr.name == "today":
        return now.replace(hour=0, minute=0, second=0, microsecond=0)
    if expr.name == "yesterday":
        return now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1)
    if expr.name == "minus" and len(expr.args) == 2:
        return _evaluate_arithmetic(ast.ArithmeticOperationOp.Sub, expr.args[0], expr.args[1], now)
    if expr.name == "add" and len(expr.args) == 2:
        return _evaluate_arithmetic(ast.ArithmeticOperationOp.Add, expr.args[0], expr.args[1], now)
    if expr.name in _MONOTONE_DATE_FUNCTIONS and expr.args:
        value = _evaluate(expr.args[0], now)
        return _truncate(expr.name, value) if value is not None else None
    if expr.name in _SHIFT_FUNCTIONS and len(expr.args) == 2:
        sign, interval_function = _SHIFT_FUNCTIONS[expr.name]
        moment = _evaluate(expr.args[0], now)
        interval = _interval(interval_function, expr.args[1])
        if moment is None or interval is None:
            return None
        return _shift(moment, interval, sign=sign)
    return None


def _evaluate_arithmetic(
    op: ast.ArithmeticOperationOp, left: ast.Expr, right: ast.Expr, now: datetime
) -> datetime | None:
    candidates: tuple[tuple[ast.Expr, ast.Expr], ...]
    if op == ast.ArithmeticOperationOp.Sub:
        # Only `moment - interval` is a point in time.
        candidates = ((left, right),)
    elif op == ast.ArithmeticOperationOp.Add:
        candidates = ((left, right), (right, left))
    else:
        return None

    for moment_side, interval_side in candidates:
        moment = _evaluate(moment_side, now)
        interval = _evaluate_interval(interval_side)
        if moment is None or interval is None:
            continue
        return _shift(moment, interval, sign=-1 if op == ast.ArithmeticOperationOp.Sub else 1)
    return None


def _evaluate_interval(expr: ast.Expr) -> timedelta | relativedelta | None:
    expr = strip_aliases(expr)
    if not isinstance(expr, ast.Call) or not expr.args:
        return None
    return _interval(expr.name, expr.args[0])


def _interval(interval_function: str, amount: ast.Expr) -> timedelta | relativedelta | None:
    amount = strip_aliases(amount)
    if not isinstance(amount, ast.Constant) or not isinstance(amount.value, int):
        return None
    try:
        if interval_function in _INTERVAL_UNITS_AS_DELTA:
            return timedelta(**{_INTERVAL_UNITS_AS_DELTA[interval_function]: amount.value})
        if interval_function in _INTERVAL_UNITS_AS_RELATIVE:
            return relativedelta(months=_INTERVAL_UNITS_AS_RELATIVE[interval_function] * amount.value)
    except (OverflowError, ValueError):
        # An amount too large to hold leaves the bound unknown rather than failing the scan.
        return None
    return None


def _truncate(function_name: str, value: datetime) -> datetime | None:
    if function_name == "toStartOfMinute":
        return value.replace(second=0, microsecond=0)
    if function_name == "toStartOfHour":
        return value.replace(minute=0, second=0, microsecond=0)
    if function_name in ("toDate", "toStartOfDay"):
        return value.replace(hour=0, minute=0, second=0, microsecond=0)
    if function_name == "toStartOfWeek":
        # ClickHouse's default mode starts the week on Sunday, which is the earlier of the two
        # starts the team's week mode can produce.
        start_of_day = value.replace(hour=0, minute=0, second=0, microsecond=0)
        return _shift(start_of_day, timedelta(days=(value.weekday() + 1) % 7), sign=-1)
    if function_name == "toStartOfMonth":
        return value.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if function_name == "toStartOfQuarter":
        first_month = value.month - (value.month - 1) % 3
        return value.replace(month=first_month, day=1, hour=0, minute=0, second=0, microsecond=0)
    if function_name == "toStartOfYear":
        return value.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
    return value


def _parse_constant(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return _as_naive_utc(value)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day)
    if not isinstance(value, str):
        return None
    try:
        return _as_naive_utc(datetime.fromisoformat(value))
    except ValueError:
        return None


def _as_naive_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)
