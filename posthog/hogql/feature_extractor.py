"""Extract product-attribution features from a HogQL select query.

Used by ``HogQLQueryExecutor`` to tag ClickHouse queries with the set of
PostHog tables and well-known event filters they reference. The tags feed
``add_fallback_query_tags`` so HogQL queries (which otherwise carry no
product information) can be attributed to the right product surface — LLM
analytics, error tracking, web analytics, replay, etc.
"""

from posthog.hogql import ast
from posthog.hogql.visitor import TraversingVisitor

# Last-identifier match for the events ``event`` column when type info isn't
# available — covers ``event``, ``events.event``, ``e.event``, etc.
_EVENT_FIELD_NAMES: frozenset[str] = frozenset({"event"})

# Known event names worth surfacing for product attribution. Restricted to
# the set used by add_fallback_query_tags — over-collecting bloats query_log
# without buying anything.
_INTERESTING_EVENT_NAMES: frozenset[str] = frozenset(
    {
        "$ai_generation",
        "$ai_span",
        "$ai_trace",
        "$ai_embedding",
        "$ai_metric",
        "$ai_feedback",
        "$exception",
        "$web_vitals",
        "$feature_flag_called",
    }
)


class HogQLFeatureExtractor(TraversingVisitor):
    """Walk a HogQL ``SelectQuery``/``SelectSetQuery`` and record:

    * ``tables``: identifiers that appear directly as a ``FROM``/``JOIN`` source.
    * ``events``: string literals compared to an ``event`` field on the events
      table via ``=`` / ``IN``, restricted to the curated
      ``_INTERESTING_EVENT_NAMES`` set.

    Works on either a raw parsed AST or a resolved AST. When type info is
    available (post-Resolver), the event-field check uses it for accuracy;
    otherwise it falls back to a last-identifier chain match.
    """

    def __init__(self) -> None:
        super().__init__()
        self.tables: set[str] = set()
        self.events: set[str] = set()

    def visit_join_expr(self, node: ast.JoinExpr) -> None:
        if isinstance(node.table, ast.Field) and node.table.chain:
            head = node.table.chain[0]
            if isinstance(head, str):
                self.tables.add(head)
        super().visit_join_expr(node)

    def visit_compare_operation(self, node: ast.CompareOperation) -> None:
        if node.op in (ast.CompareOperationOp.Eq, ast.CompareOperationOp.In):
            self._collect_event_names(node.left, node.right)
            # Also handle constant-on-the-left (`'$exception' = event`)
            self._collect_event_names(node.right, node.left)
        super().visit_compare_operation(node)

    def _collect_event_names(self, field_side: ast.Expr, value_side: ast.Expr) -> None:
        if not _looks_like_event_field(field_side):
            return
        for value in _iter_string_constants(value_side):
            if value in _INTERESTING_EVENT_NAMES:
                self.events.add(value)


def _looks_like_event_field(expr: ast.Expr) -> bool:
    """True if ``expr`` references the ``event`` column on the events table.

    Mirrors ``is_events_only_field`` in the session where-clause extractor:
    when the AST has been resolved we walk the type chain to confirm the
    field is ``event`` on ``EventsTable`` exactly. When types aren't
    populated (e.g. pre-resolution caller, or a partially-typed branch) we
    fall back to a last-identifier chain match — looser, but still useful.
    """
    if isinstance(expr, ast.Alias):
        expr = expr.expr
    if not isinstance(expr, ast.Field) or not expr.chain:
        return False

    if (events_field := _is_event_field_via_types(expr)) is not None:
        return events_field

    last = expr.chain[-1]
    return isinstance(last, str) and last in _EVENT_FIELD_NAMES


def _is_event_field_via_types(field: ast.Field) -> bool | None:
    """Return True/False from the type system, or None if types aren't
    populated and the caller should fall back to chain matching."""
    from posthog.hogql.database.schema.events import EventsTable

    type_ = field.type
    if type_ is None:
        return None

    if isinstance(type_, ast.PropertyType):
        type_ = type_.field_type
    if isinstance(type_, ast.FieldAliasType):
        type_ = type_.type
    if not isinstance(type_, ast.FieldType):
        return None

    if type_.name != "event":
        return False

    table_type = type_.table_type
    while isinstance(table_type, (ast.TableAliasType, ast.ColumnAliasedTableType)):
        table_type = table_type.table_type
    if isinstance(table_type, ast.TableType):
        return isinstance(table_type.table, EventsTable)
    return False


def _iter_string_constants(expr: ast.Expr):
    """Yield string literals from a constant, tuple, or array — covers
    ``event = 'X'`` and ``event IN ('X', 'Y')``."""
    if isinstance(expr, ast.Alias):
        expr = expr.expr
    if isinstance(expr, ast.Constant):
        if isinstance(expr.value, str):
            yield expr.value
        return
    if isinstance(expr, (ast.Tuple, ast.Array)):
        for sub in expr.exprs:
            yield from _iter_string_constants(sub)


def extract_hogql_features(
    query: ast.SelectQuery | ast.SelectSetQuery | None,
) -> tuple[list[str], list[str]]:
    """Convenience wrapper around ``HogQLFeatureExtractor``.

    Returns ``(tables, events)`` as sorted lists so the resulting query tag is
    deterministic across runs (helps log readability and snapshot tests).
    Returns empty lists if ``query`` is ``None``.
    """
    if query is None:
        return [], []
    visitor = HogQLFeatureExtractor()
    visitor.visit(query)
    return sorted(visitor.tables), sorted(visitor.events)
