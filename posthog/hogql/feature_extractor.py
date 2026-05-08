"""Extract product-attribution features from a parsed HogQL select query.

Used by ``HogQLQueryExecutor`` to tag ClickHouse queries with the set of
PostHog tables and well-known event filters they reference. The tags feed
``add_fallback_query_tags`` so HogQL queries (which otherwise carry no
product information) can be attributed to the right product surface — LLM
analytics, error tracking, web analytics, replay, etc.
"""

from posthog.hogql import ast
from posthog.hogql.visitor import TraversingVisitor

# Field chains that name the event-name column on the events table. We match
# against the *last* identifier so aliases like `e.event` work without us
# having to resolve types.
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
    """Walk a parsed HogQL ``SelectQuery``/``SelectSetQuery`` and record:

    * ``tables``: identifiers that appear directly as a ``FROM``/``JOIN`` source.
    * ``events``: string literals compared to an ``event`` field via ``=`` /
      ``IN``, restricted to the curated ``_INTERESTING_EVENT_NAMES`` set.

    The extractor runs *before* type resolution, so it works on the raw chain
    structure rather than resolved table types. Aliased and CTE-referenced
    tables show up as their alias/CTE name, which is intentional — the real
    underlying table is still captured wherever it is first joined.
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
    """``e.event`` / ``events.event`` / ``event`` all qualify."""
    if isinstance(expr, ast.Alias):
        expr = expr.expr
    if not isinstance(expr, ast.Field) or not expr.chain:
        return False
    last = expr.chain[-1]
    return isinstance(last, str) and last in _EVENT_FIELD_NAMES


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
