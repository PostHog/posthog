"""A first, deliberately crude estimate of how many events a HogQL query will read.

    rows = events per day  ×  days in the timestamp range  ×  share of volume carried by the filtered event names

It covers queries whose only physical table is ``events``: a plain select, a select over a subquery or CTE,
a UNION of such selects, or a join whose every side is one of those. Each events scan in the tree is estimated
on its own and the scans are summed. A join to any other table, or a select with no table, gives no estimate.
Property filters are ignored, so the number is an upper bound on what a well-indexed query reads and close to
exact for one that is not. The estimate is advisory. It is compared against ``read_rows`` in ``query_log`` (see
``accuracy.py``) and a wrong number costs a misleading hint, never a failed query.

Anything the estimator does not understand widens the estimate rather than narrowing it: an unparseable date
bound means "the whole window", an unrecognised event predicate means "all events", and a predicate on an
outer select never narrows the subquery it reads from.
"""

from collections.abc import Mapping
from datetime import UTC, date, datetime, timedelta
from typing import Literal

from posthog.hogql import ast
from posthog.hogql.base import CTE
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
    """Estimate the events read by a resolved query, or None when it reads anything but the events table."""
    if context.team_id is None:
        return None
    now = now or datetime.now(UTC)
    scans = _events_scans(node, now, ctes={})
    if not scans:
        return None

    volume = provider.event_volume(context.team_id)
    if volume is None or not volume.days:
        return None

    rows = 0
    days = 0.0
    bounded = True
    reads_every_event = False
    narrowed_to: set[str] = set()
    for scan in scans:
        fraction = _event_fraction(volume, scan.events)
        rows += int(volume.per_day * scan.days * fraction)
        days = max(days, scan.days)
        bounded = bounded and scan.bounded
        if fraction < 1:
            narrowed_to.update(scan.events)
        else:
            reads_every_event = True
    return EventsScanEstimate(
        rows=rows,
        days=days,
        events=() if reads_every_event else tuple(sorted(narrowed_to)),
        time_range="bounded" if bounded else "open",
    )


@frozen
class _EventsScan:
    """One read of the events table, after the predicates that apply to it were folded in."""

    days: float
    bounded: bool
    events: frozenset[str]


@frozen
class _EventsTableRef:
    """An events table in a FROM clause. ``alias`` is None when it is joined unaliased."""

    alias: str | None


def _events_table(table_type: ast.Type | None) -> _EventsTableRef | None:
    alias: str | None = None
    while isinstance(table_type, ast.TableAliasType):
        alias = table_type.alias
        table_type = table_type.table_type
    if isinstance(table_type, ast.TableType) and isinstance(table_type.table, EventsTable):
        return _EventsTableRef(alias=alias)
    return None


def _events_scans(node: ast.Expr, now: datetime, ctes: Mapping[str, CTE]) -> list[_EventsScan] | None:
    """Every events scan a query's FROM clause performs, or None when any part of it reads another table.

    ``ctes`` are the subquery CTEs in scope. The resolver leaves a CTE reference in the FROM clause typed
    as ``CTETableType`` and keeps the body on the select that declared it, so the body is followed here.
    Subqueries in the select list or WHERE clause are not walked: they are rare in editor queries and
    skipping them undercounts, which the "up to" wording does not promise against.
    """
    if isinstance(node, ast.SelectSetQuery):
        scans: list[_EventsScan] = []
        in_scope = dict(ctes)
        for branch in node.select_queries():
            branch_scans = _events_scans(branch, now, in_scope)
            if branch_scans is None:
                return None
            scans.extend(branch_scans)
            # A WITH on the first branch is visible to the later ones.
            if isinstance(branch, ast.SelectQuery) and branch.ctes:
                in_scope.update(branch.ctes)
        return scans
    if not isinstance(node, ast.SelectQuery) or node.select_from is None:
        return None
    if node.ctes:
        ctes = {**ctes, **node.ctes}

    predicates = _WherePredicates(now=now)
    if node.where is not None:
        predicates.visit(node.where)

    scans = []
    join: ast.JoinExpr | None = node.select_from
    while join is not None:
        source = _join_source(join, ctes)
        if source is None:
            return None
        if isinstance(source, _EventsTableRef):
            scans.append(predicates.scan_for(source.alias))
        else:
            inner = _events_scans(source, now, ctes)
            if inner is None:
                return None
            scans.extend(inner)
        join = join.next_join
    return scans


def _join_source(
    join: ast.JoinExpr, ctes: Mapping[str, CTE]
) -> ast.SelectQuery | ast.SelectSetQuery | _EventsTableRef | None:
    """What one side of a FROM clause reads: a subquery to descend into, an events table, or None."""
    if isinstance(join.table, ast.SelectQuery | ast.SelectSetQuery):
        return join.table
    table_type = join.type
    if isinstance(table_type, ast.CTETableAliasType):
        table_type = table_type.cte_table_type
    if isinstance(table_type, ast.CTETableType):
        cte = ctes.get(table_type.name)
        if cte is None or cte.cte_type != "subquery" or cte.recursive:
            return None
        return cte.expr if isinstance(cte.expr, ast.SelectQuery | ast.SelectSetQuery) else None
    return _events_table(join.type)


def _event_fraction(volume: EventVolume, events: frozenset[str]) -> float:
    if not events:
        return 1.0
    fractions = [volume.event_fraction(event) for event in events]
    # An event name the rollup never saw contributes nothing. A brand-new event has no history either
    # way, so treating it as zero is the smaller error.
    return min(sum(f for f in fractions if f is not None), 1.0)


class _WherePredicates(TraversingVisitor):
    """Collects timestamp bounds and event-name equality filters from a WHERE clause, per events table alias.

    Only the top-level AND chain narrows the estimate. Anything under OR or NOT is skipped, because a
    disjunction can widen the scan back to the whole table and the estimator must never narrow on it.
    Keyed by alias so that in a self-join ``a.timestamp > x`` narrows the scan of ``a`` and not of ``b``.
    """

    def __init__(self, *, now: datetime) -> None:
        super().__init__()
        self._now = now
        self._lower_bounds: dict[str | None, datetime] = {}
        self._upper_bounds: dict[str | None, datetime] = {}
        self._events: dict[str | None, set[str]] = {}

    def scan_for(self, alias: str | None) -> _EventsScan:
        since = self._lower_bounds.get(alias)
        until = self._upper_bounds.get(alias)
        bounded = since is not None and until is not None
        since = since or (self._now - timedelta(days=DEFAULT_RANGE_DAYS))
        until = until or self._now
        return _EventsScan(
            days=max((until - since).total_seconds() / 86_400, 0.0),
            bounded=bounded,
            events=frozenset(self._events.get(alias, ())),
        )

    def visit_or(self, node: ast.Or) -> None:
        return

    def visit_not(self, node: ast.Not) -> None:
        return

    def visit_select_query(self, node: ast.SelectQuery) -> None:
        return

    def visit_compare_operation(self, node: ast.CompareOperation) -> None:
        for field_side, value_side, flipped in ((node.left, node.right, False), (node.right, node.left, True)):
            located = _events_column(field_side)
            if located is None:
                continue
            alias, column = located
            if column == "timestamp":
                self._record_timestamp(alias, node.op, value_side, flipped)
            elif column == "event" and node.op in (ast.CompareOperationOp.Eq, ast.CompareOperationOp.In):
                self._events.setdefault(alias, set()).update(_string_constants(value_side))

    def _record_timestamp(self, alias: str | None, op: ast.CompareOperationOp, value: ast.Expr, flipped: bool) -> None:
        moment = _constant_datetime(value, self._now)
        if moment is None:
            return
        greater = op in (ast.CompareOperationOp.Gt, ast.CompareOperationOp.GtEq)
        less = op in (ast.CompareOperationOp.Lt, ast.CompareOperationOp.LtEq)
        if flipped:
            greater, less = less, greater
        if greater:
            current = self._lower_bounds.get(alias)
            self._lower_bounds[alias] = max(current, moment) if current else moment
        elif less:
            current = self._upper_bounds.get(alias)
            self._upper_bounds[alias] = min(current, moment) if current else moment


def _events_column(expr: ast.Expr) -> tuple[str | None, str] | None:
    """(table alias, column name) when ``expr`` reads a plain column of an events table, else None."""
    while isinstance(expr, ast.Alias):
        expr = expr.expr
    if not isinstance(expr, ast.Field):
        return None
    field_type = expr.type
    if isinstance(field_type, ast.FieldAliasType):
        field_type = field_type.type
    if not isinstance(field_type, ast.FieldType):
        return None
    table = _events_table(field_type.table_type)
    if table is None:
        return None
    return table.alias, field_type.name


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
