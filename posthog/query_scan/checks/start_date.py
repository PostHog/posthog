"""Find the timestamp bounds a query puts on the events table, and evaluate them to dates.

Two things come out of this. The classification says whether ClickHouse can skip data with
the lower bound, which is what the ``no_start_date`` finding reports. The evaluated range is
the denominator for the event ratio: the job counts the project's events between those dates
and compares that to the rows the query read.

Nothing on master evaluates an expression like ``now() - interval 30 day`` to a date, so the
evaluator here is new. It stays deliberately small: it covers the forms that appear in a
date filter and returns ``None`` for everything else, and a ``None`` only widens the range.
"""

from datetime import UTC, date, datetime, timedelta
from typing import Literal

from dateutil.relativedelta import relativedelta

from posthog.hogql import ast
from posthog.hogql.helpers.timestamp_visitor import is_time_or_interval_constant

from posthog.dataclasses import frozen
from posthog.query_scan.tree import EventsRead, collect_conditions, find_events_reads, is_column_of, strip_aliases

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

_CLASS_ORDER: tuple[StartDateClass, ...] = ("none", "column", "bound")

_BoundSide = Literal["lower", "upper"]


@frozen(eq=False)
class StartDateOutcome:
    classification: StartDateClass
    reason: StartDateReason | None = None
    clause: ast.Expr | None = None
    date_from: date | None = None
    date_to: date | None = None


@frozen(eq=False)
class _TimestampBound:
    """One bound a condition puts on a read's timestamp column. ``value`` is None when the bound
    is not a fixed point in time."""

    side: _BoundSide
    value: datetime | None
    clause: ast.Expr


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
    date_from = min(lowers).date() if len(lowers) == len(bounds) else None
    uppers = [item.upper for item in bounds if item.upper is not None]
    date_to = max(uppers).date() if len(uppers) == len(bounds) else moment.date()

    reason: StartDateReason | None = None
    if worst.classification == "column":
        reason = "column"
    elif worst.classification == "none" and has_filters_placeholder:
        # The query asked for a date range through {filters} and none was supplied, so the
        # placeholder expanded to nothing. The fix is on the insight, not in the SQL.
        reason = "filters"

    return StartDateOutcome(
        classification=worst.classification,
        reason=reason,
        clause=worst.clause,
        date_from=date_from,
        date_to=date_to,
    )


def _bounds_for_read(read: EventsRead, conditions: list[ast.Expr], now: datetime) -> _ReadBounds:
    lowers: list[datetime] = []
    uppers: list[datetime] = []
    unevaluable_lower: ast.Expr | None = None

    for term in conditions:
        for bound in _timestamp_bounds(term, read, now):
            if bound.value is None:
                if bound.side == "lower" and unevaluable_lower is None:
                    unevaluable_lower = bound.clause
                continue
            if bound.side == "lower":
                lowers.append(bound.value)
            else:
                uppers.append(bound.value)

    if lowers:
        # Several lower bounds narrow each other, so the effective one is the latest.
        return _ReadBounds(
            classification="bound", clause=None, lower=max(lowers), upper=min(uppers) if uppers else None
        )
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

    A ``None`` value means the term bounds the column but against something that is not a
    fixed point in time, so ClickHouse cannot skip data with it.
    """
    term = strip_aliases(term)

    if isinstance(term, ast.BetweenExpr):
        truncations = _timestamp_side_truncations(term.expr, read)
        if term.negated or truncations is None:
            return []
        return [
            _TimestampBound(side="lower", value=_evaluate_datetime(term.low, now), clause=term),
            _TimestampBound(
                side="upper",
                value=_end_of_interval(_evaluate_datetime(term.high, now), truncations),
                clause=term,
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
        value = _evaluate_datetime(value_side, now)
        # A truncation only moves a timestamp backwards, so it leaves a lower bound alone and
        # widens an upper one.
        return [
            _TimestampBound(
                side=side,
                value=_end_of_interval(value, truncations) if side == "upper" else value,
                clause=term,
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

    ``toStartOfMonth(timestamp) <= '2026-03-15'`` matches every timestamp in March, so the bound
    on the raw column is the start of April, not March 15. Two different truncations shift the
    value twice over, which this does not model, so those leave the bound unknown. That widens
    the range instead of narrowing it wrongly.
    """
    if value is None or not truncations:
        return value
    if len(truncations) > 1:
        return None
    name = next(iter(truncations))
    return _truncate(name, value) + _TRUNCATION_PERIODS[name]


def _evaluate_datetime(expr: ast.Expr, now: datetime) -> datetime | None:
    """A fixed point in time for ``expr``, or ``None`` when it is not one.

    ``is_time_or_interval_constant`` gates this: it already knows which shapes hold no
    column reference, so the evaluator below only has to produce the value.
    """
    try:
        if not is_time_or_interval_constant(expr):
            return None
    except Exception:
        # The visitor raises on node kinds it does not model. Those are not fixed points either.
        return None
    return _evaluate(expr, now)


def _evaluate(expr: ast.Expr, now: datetime) -> datetime | None:
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
        return moment - interval if op == ast.ArithmeticOperationOp.Sub else moment + interval
    return None


def _evaluate_interval(expr: ast.Expr) -> timedelta | relativedelta | None:
    expr = strip_aliases(expr)
    if not isinstance(expr, ast.Call) or not expr.args:
        return None
    amount = strip_aliases(expr.args[0])
    if not isinstance(amount, ast.Constant) or not isinstance(amount.value, int):
        return None
    if expr.name in _INTERVAL_UNITS_AS_DELTA:
        return timedelta(**{_INTERVAL_UNITS_AS_DELTA[expr.name]: amount.value})
    if expr.name in _INTERVAL_UNITS_AS_RELATIVE:
        return relativedelta(months=_INTERVAL_UNITS_AS_RELATIVE[expr.name] * amount.value)
    return None


def _truncate(function_name: str, value: datetime) -> datetime:
    if function_name == "toStartOfMinute":
        return value.replace(second=0, microsecond=0)
    if function_name == "toStartOfHour":
        return value.replace(minute=0, second=0, microsecond=0)
    if function_name in ("toDate", "toStartOfDay"):
        return value.replace(hour=0, minute=0, second=0, microsecond=0)
    if function_name == "toStartOfWeek":
        # ClickHouse's default mode starts the week on Sunday.
        start_of_day = value.replace(hour=0, minute=0, second=0, microsecond=0)
        return start_of_day - timedelta(days=(value.weekday() + 1) % 7)
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
