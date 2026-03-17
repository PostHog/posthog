"""AST rewriter that translates queries written against `ai_events` columns to work with the `events` table.

This is the reverse of `AiPropertyRewriter`. When a query's date range extends beyond the
`ai_events` 30-day TTL, the query must target the `events` table instead. This rewriter:

1. Rewrites dedicated column references (e.g. `trace_id`) to property access
   (e.g. `properties.$ai_trace_id`) so they resolve against the `events` table.
2. Swaps the `ai_events` table prefix to `events` in table-qualified field chains.
3. Replaces the FROM clause from `ai_events` to `events`.

The rewriter is scope-aware: it only rewrites fields within SELECT queries that have
`FROM ai_events`. Fields in outer queries (referencing subquery aliases) are left unchanged.
"""

from posthog.hogql import ast
from posthog.hogql.visitor import CloningVisitor

from posthog.hogql_queries.ai.ai_property_rewriter import AI_PROPERTY_TO_COLUMN

# Invert AI_PROPERTY_TO_COLUMN: column_name -> property_name
AI_COLUMN_TO_PROPERTY: dict[str, str] = {col: prop for prop, col in AI_PROPERTY_TO_COLUMN.items()}


class AiColumnToPropertyRewriter(CloningVisitor):
    """Rewrites `ai_events` column references to `events` property references.

    Scope-aware: only rewrites fields within SELECT queries that have `FROM ai_events`.
    Fields in outer queries (referencing subquery aliases) are left unchanged.

    When `force_rewrite=True`, always rewrites regardless of scope (for standalone expressions
    like placeholders that will be substituted into ai_events-scoped queries).
    """

    def __init__(self, force_rewrite: bool = False):
        super().__init__()
        self._in_ai_events_scope = force_rewrite

    def visit_select_query(self, node: ast.SelectQuery) -> ast.SelectQuery:
        was_in_scope = self._in_ai_events_scope
        if _has_ai_events_from(node):
            self._in_ai_events_scope = True
        result = super().visit_select_query(node)
        self._in_ai_events_scope = was_in_scope
        return result

    def visit_field(self, node: ast.Field) -> ast.Expr:
        if not self._in_ai_events_scope:
            return super().visit_field(node)

        chain = node.chain

        # Table-qualified: ["ai_events", "column_name", ...]
        if len(chain) >= 2 and chain[0] == "ai_events":
            col_name = chain[1]
            if isinstance(col_name, str) and col_name in AI_COLUMN_TO_PROPERTY:
                prop_name = AI_COLUMN_TO_PROPERTY[col_name]
                new_chain: list[str | int] = ["events", "properties", prop_name, *chain[2:]]
                return _maybe_wrap_boolean(prop_name, new_chain)
            # Native column (timestamp, event, distinct_id, etc.) — just swap table prefix
            return ast.Field(chain=["events", *chain[1:]])

        # Bare column: ["column_name", ...]
        if len(chain) >= 1:
            col_name = chain[0]
            if isinstance(col_name, str) and col_name in AI_COLUMN_TO_PROPERTY:
                prop_name = AI_COLUMN_TO_PROPERTY[col_name]
                new_chain = ["properties", prop_name, *chain[1:]]
                return _maybe_wrap_boolean(prop_name, new_chain)

        return super().visit_field(node)

    def visit_join_expr(self, node: ast.JoinExpr) -> ast.JoinExpr:
        new_node = super().visit_join_expr(node)
        # Swap FROM ai_events -> FROM events
        if isinstance(new_node.table, ast.Field) and new_node.table.chain == ["ai_events"]:
            new_node.table = ast.Field(chain=["events"])
        return new_node


def _has_ai_events_from(query: ast.SelectQuery) -> bool:
    """Check if a SELECT query has FROM ai_events."""
    return (
        query.select_from is not None
        and isinstance(query.select_from.table, ast.Field)
        and query.select_from.table.chain == ["ai_events"]
    )


def _maybe_wrap_boolean(prop_name: str, chain: list[str | int]) -> ast.Expr:
    """Wrap boolean properties to preserve UInt8 semantics used in trace runner queries."""
    if prop_name == "$ai_is_error":
        return ast.Call(
            name="if",
            args=[
                ast.CompareOperation(
                    op=ast.CompareOperationOp.Eq,
                    left=ast.Field(chain=chain),
                    right=ast.Constant(value="true"),
                ),
                ast.Constant(value=1),
                ast.Constant(value=0),
            ],
        )
    return ast.Field(chain=chain)


def rewrite_query_for_events_table(query: ast.SelectQuery | ast.SelectSetQuery) -> ast.SelectQuery | ast.SelectSetQuery:
    """Rewrite a query written against `ai_events` to target the `events` table."""
    return AiColumnToPropertyRewriter(force_rewrite=False).visit(query)


def rewrite_expr_for_events_table(expr: ast.Expr) -> ast.Expr:
    """Rewrite a standalone expression (e.g. a placeholder value) for the events table."""
    return AiColumnToPropertyRewriter(force_rewrite=True).visit(expr)
