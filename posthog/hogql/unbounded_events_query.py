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
        if not self.found and _select_reads_events(node) and not _has_events_timestamp_filter(node):
            self.found = True
        # Keep walking: a bounded outer query can still wrap an unbounded subquery / CTE.
        super().visit_select_query(node)


def _select_reads_events(node: ast.SelectQuery) -> bool:
    """Whether this SELECT's own FROM / JOIN chain reads the events table (ignores subqueries —
    each nested SELECT is scored on its own filters)."""
    join: ast.JoinExpr | None = node.select_from
    while join is not None:
        if _is_events_table(join.table):
            return True
        join = join.next_join
    return False


def _is_events_table(expr: ast.Expr | None) -> bool:
    type_ = getattr(expr, "type", None)
    while isinstance(type_, (ast.TableAliasType, ast.ColumnAliasedTableType)):
        type_ = type_.table_type
    if isinstance(type_, ast.TableType) and isinstance(type_.table, EventsTable):
        return True
    # No type info — fall back to the FROM chain identifier.
    return isinstance(expr, ast.Field) and bool(expr.chain) and expr.chain[0] == "events"


def _has_events_timestamp_filter(node: ast.SelectQuery) -> bool:
    finder = _TimestampFieldFinder()
    for clause in (node.where, node.prewhere, node.having):
        if clause is not None:
            finder.visit(clause)
    return finder.found


class _TimestampFieldFinder(TraversingVisitor):
    def __init__(self) -> None:
        super().__init__()
        self.found = False

    def visit_field(self, node: ast.Field) -> None:
        if _looks_like_events_timestamp(node):
            self.found = True

    def visit_select_query(self, node: ast.SelectQuery) -> None:
        # A timestamp bound inside a nested SELECT doesn't constrain this one — don't descend.
        pass


def _looks_like_events_timestamp(expr: ast.Field) -> bool:
    """``True`` iff ``expr`` references the events table's ``timestamp`` column.
    Mirrors ``_looks_like_event_field`` from the feature extractor."""
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

    # No type info — fall back to last-identifier chain match (covers ``timestamp``, ``e.timestamp``).
    return expr.chain[-1] == "timestamp"
