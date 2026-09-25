"""A first, deliberately crude estimate of how much a HogQL query will read, one entry per table it scans.

The FROM tree is walked whole: a plain select, a select over a subquery or CTE, a UNION, or a join, down to the
physical tables. Each scan gets an entry that says what is known about it, and the entries are summed into one
headline. What is known depends on the source. For ``events``:

    rows = events per day  ×  days in the timestamp range  ×  share of volume carried by the filtered event names
           ×  share of granules the most selective indexed property filter leaves

Sessions are a daily rate scaled to the range on the session's start time, the same shape without the event share.
A warehouse table carries the rows and bytes of its last sync, and persons and groups a count of the team's rows.
A table on a customer's database carries the row estimate its catalog reported at the last schema refresh. Any
other table is listed with nothing known about it, so the reader sees which part of the query the number does not
cover. The estimate is advisory. It is compared against
``read_rows`` in ``query_log`` (see ``accuracy.py``) and a wrong number costs a misleading hint, never a failed
query.

The number is rows read, not rows returned, so a property filter counts only when a skip index can rule out
granules for it. A filter with no usable index reads every row, which the estimate already assumes. An
equality or IN filter on an event property with a bloom filter index narrows the read to the granules expected
to hold a match (see ``_granule_fraction``). Any other indexed filter may narrow the read by an amount the
estimator cannot model, so the estimate reports itself as an upper bound.

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
from posthog.hogql.database.direct_sql_table import DirectSQLTable
from posthog.hogql.database.models import FunctionCallTable, Table
from posthog.hogql.database.s3_table import DataWarehouseTable, S3Table
from posthog.hogql.database.schema.events import EventsTable
from posthog.hogql.database.schema.groups import GroupsTable, RawGroupsTable
from posthog.hogql.database.schema.persons import PersonsTable, RawPersonsTable
from posthog.hogql.database.schema.sessions_v1 import RawSessionsTableV1, SessionsTableV1
from posthog.hogql.database.schema.sessions_v2 import RawSessionsTableV2, SessionsTableV2
from posthog.hogql.database.schema.sessions_v3 import RawSessionsTableV3, SessionsTableV3
from posthog.hogql.index_eligibility import IndexKind, eligibility_from_plan
from posthog.hogql.property_planner import PropertyScope, plan_property_comparison
from posthog.hogql.visitor import TraversingVisitor

from posthog.dataclasses import frozen
from posthog.models.group.sql import GROUPS_TABLE
from posthog.models.person.sql import PERSONS_TABLE

# A team's retention rarely exceeds this, and a query with no timestamp bound reads whatever exists.
DEFAULT_RANGE_DAYS = 365

# ClickHouse reads whole granules, and a skip index rules a granule out only when no row in it can match.
GRANULE_ROWS = 8192

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


TableSource = Literal["events", "clickhouse", "warehouse", "direct", "static"]
# ``measured``: a model of what the query reads, compared against ``read_rows`` in the query log.
# ``size_only``: the table's size is known, the query's read of it is not.
# ``unknown``: nothing is known about the table.
ScanPrecision = Literal["measured", "size_only", "unknown"]


@frozen
class FilterEstimate:
    """How much of an events scan one indexed property filter is expected to leave."""

    property_name: str
    # How many constants the property is compared against: one for ``=``, the set size for IN.
    values: int
    # Share of granules still read after this filter alone, or None when the property has no distinct count.
    granules_read: float | None


@frozen
class TableScanEstimate:
    """What is known about one scan in the FROM tree."""

    name: str
    source: TableSource
    precision: ScanPrecision
    rows: int | None = None
    bytes: int | None = None
    # Events only: the timestamp range the rows were scaled to.
    days: float | None = None
    # Events only: the event names the estimate was narrowed to. Empty means the scan reads every event.
    events: tuple[str, ...] | None = None
    # Events only: ``bounded`` when both ends of the timestamp range were understood, ``open`` when the
    # estimate fell back to DEFAULT_RANGE_DAYS on at least one side.
    time_range: Literal["bounded", "open"] | None = None
    # Events only: the indexed property filters that were considered, whether or not they narrowed the read.
    filters: tuple[FilterEstimate, ...] = ()

    def __post_init__(self) -> None:
        if (self.rows is not None and self.rows < 0) or (self.bytes is not None and self.bytes < 0):
            raise ValueError("TableScanEstimate sizes cannot be negative")
        if self.days is not None and self.days < 0:
            raise ValueError("TableScanEstimate days cannot be negative")


@frozen
class ScanEstimate:
    # Sum of the rows of every table entry that has one.
    rows: int
    # True when an indexed filter may narrow the read by an amount the estimator could not model, or when a
    # table is known only by its size, so the query reads at most ``rows`` of the tables that have a number.
    # False when every table is measured and ``rows`` is a point estimate.
    upper_bound: bool
    tables: tuple[TableScanEstimate, ...]

    @property
    def events(self) -> tuple[TableScanEstimate, ...]:
        return tuple(table for table in self.tables if table.source == "events")


def estimate_scan(
    node: ast.SelectQuery | ast.SelectSetQuery,
    context: HogQLContext,
    provider: StatisticsProvider,
    *,
    now: datetime | None = None,
) -> ScanEstimate | None:
    """Estimate what a resolved query reads, or None when it reads no table or its FROM tree cannot be walked."""
    if context.team_id is None:
        return None
    now = now or datetime.now(UTC)
    if context.property_metadata is None:
        # Deferred for the same reason as in index_eligibility: the Django-side property-definition loader
        # must stay off this module's import path. Without the metadata every property plans as a JSON read
        # and no filter is ever seen as indexed.
        from posthog.hogql.transforms.property_types import build_property_swapper  # noqa: PLC0415

        build_property_swapper(node, context)
    scans = _table_scans(node, now, context, ctes={})
    if not scans:
        return None

    volume: EventVolume | None = None
    if any(isinstance(scan, _EventsScan) for scan in scans):
        volume = provider.event_volume(context.team_id)

    tables: list[TableScanEstimate] = []
    upper_bound = False
    for scan in scans:
        if isinstance(scan, _EventsScan):
            if volume is None or not volume.days:
                tables.append(TableScanEstimate(name=scan.name, source="events", precision="unknown"))
                continue
            estimate, unmodelled = _estimate_events_scan(scan, volume, context.team_id, provider)
            tables.append(estimate)
            upper_bound = upper_bound or unmodelled
        elif isinstance(scan, _SessionsScan):
            tables.append(_estimate_sessions_scan(scan, context.team_id, provider))
        else:
            estimate = _other_table_estimate(scan, context.team_id, provider)
            tables.append(estimate)
            upper_bound = upper_bound or estimate.precision == "size_only"

    return ScanEstimate(
        rows=sum(table.rows for table in tables if table.rows is not None),
        upper_bound=upper_bound,
        tables=tuple(tables),
    )


def _estimate_events_scan(
    scan: "_EventsScan", volume: EventVolume, team_id: int, provider: StatisticsProvider
) -> tuple[TableScanEstimate, bool]:
    """Size one events scan. The bool says whether an indexed filter went unmodelled."""
    fraction = _event_fraction(volume, scan.events)
    granules_read = 1.0
    unmodelled = scan.unmodelled_filter
    filters: list[FilterEstimate] = []
    for property_filter in scan.property_filters:
        distinct_values = provider.property_ndv(team_id, property_filter.property_name)
        if distinct_values is None:
            unmodelled = True
            filters.append(
                FilterEstimate(
                    property_name=property_filter.property_name, values=property_filter.values, granules_read=None
                )
            )
            continue
        # The filters are not multiplied together. Properties on one event are often correlated, and the
        # product of two fractions that assume independence narrows far more than the data does.
        share = _granule_fraction(property_filter.values, distinct_values)
        granules_read = min(granules_read, share)
        filters.append(
            FilterEstimate(
                property_name=property_filter.property_name, values=property_filter.values, granules_read=share
            )
        )
    return (
        TableScanEstimate(
            name=scan.name,
            source="events",
            precision="measured",
            rows=int(volume.per_day * scan.days * fraction * granules_read),
            days=scan.days,
            events=tuple(sorted(scan.events)) if fraction < 1 else (),
            time_range="bounded" if scan.bounded else "open",
            filters=tuple(filters),
        ),
        unmodelled,
    )


def _estimate_sessions_scan(scan: "_SessionsScan", team_id: int, provider: StatisticsProvider) -> TableScanEstimate:
    per_day = provider.daily_rows(team_id, scan.table)
    if per_day is None:
        return TableScanEstimate(name=scan.name, source="clickhouse", precision="unknown")
    return TableScanEstimate(
        name=scan.name,
        source="clickhouse",
        precision="measured",
        rows=int(per_day * scan.days),
        days=scan.days,
        time_range="bounded" if scan.bounded else "open",
    )


def _granule_fraction(values: int, distinct_values: int) -> float:
    """Share of granules expected to hold at least one row matching an equality on ``values`` constants.

    Assumes the property's values are spread evenly over rows and over the table, because the events sort
    key does not order by any property. Under that assumption a filter narrows the read only when the
    property has far more distinct values than a granule has rows: a few thousand distinct values already
    put a match in nearly every granule. Bloom filter false positives are not modelled.
    """
    match_probability = min(values / distinct_values, 1.0)
    return 1.0 - (1.0 - match_probability) ** GRANULE_ROWS


@frozen
class _PropertyFilter:
    """An equality or IN on an event property that a bloom filter index can prune granules for."""

    property_name: str
    # How many constants the property is compared against: one for ``=``, the set size for IN.
    values: int


@frozen
class _EventsScan:
    """One read of the events table, after the predicates that apply to it were folded in."""

    name: str
    days: float
    bounded: bool
    events: frozenset[str]
    property_filters: tuple[_PropertyFilter, ...] = ()
    # An indexed filter applies to this scan but its effect on the read is not modelled.
    unmodelled_filter: bool = False


@frozen
class _SessionsScan:
    """One read of a sessions table, narrowed to the start-time range the query asks for."""

    name: str
    # The physical table the rate is counted on.
    table: str
    days: float
    bounded: bool


@frozen
class _OtherScan:
    """One read of a table that is not events. Sized once the statistics provider is at hand."""

    name: str
    table: Table


@frozen
class _TableRef:
    """A physical table in a FROM clause. ``alias`` is None when it is joined unaliased."""

    table: Table
    alias: str | None


def _table_ref(table_type: ast.Type | None) -> _TableRef | None:
    alias: str | None = None
    while isinstance(table_type, ast.TableAliasType):
        alias = table_type.alias
        table_type = table_type.table_type
    if isinstance(table_type, ast.TableType | ast.LazyTableType):
        return _TableRef(table=table_type.table, alias=alias)
    return None


def _events_table(table_type: ast.Type | None) -> _TableRef | None:
    ref = _table_ref(table_type)
    return ref if ref is not None and isinstance(ref.table, EventsTable) else None


# The lazy tables read their raw counterpart, so both map to the physical table the rate is counted on.
_SESSIONS_TABLES: dict[type[Table], str] = {
    SessionsTableV1: "sessions",
    RawSessionsTableV1: "sessions",
    SessionsTableV2: "raw_sessions",
    RawSessionsTableV2: "raw_sessions",
    SessionsTableV3: "raw_sessions_v3",
    RawSessionsTableV3: "raw_sessions_v3",
}
# Columns on which a comparison bounds a sessions scan: the lazy table's start time and the raw columns behind it.
_SESSION_START_COLUMNS = frozenset({"$start_timestamp", "min_timestamp", "session_timestamp"})


def _table_scans(
    node: ast.Expr, now: datetime, context: HogQLContext, ctes: Mapping[str, CTE]
) -> list[_EventsScan | _SessionsScan | _OtherScan] | None:
    """Every table scan a query's FROM clause performs, or None when the FROM tree cannot be walked.

    ``ctes`` are the subquery CTEs in scope. The resolver leaves a CTE reference in the FROM clause typed
    as ``CTETableType`` and keeps the body on the select that declared it, so the body is followed here.
    Subqueries in the select list or WHERE clause are not walked: they are rare in editor queries and
    skipping them undercounts, which the "up to" wording does not promise against.
    """
    if isinstance(node, ast.SelectSetQuery):
        scans: list[_EventsScan | _SessionsScan | _OtherScan] = []
        in_scope = dict(ctes)
        for branch in node.select_queries():
            branch_scans = _table_scans(branch, now, context, in_scope)
            if branch_scans is None:
                return None
            scans.extend(branch_scans)
            # A WITH on the first branch is visible to the later ones.
            if isinstance(branch, ast.SelectQuery) and branch.ctes:
                in_scope.update(branch.ctes)
        return scans
    if not isinstance(node, ast.SelectQuery):
        return None
    if node.select_from is None:
        return []
    if node.ctes:
        ctes = {**ctes, **node.ctes}

    predicates = _WherePredicates(now=now, context=context)
    if node.where is not None:
        predicates.visit(node.where)

    scans = []
    join: ast.JoinExpr | None = node.select_from
    while join is not None:
        source = _join_source(join, ctes)
        if source is None:
            return None
        if isinstance(source, _TableRef):
            name = _scan_name(join, source)
            if isinstance(source.table, EventsTable):
                scans.append(predicates.scan_for(name, source.alias))
            elif (sessions_table := _SESSIONS_TABLES.get(type(source.table))) is not None:
                scans.append(predicates.sessions_scan_for(name, source.alias, sessions_table))
            else:
                scans.append(_OtherScan(name=name, table=source.table))
        else:
            inner = _table_scans(source, now, context, ctes)
            if inner is None:
                return None
            scans.extend(inner)
        join = join.next_join
    return scans


def _join_source(
    join: ast.JoinExpr, ctes: Mapping[str, CTE]
) -> ast.SelectQuery | ast.SelectSetQuery | _TableRef | None:
    """What one side of a FROM clause reads: a subquery to descend into, a table, or None when unknown."""
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
    return _table_ref(join.type)


def _scan_name(join: ast.JoinExpr, ref: _TableRef) -> str:
    """The table as the query names it, so the breakdown reads like the SQL the person wrote."""
    if isinstance(join.table, ast.Field):
        return ".".join(str(part) for part in join.table.chain)
    return ref.table.to_printed_hogql()


# HogQL tables whose physical rows live in one replicated ClickHouse table keyed by team. The lazy tables read
# their raw counterpart, so both map to the same count.
_COUNTED_CLICKHOUSE_TABLES: dict[type[Table], str] = {
    PersonsTable: PERSONS_TABLE,
    RawPersonsTable: PERSONS_TABLE,
    GroupsTable: GROUPS_TABLE,
    RawGroupsTable: GROUPS_TABLE,
}


def _other_table_estimate(scan: _OtherScan, team_id: int, provider: StatisticsProvider) -> TableScanEstimate:
    name, table = scan.name, scan.table
    if isinstance(table, DataWarehouseTable) and (table.row_count is not None or table.size_in_s3_mib is not None):
        # Every sync records the table's rows and bytes. There is no model of how much of them a query reads.
        return TableScanEstimate(
            name=name,
            source="warehouse",
            precision="size_only",
            rows=table.row_count,
            bytes=int(table.size_in_s3_mib * 1024 * 1024) if table.size_in_s3_mib is not None else None,
        )
    if isinstance(table, S3Table):
        return TableScanEstimate(name=name, source="warehouse", precision="unknown")
    if isinstance(table, DirectSQLTable):
        if table.estimated_row_count is None:
            return TableScanEstimate(name=name, source="direct", precision="unknown")
        # The remote catalog's figure for the whole table. Nothing returns read_rows for a query that ran on
        # the customer's database, so this entry is never scored.
        return TableScanEstimate(name=name, source="direct", precision="size_only", rows=table.estimated_row_count)
    if isinstance(table, FunctionCallTable):
        return TableScanEstimate(name=name, source="static", precision="unknown")
    counted = _COUNTED_CLICKHOUSE_TABLES.get(type(table))
    rows = provider.table_rows(team_id, counted) if counted is not None else None
    if rows is None:
        return TableScanEstimate(name=name, source="clickhouse", precision="unknown")
    # A count of the team's rows, not of what the query reads: a filter on a person property cannot narrow it.
    return TableScanEstimate(name=name, source="clickhouse", precision="size_only", rows=rows)


def _event_fraction(volume: EventVolume, events: frozenset[str]) -> float:
    if not events:
        return 1.0
    fractions = [volume.event_fraction(event) for event in events]
    # An event name the rollup never saw contributes nothing. A brand-new event has no history either
    # way, so treating it as zero is the smaller error.
    return min(sum(f for f in fractions if f is not None), 1.0)


class _WherePredicates(TraversingVisitor):
    """Collects timestamp bounds, event-name filters and indexed property filters from a WHERE clause.

    Only the top-level AND chain narrows the estimate. Anything under OR, NOT or a function call is skipped,
    because a disjunction can widen the scan back to the whole table and the estimator must never narrow on it.
    Keyed by alias so that in a self-join ``a.timestamp > x`` narrows the scan of ``a`` and not of ``b``.
    """

    def __init__(self, *, now: datetime, context: HogQLContext) -> None:
        super().__init__()
        self._now = now
        self._context = context
        # Bounds are keyed by (table kind, alias): an unaliased events table and an unaliased sessions table
        # in one join must not share a range.
        self._lower_bounds: dict[tuple[str, str | None], datetime] = {}
        self._upper_bounds: dict[tuple[str, str | None], datetime] = {}
        self._events: dict[str | None, set[str]] = {}
        self._property_filters: dict[str | None, list[_PropertyFilter]] = {}
        # Set when an indexed filter cannot be pinned to one scan or modelled. It applies to every scan of
        # the select, because a filter under OR or on a joined table cannot be attributed to one alias.
        self._unmodelled_filter = False

    def _range(self, kind: str, alias: str | None) -> tuple[float, bool]:
        since = self._lower_bounds.get((kind, alias))
        until = self._upper_bounds.get((kind, alias))
        bounded = since is not None and until is not None
        since = since or (self._now - timedelta(days=DEFAULT_RANGE_DAYS))
        until = until or self._now
        return max((until - since).total_seconds() / 86_400, 0.0), bounded

    def sessions_scan_for(self, name: str, alias: str | None, table: str) -> _SessionsScan:
        days, bounded = self._range("sessions", alias)
        return _SessionsScan(name=name, table=table, days=days, bounded=bounded)

    def scan_for(self, name: str, alias: str | None) -> _EventsScan:
        days, bounded = self._range("events", alias)
        return _EventsScan(
            name=name,
            days=days,
            bounded=bounded,
            events=frozenset(self._events.get(alias, ())),
            property_filters=tuple(self._property_filters.get(alias, ())),
            unmodelled_filter=self._unmodelled_filter,
        )

    def visit_or(self, node: ast.Or) -> None:
        self._skip(node)

    def visit_not(self, node: ast.Not) -> None:
        self._skip(node)

    def visit_call(self, node: ast.Call) -> None:
        # ``not (x)`` and ``or(x, y)`` parse to calls, and any other function can turn a comparison into
        # something that no longer restricts rows. Only the call form of AND keeps its arguments as filters.
        if node.name.lower() == "and":
            super().visit_call(node)
        else:
            self._skip(node)

    def _skip(self, node: ast.Expr) -> None:
        finder = _IndexedFilterFinder(self._context)
        finder.visit(node)
        self._unmodelled_filter = self._unmodelled_filter or finder.found

    def visit_select_query(self, node: ast.SelectQuery) -> None:
        return

    def visit_compare_operation(self, node: ast.CompareOperation) -> None:
        for field_side, value_side, flipped in ((node.left, node.right, False), (node.right, node.left, True)):
            located = _table_column(field_side)
            if located is None:
                continue
            ref, column = located
            if isinstance(ref.table, EventsTable):
                if column == "timestamp":
                    self._record_timestamp(("events", ref.alias), node.op, value_side, flipped)
                elif column == "event" and node.op in (ast.CompareOperationOp.Eq, ast.CompareOperationOp.In):
                    self._events.setdefault(ref.alias, set()).update(_string_constants(value_side))
            elif type(ref.table) in _SESSIONS_TABLES and column in _SESSION_START_COLUMNS:
                self._record_timestamp(("sessions", ref.alias), node.op, value_side, flipped)
        self._record_property_filter(node)

    def _record_property_filter(self, node: ast.CompareOperation) -> None:
        plan = plan_property_comparison(node, self._context)
        if plan is None:
            return
        eligibility = eligibility_from_plan(plan)
        if not eligibility.prunes_data:
            return

        table = _events_table(plan.access.property_type.field_type.table_type)
        value_side = node.right if plan.property_side == "left" else node.left
        values = _constant_count(value_side)
        modelled = (
            plan.access.scope == PropertyScope.EVENT
            and plan.operator in (ast.CompareOperationOp.Eq, ast.CompareOperationOp.In)
            and IndexKind.BLOOM_FILTER in eligibility.usable_indexes
            and values > 0
        )
        if table is None or not modelled:
            self._unmodelled_filter = True
            return
        self._property_filters.setdefault(table.alias, []).append(
            _PropertyFilter(property_name=plan.access.property_name, values=values)
        )

    def _record_timestamp(
        self, key: tuple[str, str | None], op: ast.CompareOperationOp, value: ast.Expr, flipped: bool
    ) -> None:
        moment = _constant_datetime(value, self._now)
        if moment is None:
            return
        greater = op in (ast.CompareOperationOp.Gt, ast.CompareOperationOp.GtEq)
        less = op in (ast.CompareOperationOp.Lt, ast.CompareOperationOp.LtEq)
        if flipped:
            greater, less = less, greater
        if greater:
            current = self._lower_bounds.get(key)
            self._lower_bounds[key] = max(current, moment) if current else moment
        elif less:
            current = self._upper_bounds.get(key)
            self._upper_bounds[key] = min(current, moment) if current else moment


class _IndexedFilterFinder(TraversingVisitor):
    """Reports whether a subtree holds a property comparison that a skip index can prune."""

    def __init__(self, context: HogQLContext) -> None:
        super().__init__()
        self._context = context
        self.found = False

    def visit_select_query(self, node: ast.SelectQuery) -> None:
        return

    def visit_compare_operation(self, node: ast.CompareOperation) -> None:
        plan = plan_property_comparison(node, self._context)
        if plan is not None and eligibility_from_plan(plan).prunes_data:
            self.found = True
        super().visit_compare_operation(node)


def _table_column(expr: ast.Expr) -> tuple[_TableRef, str] | None:
    """(table, column name) when ``expr`` reads a plain column of a physical table, else None."""
    while isinstance(expr, ast.Alias):
        expr = expr.expr
    if not isinstance(expr, ast.Field):
        return None
    field_type = expr.type
    if isinstance(field_type, ast.FieldAliasType):
        field_type = field_type.type
    if not isinstance(field_type, ast.FieldType):
        return None
    table = _table_ref(field_type.table_type)
    if table is None:
        return None
    return table, field_type.name


def _string_constants(expr: ast.Expr) -> list[str]:
    if isinstance(expr, ast.Constant):
        return [expr.value] if isinstance(expr.value, str) else []
    if isinstance(expr, ast.Tuple | ast.Array):
        return [value for item in expr.exprs for value in _string_constants(item)]
    return []


def _constant_count(expr: ast.Expr) -> int:
    """How many constants ``expr`` lists, or 0 when any part of it is not a constant."""
    if isinstance(expr, ast.Constant):
        return 1
    if isinstance(expr, ast.Tuple | ast.Array):
        counts = [_constant_count(item) for item in expr.exprs]
        return sum(counts) if all(counts) else 0
    return 0


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
