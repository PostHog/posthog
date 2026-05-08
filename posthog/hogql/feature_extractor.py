"""Extract product-attribution features from a HogQL select query.

Feeds ``add_fallback_query_tags`` so HogQL queries can be attributed to a
product surface (LLM analytics, error tracking, web analytics, replay, …)
based on what tables and event filters they reference.
"""

from posthog.hogql import ast
from posthog.hogql.database.schema.events import EventsTable
from posthog.hogql.visitor import TraversingVisitor

# Restricted to the set add_fallback_query_tags actually maps — over-collecting bloats query_log without buying anything.
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
    """Records ``tables`` (FROM/JOIN sources) and ``events`` (event-name literals
    compared to the events ``event`` column). Works on raw or resolved ASTs;
    uses type info when available, falls back to chain matching otherwise."""

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
            for field_side, value_side in ((node.left, node.right), (node.right, node.left)):
                if _looks_like_event_field(field_side):
                    self.events.update(v for v in _iter_string_constants(value_side) if v in _INTERESTING_EVENT_NAMES)
        super().visit_compare_operation(node)


def _looks_like_event_field(expr: ast.Expr) -> bool:
    """``True`` iff ``expr`` references the events table's ``event`` column.
    Mirrors ``is_events_only_field`` from the session where-clause extractor."""
    expr = _strip_aliases(expr)
    if not isinstance(expr, ast.Field) or not expr.chain:
        return False

    type_ = expr.type
    if isinstance(type_, ast.PropertyType):
        type_ = type_.field_type
    if isinstance(type_, ast.FieldAliasType):
        type_ = type_.type
    if isinstance(type_, ast.FieldType):
        if type_.name != "event":
            return False
        table_type = type_.table_type
        while isinstance(table_type, (ast.TableAliasType, ast.ColumnAliasedTableType)):
            table_type = table_type.table_type
        return isinstance(table_type, ast.TableType) and isinstance(table_type.table, EventsTable)

    # No type info — fall back to last-identifier chain match (covers ``event``, ``e.event``, ``events.event``).
    return expr.chain[-1] == "event"


def _strip_aliases(expr: ast.Expr) -> ast.Expr:
    while isinstance(expr, ast.Alias):
        expr = expr.expr
    return expr


def _iter_string_constants(expr: ast.Expr):
    """Yield string literals from a constant, tuple, or array — covers ``= 'X'`` and ``IN ('X', 'Y')``."""
    expr = _strip_aliases(expr)
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
    """Returns ``(tables, events)`` sorted for deterministic tag output."""
    if query is None:
        return [], []
    visitor = HogQLFeatureExtractor()
    visitor.visit(query)
    return sorted(visitor.tables), sorted(visitor.events)
