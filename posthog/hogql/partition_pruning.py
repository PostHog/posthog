"""Static detection of `events` scans that ClickHouse cannot narrow to a subset of partitions.

`sharded_events` is `PARTITION BY toYYYYMM(timestamp)` (see posthog/models/event/sql.py), so a scan that
places no bound on `timestamp` has to open every monthly partition the team has. Partition selection runs
before any skip index or sort-key prefix narrows the read, which makes it the coarsest cost lever in a
query, and the online workload aborts a query that reads past its byte ceiling (see
posthog/clickhouse/client/execute.py) rather than merely running it slowly.

This analysis runs on the parsed AST before type resolution, so it matches fields by name. It reports a
scan only when no bound it recognizes can reach that scan. An enclosing bound and an enclosing row limit
both carry down into subqueries, because a wrong warning in the editor costs more than a missed one.
Recognizing a bound works off an allowlist of order-preserving wrappers, so a monotonic function missing
from that list warns about a query that does in fact prune.

Matching by name means a bound cannot be attributed to the table it constrains, which under-reports in
two known shapes. A query joining two events sources and bounding only one counts as bounded for both.
An outer bound counts for an independent subquery that the outer predicate cannot reach. Both stay
silent rather than warn. Attributing bounds to tables needs the analysis to run after type resolution,
which would cost it the cheap pre-resolution property this relies on.
"""

from posthog.hogql import ast
from posthog.hogql.escape_sql import escape_hogql_identifier
from posthog.hogql.functions.mapping import find_hogql_aggregation
from posthog.hogql.helpers.timestamp_visitor import is_time_or_interval_constant
from posthog.hogql.visitor import TraversingVisitor

from posthog.dataclasses import frozen

EVENTS_TABLE_NAME = "events"
EVENTS_PARTITION_KEY = "toYYYYMM(timestamp)"

# Shared by the editor marker and the scan report so the two cannot drift apart.
UNPRUNED_SCAN_MESSAGE = "No filter on events.timestamp, so this reads your full event history."
UNPRUNED_SCAN_FIX = "Add WHERE timestamp > now() - INTERVAL 30 DAY to read a recent time range."
UNPRUNED_SCAN_FIX_TITLE = "Add a time range"

# The bound the quick fix writes. It matches the interval named in UNPRUNED_SCAN_FIX.
_BOUND_EXPRESSION = "now() - INTERVAL 30 DAY"

# Wrappers that keep the ordering of `timestamp`, so a bound on the wrapped expression still bounds
# `toYYYYMM(timestamp)` and prunes partitions. Mirrors the allowlist that helpers/timestamp_visitor.py
# uses for the same reasoning. A non-monotonic wrapper such as toDayOfWeek must stay out: a bound on it
# matches rows in every partition.
_ORDER_PRESERVING_TIMESTAMP_FUNCTIONS = frozenset(
    {
        "assumeNotNull",
        "parseDateTime64BestEffortOrNull",
        "toDate",
        "toDateOrNull",
        "toDateTime",
        "toDateTime64",
        "toDateTimeOrNull",
        "toLastDayOfMonth",
        "toMonday",
        "toStartOfDay",
        "toStartOfFifteenMinutes",
        "toStartOfFiveMinutes",
        "toStartOfHour",
        "toStartOfInterval",
        "toStartOfMinute",
        "toStartOfMonth",
        "toStartOfQuarter",
        "toStartOfWeek",
        "toStartOfYear",
        "toTimeZone",
        "toUnixTimestamp",
        "toYYYYMM",
        "toYYYYMMDD",
        "toYYYYMMDDhhmmss",
    }
)

_BOUNDING_COMPARE_OPS = frozenset(
    {
        ast.CompareOperationOp.Eq,
        ast.CompareOperationOp.Gt,
        ast.CompareOperationOp.GtEq,
        ast.CompareOperationOp.Lt,
        ast.CompareOperationOp.LtEq,
    }
)


@frozen
class QueryTextEdit:
    """A replacement in the query source, as offsets into the text the query was parsed from."""

    start: int
    end: int
    text: str


@frozen
class UnprunedEventsScan:
    """An `events` scan that no timestamp bound in scope can narrow to a subset of partitions."""

    start: int | None
    end: int | None
    # Empty when the query shape has no unambiguous place to write the bound.
    bound_edits: tuple[QueryTextEdit, ...] = ()


def find_unpruned_events_scans(query: ast.SelectQuery | ast.SelectSetQuery) -> list[UnprunedEventsScan]:
    scans: list[UnprunedEventsScan] = []
    # The root starts capped because HogQLQueryExecutor._apply_limit gives every top-level select a
    # default LIMIT when the query does not write one.
    _collect_scans(query, bounded=False, capped=True, shadowed=frozenset(), scans=scans)
    return scans


def _collect_scans(
    node: ast.Expr,
    *,
    bounded: bool,
    capped: bool,
    shadowed: frozenset[str],
    scans: list[UnprunedEventsScan],
) -> None:
    """Report every unbounded `events` scan under `node`.

    `bounded` says an enclosing query confines `timestamp`, and `capped` says an enclosing query limits
    the rows it consumes. Either one keeps a scan under `node` off the report.
    """
    if isinstance(node, ast.SelectSetQuery):
        for branch in node.select_queries():
            _collect_scans(branch, bounded=bounded, capped=capped, shadowed=shadowed, scans=scans)
        return
    if not isinstance(node, ast.SelectQuery):
        return

    bounded_here = bounded or _query_bounds_timestamp(node)
    # A row limit only caps the read when the scan can stop early. The enclosing limit carries into such
    # a query because ClickHouse stops reading the source once the outer limit is satisfied.
    capped_here = _terminates_early(node) and (capped or node.limit is not None)

    # A CTE named `events` hides the real table, but only from the scopes that can see the name. The
    # resolver reads a CTE's own body before registering it, so `WITH events AS (SELECT ... FROM
    # events)` reads the physical table inside that body.
    for name, cte in (node.ctes or {}).items():
        _collect_scans(cte.expr, bounded=bounded_here, capped=capped_here, shadowed=shadowed, scans=scans)
        shadowed = shadowed | {name}

    join = node.select_from
    while join is not None:
        table = join.table
        if isinstance(table, ast.Field):
            if not bounded_here and not capped_here and _is_events_table(table, shadowed):
                scans.append(
                    UnprunedEventsScan(
                        start=table.start,
                        end=table.end,
                        bound_edits=_bound_edits(node, join),
                    )
                )
        elif isinstance(table, ast.SelectQuery | ast.SelectSetQuery):
            _collect_scans(table, bounded=bounded_here, capped=capped_here, shadowed=shadowed, scans=scans)
        join = join.next_join

    # A subquery outside FROM builds its whole result before the enclosing query reads a row, so no outer
    # limit caps it. The enclosing bound still carries down, because predicate pushdown can reach a
    # correlated subquery and a wrong warning costs more than a missed one.
    for subquery in _nested_select_queries(node):
        _collect_scans(subquery, bounded=bounded_here, capped=False, shadowed=shadowed, scans=scans)


def _bound_edits(query: ast.SelectQuery, events_join: ast.JoinExpr) -> tuple[QueryTextEdit, ...]:
    """Edits that add a timestamp bound to `query`, or nothing when the shape makes that ambiguous."""
    predicate = f"{_timestamp_column(query, events_join)} > {_BOUND_EXPRESSION}"

    join_type = (events_join.join_type or "").upper()
    if join_type.startswith("LEFT"):
        # The join null-extends the events columns for every unmatched row, and a WHERE predicate
        # discards those rows because NULL > x is never true. That turns the LEFT JOIN into an inner
        # join and drops rows the reader asked to keep. The ON clause narrows the scan instead.
        return _conjunct_edits(events_join.constraint, predicate)

    # A RIGHT or FULL join can null-extend the events rows from elsewhere in the chain, and working
    # out which side survives is more than this analysis knows. Those shapes get no fix.
    if _chain_has_right_or_full_join(query.select_from):
        return ()

    if query.where is not None:
        return _conjunct_edits_for_expr(query.where, predicate)

    # PREWHERE and ARRAY JOIN sit between the FROM clause and the WHERE clause, so a WHERE written at
    # the insertion point below would land in front of them.
    if query.prewhere is not None or query.array_join_list:
        return ()

    insert_at = _join_chain_end(query.select_from)
    if insert_at is None:
        return ()
    return (QueryTextEdit(start=insert_at, end=insert_at, text=f" WHERE {predicate}"),)


def _timestamp_column(query: ast.SelectQuery, events_join: ast.JoinExpr) -> str:
    """How to name the events timestamp so it stays unambiguous next to any joined table."""
    if events_join.alias:
        return f"{escape_hogql_identifier(events_join.alias)}.timestamp"
    if query.select_from is not None and query.select_from.next_join is not None:
        return f"{EVENTS_TABLE_NAME}.timestamp"
    return "timestamp"


def _conjunct_edits(constraint: ast.JoinConstraint | None, predicate: str) -> tuple[QueryTextEdit, ...]:
    # USING lists columns rather than a condition, so there is nothing to add a conjunct to.
    if constraint is None or constraint.constraint_type != "ON":
        return ()
    return _conjunct_edits_for_expr(constraint.expr, predicate)


def _conjunct_edits_for_expr(expr: ast.Expr, predicate: str) -> tuple[QueryTextEdit, ...]:
    """Add `predicate` to `expr` as a conjunct, parenthesizing what is already there."""
    if expr.start is None or expr.end is None:
        return ()
    # The existing condition gets parentheses because appending `AND x` to `a OR b` binds to `b`
    # alone, which changes which rows match.
    return (
        QueryTextEdit(start=expr.start, end=expr.start, text="("),
        QueryTextEdit(start=expr.end, end=expr.end, text=f") AND {predicate}"),
    )


def _chain_has_right_or_full_join(join: ast.JoinExpr | None) -> bool:
    while join is not None:
        join_type = (join.join_type or "").upper()
        if join_type.startswith("RIGHT") or join_type.startswith("FULL"):
            return True
        join = join.next_join
    return False


def _join_chain_end(join: ast.JoinExpr | None) -> int | None:
    """The offset just past the FROM clause, including any join constraint that trails the table."""
    ends: list[int] = []
    while join is not None:
        if join.end is not None:
            ends.append(join.end)
        if join.constraint is not None and join.constraint.end is not None:
            ends.append(join.constraint.end)
        join = join.next_join
    return max(ends) if ends else None


def _is_events_table(table: ast.Field, shadowed: frozenset[str]) -> bool:
    return list(table.chain) == [EVENTS_TABLE_NAME] and EVENTS_TABLE_NAME not in shadowed


def _query_bounds_timestamp(query: ast.SelectQuery) -> bool:
    if _bounds_timestamp(query.where) or _bounds_timestamp(query.prewhere):
        return True
    # A join later in the chain still bounds a scan earlier in it, so every constraint counts.
    join = query.select_from
    while join is not None:
        if join.constraint is not None and _bounds_timestamp(join.constraint.expr):
            return True
        join = join.next_join
    return False


def _bounds_timestamp(expr: ast.Expr | None) -> bool:
    """True when `expr` confines `timestamp` to a range on every path that can match a row."""
    if expr is None:
        return False
    if isinstance(expr, ast.And):
        return any(_bounds_timestamp(child) for child in expr.exprs)
    if isinstance(expr, ast.Or):
        # A branch with no bound matches rows in any partition, so every branch has to bound.
        return bool(expr.exprs) and all(_bounds_timestamp(child) for child in expr.exprs)
    if isinstance(expr, ast.CompareOperation):
        if expr.op not in _BOUNDING_COMPARE_OPS:
            return False
        return (_is_timestamp_expression(expr.left) and _is_time_constant(expr.right)) or (
            _is_timestamp_expression(expr.right) and _is_time_constant(expr.left)
        )
    if isinstance(expr, ast.BetweenExpr):
        return (
            not expr.negated
            and _is_timestamp_expression(expr.expr)
            and _is_time_constant(expr.low)
            and _is_time_constant(expr.high)
        )
    return False


def _is_timestamp_expression(expr: ast.Expr) -> bool:
    if isinstance(expr, ast.Alias | ast.TypeCast | ast.TryCast):
        return _is_timestamp_expression(expr.expr)
    if isinstance(expr, ast.ArithmeticOperation):
        return (_is_timestamp_expression(expr.left) and _is_time_constant(expr.right)) or (
            _is_timestamp_expression(expr.right) and _is_time_constant(expr.left)
        )
    if isinstance(expr, ast.Call):
        if expr.name in _ORDER_PRESERVING_TIMESTAMP_FUNCTIONS and expr.args:
            return _is_timestamp_expression(expr.args[0])
        return False
    if isinstance(expr, ast.Field):
        return bool(expr.chain) and expr.chain[-1] == "timestamp"
    return False


def _is_time_constant(expr: ast.Expr) -> bool:
    try:
        return is_time_or_interval_constant(expr)
    except Exception:
        # The visitor raises on an unreplaced placeholder and on nodes it has no case for. Metadata runs
        # on every keystroke, so treat the expression as non-constant instead of failing the request.
        return False


def _terminates_early(query: ast.SelectQuery) -> bool:
    """True when a row limit really does cap the read, so an unbounded scan stays cheap.

    Early termination needs every row to qualify. A filter breaks that: to return one row of
    `WHERE event = 'never_matches' LIMIT 1`, ClickHouse reads every partition to prove no row matches,
    and the rarer the value the more it reads. An ORDER BY breaks it too, because `timestamp` is not a
    prefix of either physical sort key: the JSON table orders by
    `(team_id, toDate(timestamp), event, timestamp, ...)` and the distributed table has no raw timestamp
    in its key at all, so `event` intervenes and the sort sees full history before the limit applies.
    """
    if query.distinct or query.group_by or query.having or query.array_join_list:
        return False
    if query.qualify or query.window_exprs or query.limit_by:
        return False
    if query.where is not None or query.prewhere is not None:
        return False
    # A join can consume its whole input before it produces a row, because a limited result says
    # nothing about how many rows had to be probed to find a match.
    if query.select_from is not None and query.select_from.next_join is not None:
        return False
    if query.order_by:
        return False
    # An offset still has to read and discard the rows it skips.
    if query.offset is not None:
        return False
    # An inline `OVER (...)` is a WindowFunction in the select list and leaves window_exprs unset, so
    # the clause check above does not see it. A window still orders the whole partition first.
    return not any(_contains_aggregation(expr) or _contains_window_function(expr) for expr in query.select)


class _AggregationFinder(TraversingVisitor):
    def __init__(self) -> None:
        self.found = False

    def visit_call(self, node: ast.Call) -> None:
        if find_hogql_aggregation(node.name):
            self.found = True
        super().visit_call(node)

    # An aggregate inside a subquery aggregates that subquery, so it says nothing about whether this
    # select list streams rows.
    def visit_select_query(self, node: ast.SelectQuery) -> None:
        pass

    def visit_select_set_query(self, node: ast.SelectSetQuery) -> None:
        pass


def _contains_aggregation(expr: ast.Expr) -> bool:
    finder = _AggregationFinder()
    finder.visit(expr)
    return finder.found


class _WindowFunctionFinder(TraversingVisitor):
    def __init__(self) -> None:
        self.found = False

    def visit_window_function(self, node: ast.WindowFunction) -> None:
        self.found = True

    # A window inside a subquery belongs to that subquery.
    def visit_select_query(self, node: ast.SelectQuery) -> None:
        pass

    def visit_select_set_query(self, node: ast.SelectSetQuery) -> None:
        pass


def _contains_window_function(expr: ast.Expr) -> bool:
    finder = _WindowFunctionFinder()
    finder.visit(expr)
    return finder.found


class _NestedSelectFinder(TraversingVisitor):
    def __init__(self) -> None:
        self.queries: list[ast.SelectQuery | ast.SelectSetQuery] = []

    def visit_select_query(self, node: ast.SelectQuery) -> None:
        self.queries.append(node)

    def visit_select_set_query(self, node: ast.SelectSetQuery) -> None:
        self.queries.append(node)


def _nested_select_queries(query: ast.SelectQuery) -> list[ast.SelectQuery | ast.SelectSetQuery]:
    """Select queries reachable from clauses other than FROM, which _collect_scans walks itself."""
    finder = _NestedSelectFinder()
    for expr in [*query.select, query.where, query.prewhere, query.having, query.qualify]:
        if expr is not None:
            finder.visit(expr)
    return finder.queries
