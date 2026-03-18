import pytest

from posthog.hogql import ast
from posthog.hogql.parser import parse_select

from posthog.hogql_queries.ai.ai_column_rewriter import (
    _BOOLEAN_COLUMNS,
    _NUMERIC_COLUMNS,
    AI_COLUMN_TO_PROPERTY,
    AiColumnToPropertyRewriter,
    rewrite_expr_for_events_table,
    rewrite_query_for_events_table,
)


class TestAiColumnToPropertyRewriter:
    def test_bare_string_column_rewritten(self):
        node = ast.Field(chain=["trace_id"])
        result = AiColumnToPropertyRewriter(force_rewrite=True).visit(node)
        assert isinstance(result, ast.Field)
        assert result.chain == ["properties", "$ai_trace_id"]

    def test_table_qualified_string_column_rewritten(self):
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
        assert isinstance(result.args[1], ast.Constant)
        assert result.args[1].value == 1
        assert isinstance(result.args[2], ast.Constant)
        assert result.args[2].value == 0

    def test_boolean_column_table_qualified_wrapped(self):
        node = ast.Field(chain=["ai_events", "is_error"])
        result = AiColumnToPropertyRewriter(force_rewrite=True).visit(node)
        assert isinstance(result, ast.Call)
        assert result.name == "if"
        assert isinstance(result.args[0], ast.CompareOperation)
        assert isinstance(result.args[0].left, ast.Field)
        assert result.args[0].left.chain == ["events", "properties", "$ai_is_error"]

    @pytest.mark.parametrize(
        "col_name,prop_name",
        [
            ("latency", "$ai_latency"),
            ("input_tokens", "$ai_input_tokens"),
            ("output_tokens", "$ai_output_tokens"),
            ("input_cost_usd", "$ai_input_cost_usd"),
            ("total_cost_usd", "$ai_total_cost_usd"),
            ("time_to_first_token", "$ai_time_to_first_token"),
        ],
    )
    def test_numeric_column_wrapped_in_toFloat(self, col_name, prop_name):
        node = ast.Field(chain=[col_name])
        result = AiColumnToPropertyRewriter(force_rewrite=True).visit(node)
        assert isinstance(result, ast.Call)
        assert result.name == "toFloat"
        assert len(result.args) == 1
        assert isinstance(result.args[0], ast.Field)
        assert result.args[0].chain == ["properties", prop_name]

    def test_numeric_column_table_qualified_wrapped(self):
        node = ast.Field(chain=["ai_events", "latency"])
        result = AiColumnToPropertyRewriter(force_rewrite=True).visit(node)
        assert isinstance(result, ast.Call)
        assert result.name == "toFloat"
        assert isinstance(result.args[0], ast.Field)
        assert result.args[0].chain == ["events", "properties", "$ai_latency"]

    def test_numeric_column_usable_in_sum(self):
        """Verify the rewriter produces sumIf(toFloat(properties.$ai_input_tokens), ...) instead of sumIf(properties.$ai_input_tokens, ...)."""
        query = parse_select("SELECT sumIf(input_tokens, event = '$ai_generation') FROM posthog.ai_events AS ai_events")
        result = rewrite_query_for_events_table(query)
        assert isinstance(result, ast.SelectQuery)
        # The sumIf argument should be toFloat(properties.$ai_input_tokens)
        sum_call = result.select[0]
        assert isinstance(sum_call, ast.Call)
        assert sum_call.name == "sumIf"
        arg = sum_call.args[0]
        assert isinstance(arg, ast.Call)
        assert arg.name == "toFloat"
        assert isinstance(arg.args[0], ast.Field)
        assert arg.args[0].chain == ["properties", "$ai_input_tokens"]

    def test_string_column_not_wrapped(self):
        for col_name in ["trace_id", "session_id", "model", "provider", "span_name"]:
            if col_name not in AI_COLUMN_TO_PROPERTY:
                continue
            node = ast.Field(chain=[col_name])
            result = AiColumnToPropertyRewriter(force_rewrite=True).visit(node)
            assert isinstance(result, ast.Field), f"{col_name} should not be wrapped"

    def test_scope_only_rewrites_in_ai_events_query(self):
        query = parse_select("SELECT trace_id FROM posthog.ai_events AS ai_events")
        result = rewrite_query_for_events_table(query)
        assert isinstance(result, ast.SelectQuery)
        assert isinstance(result.select[0], ast.Field)
        assert result.select[0].chain == ["properties", "$ai_trace_id"]
        assert result.select_from is not None
        assert isinstance(result.select_from.table, ast.Field)
        assert result.select_from.table.chain == ["events"]
        assert result.select_from.alias is None

    def test_scope_skips_non_ai_events_query(self):
        query = parse_select("SELECT trace_id FROM events")
        result = rewrite_query_for_events_table(query)
        assert isinstance(result, ast.SelectQuery)
        assert isinstance(result.select[0], ast.Field)
        assert result.select[0].chain == ["trace_id"]

    def test_subquery_inner_rewritten_outer_preserved(self):
        query = parse_select(
            "SELECT trace_id FROM (SELECT trace_id AS trace_id FROM posthog.ai_events AS ai_events GROUP BY trace_id)"
        )
        result = rewrite_query_for_events_table(query)
        assert isinstance(result, ast.SelectQuery)
        # Outer trace_id references the alias — NOT rewritten
        assert isinstance(result.select[0], ast.Field)
        assert result.select[0].chain == ["trace_id"]
        # Inner query rewritten
        assert result.select_from is not None
        inner = result.select_from.table
        assert isinstance(inner, ast.SelectQuery)
        assert inner.select_from is not None
        assert isinstance(inner.select_from.table, ast.Field)
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
        assert isinstance(result.exprs[0], ast.CompareOperation)
        left0 = result.exprs[0].left
        assert isinstance(left0, ast.Field)
        assert left0.chain == ["properties", "$ai_trace_id"]
        # ai_events.timestamp → events.timestamp
        assert isinstance(result.exprs[1], ast.CompareOperation)
        left1 = result.exprs[1].left
        assert isinstance(left1, ast.Field)
        assert left1.chain == ["events", "timestamp"]

    def test_union_all_both_branches_rewritten(self):
        query = parse_select(
            """
            SELECT trace_id AS trace_id FROM posthog.ai_events AS ai_events
            UNION ALL
            SELECT trace_id AS trace_id FROM posthog.ai_events AS ai_events
            """
        )
        result = rewrite_query_for_events_table(query)
        assert isinstance(result, ast.SelectSetQuery)
        # Both branches should have FROM events
        q1 = result.initial_select_query
        q2 = result.subsequent_select_queries[0].select_query
        assert isinstance(q1, ast.SelectQuery)
        assert isinstance(q2, ast.SelectQuery)
        assert q1.select_from is not None
        assert isinstance(q1.select_from.table, ast.Field)
        assert q1.select_from.table.chain == ["events"]
        assert q2.select_from is not None
        assert isinstance(q2.select_from.table, ast.Field)
        assert q2.select_from.table.chain == ["events"]

    def test_column_to_property_mapping_is_inverse(self):
        from posthog.hogql_queries.ai.ai_property_rewriter import AI_PROPERTY_TO_COLUMN

        for prop, col in AI_PROPERTY_TO_COLUMN.items():
            assert AI_COLUMN_TO_PROPERTY[col] == prop

    def test_all_numeric_columns_are_in_column_mapping(self):
        for col in _NUMERIC_COLUMNS:
            assert col in AI_COLUMN_TO_PROPERTY, f"Numeric column {col} not in AI_COLUMN_TO_PROPERTY"

    def test_all_boolean_columns_are_in_column_mapping(self):
        for col in _BOOLEAN_COLUMNS:
            assert col in AI_COLUMN_TO_PROPERTY, f"Boolean column {col} not in AI_COLUMN_TO_PROPERTY"

    def test_numeric_and_boolean_sets_are_disjoint(self):
        overlap = _NUMERIC_COLUMNS & _BOOLEAN_COLUMNS
        assert not overlap, f"Columns in both numeric and boolean sets: {overlap}"
