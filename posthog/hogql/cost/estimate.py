"""A first, deliberately crude estimate of how many events a HogQL query will read.

    rows = events per day  ×  days in the timestamp range  ×  share of volume carried by the filtered event names

It covers one shape: a select whose only table is ``events``, with no joins. Property filters are ignored, so
the number is an upper bound on what a well-indexed query reads and close to exact for one that is not. The
estimate is advisory. It is compared against ``read_rows`` in ``query_log`` (see ``accuracy.py``) and a wrong
number costs a misleading hint, never a failed query.

Anything the estimator does not understand widens the estimate rather than narrowing it: an unparseable date
bound means "the whole window", an unrecognised event predicate means "all events".
"""

from datetime import UTC, date, datetime, timedelta
from typing import Literal

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.cost.statistics import EventVolume, StatisticsProvider
from posthog.hogql.database.schema.events import EventsTable
from posthog.hogql.visitor import TraversingVisitor

from posthog.dataclasses import frozen

# A team's retention rarely exceeds this, and a query with no timestamp bound reads whatever exists.
DEFAULT_RANGE_DAYS = 365

_INTERVAL_DAYS: dict[str, float] = {
    "toIntervalSecond": 1 / 86_400,
    "toIntervalMinute": 1 / 1_440,
    "toIntervalHour": 1 / 24,
    "toIntervalDay": 1,
    "toIntervalWeek": 7,
    "toIntervalMonth": 30,
    "toIntervalQuarter": 91,
    "toIntervalYear": 365,
}


@frozen
class EventsScanEstimate:
    rows: int
    days: float
    # The event names the estimate was narrowed to. Empty means the query reads every event.
    events: tuple[str, ...]
    # ``bounded`` when both ends of the timestamp range were understood, ``open`` when the estimate fell back
    # to DEFAULT_RANGE_DAYS on at least one side.
    time_range: Literal["bounded", "open"]

    def __post_init__(self) -> None:
        if self.rows < 0 or self.days < 0:
            raise ValueError("EventsScanEstimate values cannot be negative")


def estimate_events_scan(
    node: ast.SelectQuery | ast.SelectSetQuery,
    context: HogQLContext,
    provider: StatisticsProvider,
    *,
    now: datetime | None = None,
) -> EventsScanEstimate | None:
    """Estimate the events read by a resolved single-table select, or None when the shape is not covered."""
    if not isinstance(node, ast.SelectQuery) or context.team_id is None:
        return None
    if not _selects_only_events(node):
        return None
    volume = provider.event_volume(context.team_id)
    if volume is None or not volume.days:
        return None

    now = now or datetime.now(UTC)
    predicates = _WherePredicates(now=now)
    if node.where is not None:
        predicates.visit(node.where)

    since = predicates.lower_bound
    until = predicates.upper_bound
    bounded = since is not None and until is not None
    since = since or (now - timedelta(days=DEFAULT_RANGE_DAYS))
    until = until or now
    days = max((until - since).total_seconds() / 86_400, 0.0)

    fraction = _event_fraction(volume, predicates.events)
    rows = int(volume.per_day * days * fraction)
    return EventsScanEstimate(
        rows=rows,
        days=days,
        events=tuple(sorted(predicates.events)) if fraction < 1 else (),
        time_range="bounded" if bounded else "open",
    )


def _selects_only_events(node: ast.SelectQuery) -> bool:
    join = node.select_from
    if join is None or join.next_join is not None:
        return False
    table_type = join.type
    while isinstance(table_type, ast.TableAliasType):
        table_type = table_type.table_type
    return isinstance(table_type, ast.TableType) and isinstance(table_type.table, EventsTable)


def _event_fraction(volume: EventVolume, events: set[str]) -> float:
    if not events:
        return 1.0
    fractions = [volume.event_fraction(event) for event in events]
    # An event name the rollup never saw contributes nothing. A brand-new event has no history either
    # way, so treating it as zero is the smaller error.
    return min(sum(f for f in fractions if f is not None), 1.0)


class _WherePredicates(TraversingVisitor):
    """Collects timestamp bounds and event-name equality filters from a WHERE clause.

    Only the top-level AND chain narrows the estimate. Anything under OR or NOT is skipped, because a
    disjunction can widen the scan back to the whole table and the estimator must never narrow on it.
    """

    def __init__(self, *, now: datetime) -> None:
        super().__init__()
        self._now = now
        self.lower_bound: datetime | None = None
        self.upper_bound: datetime | None = None
        self.events: set[str] = set()

    def visit_or(self, node: ast.Or) -> None:
        return

    def visit_not(self, node: ast.Not) -> None:
        return

    def visit_select_query(self, node: ast.SelectQuery) -> None:
        return

    def visit_compare_operation(self, node: ast.CompareOperation) -> None:
        for field_side, value_side, flipped in ((node.left, node.right, False), (node.right, node.left, True)):
            column = _events_column(field_side)
            if column == "timestamp":
                self._record_timestamp(node.op, value_side, flipped)
            elif column == "event" and node.op in (ast.CompareOperationOp.Eq, ast.CompareOperationOp.In):
                self.events.update(_string_constants(value_side))

    def _record_timestamp(self, op: ast.CompareOperationOp, value: ast.Expr, flipped: bool) -> None:
        moment = _constant_datetime(value, self._now)
        if moment is None:
            return
        greater = op in (ast.CompareOperationOp.Gt, ast.CompareOperationOp.GtEq)
        less = op in (ast.CompareOperationOp.Lt, ast.CompareOperationOp.LtEq)
        if flipped:
            greater, less = less, greater
        if greater:
            self.lower_bound = max(self.lower_bound, moment) if self.lower_bound else moment
        elif less:
            self.upper_bound = min(self.upper_bound, moment) if self.upper_bound else moment


def _events_column(expr: ast.Expr) -> str | None:
    """Name of the events-table column ``expr`` reads, or None when it is not a plain column of events."""
    while isinstance(expr, ast.Alias):
        expr = expr.expr
    if not isinstance(expr, ast.Field):
        return None
    field_type = expr.type
    if isinstance(field_type, ast.FieldAliasType):
        field_type = field_type.type
    if not isinstance(field_type, ast.FieldType):
        return None
    table_type = field_type.table_type
    while isinstance(table_type, ast.TableAliasType):
        table_type = table_type.table_type
    if not (isinstance(table_type, ast.TableType) and isinstance(table_type.table, EventsTable)):
        return None
    return field_type.name


def _string_constants(expr: ast.Expr) -> list[str]:
    if isinstance(expr, ast.Constant):
        return [expr.value] if isinstance(expr.value, str) else []
    if isinstance(expr, ast.Tuple | ast.Array):
        return [value for item in expr.exprs for value in _string_constants(item)]
    return []


def _constant_datetime(expr: ast.Expr, now: datetime) -> datetime | None:
    """Resolve a literal or ``now() [- interval]`` bound to an aware datetime; None for anything else."""
    if isinstance(expr, ast.Constant):
        return _parse_literal(expr.value)
    if isinstance(expr, ast.Call) and expr.name == "now" and not expr.args:
        return now
    if isinstance(expr, ast.ArithmeticOperation) and expr.op in (
        ast.ArithmeticOperationOp.Sub,
        ast.ArithmeticOperationOp.Add,
    ):
        base = _constant_datetime(expr.left, now)
        offset = _interval_days(expr.right)
        if base is None or offset is None:
            return None
        delta = timedelta(days=offset)
        return base - delta if expr.op == ast.ArithmeticOperationOp.Sub else base + delta
    return None


def _interval_days(expr: ast.Expr) -> float | None:
    if not (isinstance(expr, ast.Call) and len(expr.args) == 1):
        return None
    per_unit = _INTERVAL_DAYS.get(expr.name)
    amount = expr.args[0]
    if per_unit is None or not isinstance(amount, ast.Constant) or not isinstance(amount.value, int | float):
        return None
    return float(amount.value) * per_unit


def _parse_literal(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=UTC)
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
