"""AST rewriter that translates queries written against `ai_events` columns to work with the `events` table.

This is the reverse of `AiPropertyRewriter`. When a query targets the `events` table
as a fallback (e.g. data older than the `ai_events` TTL, or the kill switch is off),
this rewriter:

1. Rewrites dedicated column references (e.g. `trace_id`) to property access
   (e.g. `properties.$ai_trace_id`) so they resolve against the `events` table.
2. Wraps numeric columns in `toFloat()` since JSON-extracted properties are strings
   and aggregate functions like `sum()` require numeric types.
3. Wraps boolean columns (`is_error`) to preserve UInt8 semantics.
4. Swaps the `ai_events` table prefix to `events` in table-qualified field chains.
5. Replaces the FROM clause from `ai_events` to `events`.

The rewriter is scope-aware: it only rewrites fields within SELECT queries that have
`FROM ai_events`. Fields in outer queries (referencing subquery aliases) are left unchanged.
"""

from posthog.hogql import ast
from posthog.hogql.visitor import CloningVisitor

from posthog.hogql_queries.ai.ai_property_rewriter import AI_PROPERTY_TO_COLUMN

# Invert AI_PROPERTY_TO_COLUMN: column_name -> property_name
AI_COLUMN_TO_PROPERTY: dict[str, str] = {col: prop for prop, col in AI_PROPERTY_TO_COLUMN.items()}

# Columns that are Int64/Float64 in ai_events but resolve as strings from events JSON.
# Derived from posthog/models/ai_events/sql.py DDL. Keep in sync when adding columns.
_NUMERIC_COLUMNS: frozenset[str] = frozenset(
    {
        # Token counts (Int64)
        "total_tokens",
        "input_tokens",
        "output_tokens",
        "text_input_tokens",
        "text_output_tokens",
        "image_input_tokens",
        "image_output_tokens",
        "audio_input_tokens",
        "audio_output_tokens",
        "video_input_tokens",
        "video_output_tokens",
        "reasoning_tokens",
        "cache_read_input_tokens",
        "cache_creation_input_tokens",
        "web_search_count",
        # Costs (Float64)
        "input_cost_usd",
        "output_cost_usd",
        "total_cost_usd",
        "request_cost_usd",
        "web_search_cost_usd",
        "audio_cost_usd",
        "image_cost_usd",
        "video_cost_usd",
        # Timing (Float64)
        "latency",
        "time_to_first_token",
    }
)

_BOOLEAN_COLUMNS: frozenset[str] = frozenset({"is_error"})


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
                return _wrap_for_events_type(col_name, prop_name, new_chain)
            # Native column (timestamp, event, distinct_id, etc.) — just swap table prefix
            return ast.Field(chain=["events", *chain[1:]])

        # Bare column: ["column_name", ...]
        if len(chain) >= 1:
            col_name = chain[0]
            if isinstance(col_name, str) and col_name in AI_COLUMN_TO_PROPERTY:
                prop_name = AI_COLUMN_TO_PROPERTY[col_name]
                new_chain = ["properties", prop_name, *chain[1:]]
                return _wrap_for_events_type(col_name, prop_name, new_chain)

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


def _wrap_for_events_type(col_name: str, prop_name: str, chain: list[str | int]) -> ast.Expr:
    """Wrap a rewritten property reference to preserve the ai_events column type.

    On the events table, properties are strings (JSON extraction). Aggregate functions
    like sum() need numeric types, and boolean columns use UInt8 on ai_events.
    """
    if col_name in _BOOLEAN_COLUMNS:
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
    if col_name in _NUMERIC_COLUMNS:
        return ast.Call(name="toFloat", args=[ast.Field(chain=chain)])
    return ast.Field(chain=chain)


def rewrite_query_for_events_table(query: ast.SelectQuery | ast.SelectSetQuery) -> ast.SelectQuery | ast.SelectSetQuery:
    """Rewrite a query written against `ai_events` to target the `events` table."""
    return AiColumnToPropertyRewriter(force_rewrite=False).visit(query)


def rewrite_expr_for_events_table(expr: ast.Expr) -> ast.Expr:
    """Rewrite a standalone expression (e.g. a placeholder value) for the events table."""
    return AiColumnToPropertyRewriter(force_rewrite=True).visit(expr)
