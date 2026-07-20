"""Detect HogQL queries that read the events table without constraining ``timestamp``.

A ``SELECT ... FROM events`` with no bound on ``timestamp`` in any filter position scans the
whole history of the table. Compiled insight queries (trends, funnels, …) always inject a date
range, so only hand-written HogQL can end up unbounded. This module flags that shape so query
execution can surface it as telemetry (see ``posthog/hogql/query.py``) and we can alert on it.

Works on raw or resolved ASTs: it uses type info when available and falls back to chain matching
otherwise, mirroring ``feature_extractor.py``.
"""

from posthog.hogql import ast
from posthog.hogql.database.schema.events import EventsTable
from posthog.hogql.visitor import TraversingVisitor


def query_reads_events_without_timestamp_filter(node: ast.Expr | None) -> bool:
    """``True`` iff any SELECT in the tree reads the events table directly while none of its own
    filter positions (WHERE / PREWHERE / HAVING) reference the events ``timestamp`` column."""
    if node is None:
        return False
    detector = _UnboundedEventsQueryDetector()
    detector.visit(node)
    return detector.found


class _UnboundedEventsQueryDetector(TraversingVisitor):
    def __init__(self) -> None:
        super().__init__()
        self.found = False

    def visit_select_query(self, node: ast.SelectQuery) -> None:
        if not self.found:
            events_ids = _events_table_identifiers(node)
            if events_ids and not _has_events_timestamp_filter(node, events_ids):
                self.found = True
        # Keep walking: a bounded outer query can still wrap an unbounded subquery / CTE.
        super().visit_select_query(node)


def _events_table_identifiers(node: ast.SelectQuery) -> set[str]:
    """Names that refer to the events table in this SELECT's own FROM / JOIN chain — each events
    source's alias (or ``events`` when unaliased). Empty when the SELECT doesn't read events
    directly (nested subqueries are scored on their own). Also used to attribute an unresolved
    ``x.timestamp`` filter to the right table."""
    ids: set[str] = set()
    join: ast.JoinExpr | None = node.select_from
    while join is not None:
        if _is_events_table(join.table):
            ids.add("events")
            if join.alias:
                ids.add(join.alias)
        join = join.next_join
    return ids


def _is_events_table(expr: ast.Expr | None) -> bool:
    type_ = getattr(expr, "type", None)
    while isinstance(type_, (ast.TableAliasType, ast.ColumnAliasedTableType)):
        type_ = type_.table_type
    if isinstance(type_, ast.TableType) and isinstance(type_.table, EventsTable):
        return True
    # No type info — fall back to the FROM chain identifier.
    return isinstance(expr, ast.Field) and bool(expr.chain) and expr.chain[0] == "events"


def _has_events_timestamp_filter(node: ast.SelectQuery, events_ids: set[str]) -> bool:
    finder = _TimestampFieldFinder(events_ids)
    for clause in (node.where, node.prewhere, node.having):
        if clause is not None:
            finder.visit(clause)
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

    type_ = expr.type
    if isinstance(type_, ast.PropertyType):
        type_ = type_.field_type
    if isinstance(type_, ast.FieldAliasType):
        type_ = type_.type
    if isinstance(type_, ast.FieldType):
        if type_.name != "timestamp":
            return False
        table_type = type_.table_type
        while isinstance(table_type, (ast.TableAliasType, ast.ColumnAliasedTableType)):
            table_type = table_type.table_type
        return isinstance(table_type, ast.TableType) and isinstance(table_type.table, EventsTable)

    # No type info — fall back to the chain. Bare ``timestamp`` counts; a qualified ``x.timestamp``
    # counts only when ``x`` is an events-table identifier in this SELECT.
    if expr.chain[-1] != "timestamp":
        return False
    return len(expr.chain) == 1 or expr.chain[-2] in events_ids
