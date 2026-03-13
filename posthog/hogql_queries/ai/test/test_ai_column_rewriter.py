from posthog.hogql import ast
from posthog.hogql.parser import parse_select

from posthog.hogql_queries.ai.ai_column_rewriter import (
    AI_COLUMN_TO_PROPERTY,
    AiColumnToPropertyRewriter,
    rewrite_expr_for_events_table,
    rewrite_query_for_events_table,
)


class TestAiColumnToPropertyRewriter:
    def test_bare_column_rewritten(self):
        node = ast.Field(chain=["trace_id"])
        result = AiColumnToPropertyRewriter(force_rewrite=True).visit(node)
        assert isinstance(result, ast.Field)
        assert result.chain == ["properties", "$ai_trace_id"]

    def test_table_qualified_column_rewritten(self):
        node = ast.Field(chain=["ai_events", "trace_id"])
        result = AiColumnToPropertyRewriter(force_rewrite=True).visit(node)
        assert isinstance(result, ast.Field)
        assert result.chain == ["events", "properties", "$ai_trace_id"]

    def test_native_column_keeps_table_prefix_swap(self):
        node = ast.Field(chain=["ai_events", "timestamp"])
        result = AiColumnToPropertyRewriter(force_rewrite=True).visit(node)
        assert isinstance(result, ast.Field)
        assert result.chain == ["events", "timestamp"]

    def test_non_ai_column_unchanged(self):
        node = ast.Field(chain=["event"])
        result = AiColumnToPropertyRewriter(force_rewrite=True).visit(node)
        assert isinstance(result, ast.Field)
        assert result.chain == ["event"]

    def test_boolean_column_wrapped(self):
        node = ast.Field(chain=["is_error"])
        result = AiColumnToPropertyRewriter(force_rewrite=True).visit(node)
        assert isinstance(result, ast.Call)
        assert result.name == "if"
        compare = result.args[0]
        assert isinstance(compare, ast.CompareOperation)
        assert isinstance(compare.left, ast.Field)
        assert compare.left.chain == ["properties", "$ai_is_error"]
        assert isinstance(compare.right, ast.Constant)
        assert compare.right.value == "true"
        assert result.args[1].value == 1
        assert result.args[2].value == 0

    def test_scope_only_rewrites_in_ai_events_query(self):
        query = parse_select("SELECT trace_id FROM ai_events")
        result = rewrite_query_for_events_table(query)
        assert isinstance(result, ast.SelectQuery)
        assert isinstance(result.select[0], ast.Field)
        assert result.select[0].chain == ["properties", "$ai_trace_id"]
        assert result.select_from.table.chain == ["events"]

    def test_scope_skips_non_ai_events_query(self):
        query = parse_select("SELECT trace_id FROM events")
        result = rewrite_query_for_events_table(query)
        assert isinstance(result, ast.SelectQuery)
        assert isinstance(result.select[0], ast.Field)
        assert result.select[0].chain == ["trace_id"]

    def test_subquery_inner_rewritten_outer_preserved(self):
        query = parse_select("SELECT trace_id FROM (SELECT trace_id AS trace_id FROM ai_events GROUP BY trace_id)")
        result = rewrite_query_for_events_table(query)
        assert isinstance(result, ast.SelectQuery)
        # Outer trace_id references the alias — NOT rewritten
        assert isinstance(result.select[0], ast.Field)
        assert result.select[0].chain == ["trace_id"]
        # Inner query rewritten
        inner = result.select_from.table
        assert isinstance(inner, ast.SelectQuery)
        assert inner.select_from.table.chain == ["events"]
        # Inner SELECT: Alias(alias="trace_id", expr=Field(chain=["properties", "$ai_trace_id"]))
        inner_select = inner.select[0]
        assert isinstance(inner_select, ast.Alias)
        assert inner_select.alias == "trace_id"
        assert isinstance(inner_select.expr, ast.Field)
        assert inner_select.expr.chain == ["properties", "$ai_trace_id"]

    def test_force_rewrite_ignores_scope(self):
        node = ast.Field(chain=["trace_id"])
        result = AiColumnToPropertyRewriter(force_rewrite=True).visit(node)
        assert isinstance(result, ast.Field)
        assert result.chain == ["properties", "$ai_trace_id"]

    def test_rewrite_expr_for_events_table(self):
        expr = ast.And(
            exprs=[
                ast.CompareOperation(
                    op=ast.CompareOperationOp.Eq,
                    left=ast.Field(chain=["trace_id"]),
                    right=ast.Constant(value="abc"),
                ),
                ast.CompareOperation(
                    op=ast.CompareOperationOp.GtEq,
                    left=ast.Field(chain=["ai_events", "timestamp"]),
                    right=ast.Constant(value="2025-01-01"),
                ),
            ]
        )
        result = rewrite_expr_for_events_table(expr)
        assert isinstance(result, ast.And)
        # trace_id → properties.$ai_trace_id
        left0 = result.exprs[0].left
        assert isinstance(left0, ast.Field)
        assert left0.chain == ["properties", "$ai_trace_id"]
        # ai_events.timestamp → events.timestamp
        left1 = result.exprs[1].left
        assert isinstance(left1, ast.Field)
        assert left1.chain == ["events", "timestamp"]

    def test_union_all_both_branches_rewritten(self):
        query = parse_select(
            """
            SELECT trace_id AS trace_id FROM ai_events
            UNION ALL
            SELECT trace_id AS trace_id FROM ai_events
            """
        )
        result = rewrite_query_for_events_table(query)
        assert isinstance(result, ast.SelectSetQuery)
        # Both branches should have FROM events
        q1 = result.initial_select_query
        q2 = result.subsequent_select_queries[0].select_query
        assert q1.select_from.table.chain == ["events"]
        assert q2.select_from.table.chain == ["events"]

    def test_column_to_property_mapping_is_inverse(self):
        from posthog.hogql_queries.ai.ai_property_rewriter import AI_PROPERTY_TO_COLUMN

        for prop, col in AI_PROPERTY_TO_COLUMN.items():
            assert AI_COLUMN_TO_PROPERTY[col] == prop
