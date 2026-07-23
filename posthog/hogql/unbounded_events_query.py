"""Detect HogQL queries that read the events table without constraining ``timestamp``.

A ``SELECT ... FROM events`` with no bound on ``timestamp`` scans the whole history of the table.
Compiled insight queries (trends, funnels, …) always inject a date range, so only hand-written
HogQL can end up unbounded. This module flags that shape so query execution can surface it as
telemetry (see ``posthog/hogql/query.py``) and we can alert on it.

Works on raw or resolved ASTs: it uses type info when available and falls back to chain matching
otherwise, mirroring ``feature_extractor.py``. In production it runs on the unresolved AST, so the
chain-matching paths are what actually decide.

This flags the *shape* — a timestamp-less events read — which is the signal; the emitted event
carries enough context (dashboard, access method, insight id) for the alert / insight to segment by
cost. We deliberately don't pre-judge cost here: a ``LIMIT``-only read is bounded rather than a full
scan, but it's the same omitted-``timestamp`` pattern, so we surface it and let the consumer decide.
The rule errs toward precision so a genuinely bounded query isn't mislabeled:
- A ``timestamp`` bound counts only where it can prune the scan: WHERE / PREWHERE, respecting
  boolean structure (an ``OR`` bounds only if every branch does). HAVING runs after the full scan,
  so it never counts.
- A qualified ``x.timestamp`` counts only when ``x`` names the events table, so a JOINed table's
  ``timestamp`` filter doesn't mask an unbounded events read.
- A bound on an *enclosing* SELECT counts too, because ClickHouse pushes such predicates down into
  the single subquery / CTE feeding it (the common "prefilter in a CTE, bound in the outer query"
  pattern) — but not across a join or into an independent WHERE/SELECT subquery.
"""

from collections.abc import Iterator

from posthog.hogql import ast
from posthog.hogql.database.schema.events import EventsTable
from posthog.hogql.feature_extractor import resolves_to_events_column
from posthog.hogql.visitor import TraversingVisitor


def query_reads_events_without_timestamp_filter(node: ast.Expr | None) -> bool:
    """``True`` iff some SELECT in the tree reads the events table with no timestamp bound able to
    constrain its scan — its own filters or an enclosing SELECT's (which push down into it)."""
    if node is None:
        return False
    detector = _UnboundedEventsQueryDetector(_collect_cte_names(node))
    detector.visit(node)
    return detector.found


def _collect_cte_names(node: ast.Expr) -> set[str]:
    """Every CTE name defined anywhere in the tree. A ``FROM <name>`` matching one is a CTE
    reference, not the real events table, even when it is named ``events``."""
    collector = _CTENameCollector()
    collector.visit(node)
    return collector.names


class _CTENameCollector(TraversingVisitor):
    def __init__(self) -> None:
        super().__init__()
        self.names: set[str] = set()

    def visit_select_query(self, node: ast.SelectQuery) -> None:
        if node.ctes:
            self.names.update(node.ctes.keys())
        super().visit_select_query(node)


class _UnboundedEventsQueryDetector(TraversingVisitor):
    def __init__(self, cte_names: set[str]) -> None:
        super().__init__()
        self.cte_names = cte_names
        self.found = False
        # Whether the SELECT currently being entered is fed by a timestamp-bounded outer query. Set
        # only while descending into a bounded SELECT's single FROM source / CTEs, since ClickHouse
        # pushes an outer predicate down into the table feeding a query — but not across a join or
        # into an independent WHERE / SELECT-list subquery (``... IN (SELECT … FROM events)``).
        self._from_bound = False

    def visit_select_query(self, node: ast.SelectQuery) -> None:
        events_ids = _events_table_identifiers(node, self.cte_names)
        bounded = self._from_bound or _has_events_timestamp_filter(node, events_ids)
        if not self.found and events_ids and not bounded:
            self.found = True

        outer_from_bound = self._from_bound
        # A bound pushes down only into a single source (its FROM subquery / consumed CTE). With a
        # join the predicate may filter only one side, so judge each joined source independently.
        single_source = node.select_from is not None and node.select_from.next_join is None
        # FROM subquery and CTEs inherit the bound (predicates push down into the table feeding us).
        self._from_bound = bounded and single_source
        self.visit(node.select_from)
        for cte in (node.ctes or {}).values():
            self.visit(cte)
        # Everything else is a fresh scope — a bound here doesn't reach its subqueries.
        # (Keep in sync with visitor.py's SelectQuery traversal.)
        self._from_bound = False
        for array_join in node.array_join_list or []:
            self.visit(array_join)
        for column in node.select or []:
            self.visit(column)
        self.visit(node.where)
        self.visit(node.prewhere)
        self.visit(node.having)
        self.visit(node.qualify)
        for group in node.group_by or []:
            self.visit(group)
        for order in node.order_by or []:
            self.visit(order)
        for interpolate in node.interpolate or []:
            self.visit(interpolate)
        self.visit(node.limit_by)
        self.visit(node.limit)
        self.visit(node.offset)
        for window in (node.window_exprs or {}).values():
            self.visit(window)
        self._from_bound = outer_from_bound


def _iter_joins(node: ast.SelectQuery) -> Iterator[ast.JoinExpr]:
    join: ast.JoinExpr | None = node.select_from
    while join is not None:
        yield join
        join = join.next_join


def _events_table_identifiers(node: ast.SelectQuery, cte_names: set[str]) -> set[str]:
    """Names that refer to the events table in this SELECT's own FROM / JOIN chain — each events
    source's alias (or ``events`` when unaliased). Empty when the SELECT doesn't read events
    directly (nested subqueries are scored on their own). Also used to attribute an unresolved
    ``x.timestamp`` filter to the right table."""
    ids: set[str] = set()
    for join in _iter_joins(node):
        if _is_events_table(join.table, cte_names):
            ids.add("events")
            if join.alias:
                ids.add(join.alias)
    return ids


def _is_events_table(expr: ast.Expr | None, cte_names: set[str]) -> bool:
    type_ = getattr(expr, "type", None)
    while isinstance(type_, (ast.TableAliasType, ast.ColumnAliasedTableType)):
        type_ = type_.table_type
    if isinstance(type_, ast.TableType) and isinstance(type_.table, EventsTable):
        return True
    # No type info — match the FROM identifier, but a CTE named "events" shadows the real table.
    return isinstance(expr, ast.Field) and bool(expr.chain) and expr.chain[0] == "events" and "events" not in cte_names


def _has_events_timestamp_filter(node: ast.SelectQuery, events_ids: set[str]) -> bool:
    # HAVING is evaluated after aggregation over the full scan, so it never bounds the read —
    # only WHERE / PREWHERE do.
    return _expr_bounds_events_timestamp(node.where, events_ids) or _expr_bounds_events_timestamp(
        node.prewhere, events_ids
    )


def _expr_bounds_events_timestamp(expr: ast.Expr | None, events_ids: set[str]) -> bool:
    """Whether a filter expression guarantees the events ``timestamp`` is constrained. Respects
    boolean structure: an ``AND`` bounds if any operand bounds; an ``OR`` bounds only if *every*
    operand does (``timestamp > x OR event = 'y'`` still admits all history); a leaf bounds when it
    references the events ``timestamp`` column — deliberately without checking it's a range
    comparison, so ``timestamp IS NOT NULL`` or ``timestamp != now()`` count as bounded too; full
    range-pruning analysis would require semantic evaluation this module doesn't attempt."""
    if expr is None:
        return False
    if isinstance(expr, ast.And):
        return any(_expr_bounds_events_timestamp(e, events_ids) for e in expr.exprs)
    if isinstance(expr, ast.Or):
        return bool(expr.exprs) and all(_expr_bounds_events_timestamp(e, events_ids) for e in expr.exprs)
    finder = _TimestampFieldFinder(events_ids)
    finder.visit(expr)
    return finder.found


class _TimestampFieldFinder(TraversingVisitor):
    def __init__(self, events_ids: set[str]) -> None:
        super().__init__()
        self.events_ids = events_ids
        self.found = False

    def visit_field(self, node: ast.Field) -> None:
        if _field_is_events_timestamp(node, self.events_ids):
            self.found = True

    def visit_select_query(self, node: ast.SelectQuery) -> None:
        # A timestamp bound inside a nested SELECT doesn't constrain this one — don't descend.
        pass


def _field_is_events_timestamp(expr: ast.Field, events_ids: set[str]) -> bool:
    """``True`` iff ``expr`` references the events table's ``timestamp`` column. Uses type info
    when resolved; otherwise falls back to the chain, attributing a qualified ``x.timestamp`` only
    when ``x`` names the events table (so a JOINed table's ``timestamp`` filter doesn't count)."""
    if not expr.chain:
        return False

    resolved = resolves_to_events_column(expr, "timestamp")
    if resolved is not None:
        return resolved

    # No type info — fall back to the chain. Bare ``timestamp`` counts; a qualified ``x.timestamp``
    # counts only when ``x`` is an events-table identifier in this SELECT.
    if expr.chain[-1] != "timestamp":
        return False
    return len(expr.chain) == 1 or expr.chain[-2] in events_ids
