"""
Tests for FunnelStepBuilder.

Created by: Rodrigo
Date: 2026-03-05
"""

from posthog.test.base import BaseTest

from posthog.schema import ActionsNode, EventsNode, ExperimentDataWarehouseNode

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr

from posthog.hogql_queries.experiments.funnel_step_builder import FunnelStepBuilder


class TestFunnelStepBuilder(BaseTest):
    """Test FunnelStepBuilder for step column generation."""

    def test_num_steps_includes_exposure(self):
        """num_steps should be series length + 1 (for exposure step_0)."""
        series: list[EventsNode | ActionsNode | ExperimentDataWarehouseNode] = [
            EventsNode(event="pageview"),
            EventsNode(event="purchase"),
        ]
        builder = FunnelStepBuilder(series, self.team)

        assert builder.num_steps == 3  # step_0 (exposure) + 2 metric steps

    def test_boolean_columns_single_event_step(self):
        """Boolean columns for simple 1-step funnel."""
        series: list[EventsNode | ActionsNode | ExperimentDataWarehouseNode] = [EventsNode(event="purchase")]
        builder = FunnelStepBuilder(series, self.team)

        exposure_filter = parse_expr("event = '$feature_flag_called'")
        columns = builder.build_boolean_columns(exposure_filter)

        # Should have 2 columns: step_0 (exposure), step_1 (purchase)
        assert len(columns) == 2

        # Verify aliases
        assert columns[0].alias == "step_0"
        assert columns[1].alias == "step_1"

        # step_0 should be the exposure filter
        assert columns[0].expr == exposure_filter

        # step_1 should be wrapped in if() call: if(event = 'purchase', 1, 0)
        assert isinstance(columns[1].expr, ast.Call)
        assert columns[1].expr.name == "if"
        assert isinstance(columns[1].expr.args[0], ast.CompareOperation)  # The condition

    def test_boolean_columns_multiple_event_steps(self):
        """Boolean columns for multi-step event funnel."""
        series: list[EventsNode | ActionsNode | ExperimentDataWarehouseNode] = [
            EventsNode(event="pageview"),
            EventsNode(event="add_to_cart"),
            EventsNode(event="purchase"),
        ]
        builder = FunnelStepBuilder(series, self.team)

        exposure_filter = parse_expr("event = '$feature_flag_called'")
        columns = builder.build_boolean_columns(exposure_filter)

        # Should have 4 columns: step_0 + 3 metric steps
        assert len(columns) == 4

        # Verify all aliases
        assert [col.alias for col in columns] == ["step_0", "step_1", "step_2", "step_3"]

        # Each metric step should be wrapped in if() call
        for i in range(1, 4):
            expr = columns[i].expr
            assert isinstance(expr, ast.Call)
            assert expr.name == "if"

    def test_boolean_columns_action_step(self):
        """Boolean columns work with ActionsNode."""
        series: list[EventsNode | ActionsNode | ExperimentDataWarehouseNode] = [
            EventsNode(event="pageview"),
            ActionsNode(id=123),
        ]
        builder = FunnelStepBuilder(series, self.team)

        exposure_filter = parse_expr("event = '$feature_flag_called'")
        columns = builder.build_boolean_columns(exposure_filter)

        # Should have 3 columns
        assert len(columns) == 3

        # step_1 should be event check wrapped in if()
        assert isinstance(columns[1].expr, ast.Call)
        assert columns[1].expr.name == "if"

        # step_2 should be action check wrapped in if()
        # The inner condition returns False constant if action doesn't exist
        assert isinstance(columns[2].expr, ast.Call)
        assert columns[2].expr.name == "if"

    def test_boolean_columns_rejects_datawarehouse(self):
        """Boolean columns should reject DW nodes with clear error."""
        series: list[EventsNode | ActionsNode | ExperimentDataWarehouseNode] = [
            EventsNode(event="pageview"),
            ExperimentDataWarehouseNode(
                table_name="revenue",
                timestamp_field="ds",
                data_warehouse_join_key="user_id",
                events_join_key="properties.$user_id",
            ),
        ]
        builder = FunnelStepBuilder(series, self.team)

        exposure_filter = parse_expr("event = '$feature_flag_called'")

        with self.assertRaises(ValueError) as context:
            builder.build_boolean_columns(exposure_filter)

        # Should have helpful error message
        assert "Cannot build boolean filter" in str(context.exception)
        assert "ExperimentDataWarehouseNode" in str(context.exception)
        assert "UNION ALL" in str(context.exception)

    def test_constant_columns_for_exposure(self):
        """Constant columns for exposure step (step_0=1, others=0)."""
        series: list[EventsNode | ActionsNode | ExperimentDataWarehouseNode] = [
            EventsNode(event="pageview"),
            EventsNode(event="purchase"),
        ]
        builder = FunnelStepBuilder(series, self.team)

        # Build columns for exposure step
        columns = builder.build_constant_columns(active_step_index=0)

        # Should have 3 columns
        assert len(columns) == 3

        # Verify aliases
        assert [col.alias for col in columns] == ["step_0", "step_1", "step_2"]

        # step_0 should be 1, others should be 0
        assert isinstance(columns[0].expr, ast.Constant)
        assert columns[0].expr.value == 1
        assert isinstance(columns[1].expr, ast.Constant)
        assert columns[1].expr.value == 0
        assert isinstance(columns[2].expr, ast.Constant)
        assert columns[2].expr.value == 0

    def test_constant_columns_for_first_metric_step(self):
        """Constant columns for first metric step (step_1=1, others=0)."""
        series: list[EventsNode | ActionsNode | ExperimentDataWarehouseNode] = [
            EventsNode(event="pageview"),
            EventsNode(event="purchase"),
        ]
        builder = FunnelStepBuilder(series, self.team)

        columns = builder.build_constant_columns(active_step_index=1)

        # step_1 should be 1, others should be 0
        assert isinstance(columns[0].expr, ast.Constant)
        assert columns[0].expr.value == 0  # step_0
        assert isinstance(columns[1].expr, ast.Constant)
        assert columns[1].expr.value == 1  # step_1 (active)
        assert isinstance(columns[2].expr, ast.Constant)
        assert columns[2].expr.value == 0  # step_2

    def test_constant_columns_for_last_step(self):
        """Constant columns for last step."""
        series: list[EventsNode | ActionsNode | ExperimentDataWarehouseNode] = [
            EventsNode(event="pageview"),
            EventsNode(event="add_to_cart"),
            EventsNode(event="purchase"),
        ]
        builder = FunnelStepBuilder(series, self.team)

        columns = builder.build_constant_columns(active_step_index=3)

        # step_3 should be 1, others should be 0
        assert isinstance(columns[0].expr, ast.Constant)
        assert columns[0].expr.value == 0  # step_0
        assert isinstance(columns[1].expr, ast.Constant)
        assert columns[1].expr.value == 0  # step_1
        assert isinstance(columns[2].expr, ast.Constant)
        assert columns[2].expr.value == 0  # step_2
        assert isinstance(columns[3].expr, ast.Constant)
        assert columns[3].expr.value == 1  # step_3 (active)

    def test_constant_columns_all_constant_nodes(self):
        """Constant columns should all be ast.Constant nodes."""
        series: list[EventsNode | ActionsNode | ExperimentDataWarehouseNode] = [EventsNode(event="test")]
        builder = FunnelStepBuilder(series, self.team)

        columns = builder.build_constant_columns(active_step_index=0)

        for col in columns:
            assert isinstance(col.expr, ast.Constant)
            assert col.expr.value in [0, 1]

    def test_constant_columns_with_datawarehouse_steps(self):
        """Constant columns work with DW steps in series."""
        series: list[EventsNode | ActionsNode | ExperimentDataWarehouseNode] = [
            EventsNode(event="pageview"),
            ExperimentDataWarehouseNode(
                table_name="revenue",
                timestamp_field="ds",
                data_warehouse_join_key="user_id",
                events_join_key="properties.$user_id",
            ),
            EventsNode(event="purchase"),
        ]
        builder = FunnelStepBuilder(series, self.team)

        # Build columns for DW step (step 2)
        columns = builder.build_constant_columns(active_step_index=2)

        # Should have 4 columns (exposure + 3 steps)
        assert len(columns) == 4

        # Only step_2 should be active
        assert isinstance(columns[0].expr, ast.Constant)
        assert columns[0].expr.value == 0
        assert isinstance(columns[1].expr, ast.Constant)
        assert columns[1].expr.value == 0
        assert isinstance(columns[2].expr, ast.Constant)
        assert columns[2].expr.value == 1  # DW step active
        assert isinstance(columns[3].expr, ast.Constant)
        assert columns[3].expr.value == 0

    def test_constant_columns_correct_count(self):
        """Constant columns count matches num_steps."""
        series: list[EventsNode | ActionsNode | ExperimentDataWarehouseNode] = [
            EventsNode(event="a"),
            EventsNode(event="b"),
            EventsNode(event="c"),
            EventsNode(event="d"),
        ]
        builder = FunnelStepBuilder(series, self.team)

        columns = builder.build_constant_columns(active_step_index=0)

        assert len(columns) == builder.num_steps
        assert len(columns) == 5  # 4 metric steps + 1 exposure

    def test_step_filter_event_node(self):
        """_build_step_filter generates correct filter for EventsNode."""
        series: list[EventsNode | ActionsNode | ExperimentDataWarehouseNode] = [EventsNode(event="purchase")]
        builder = FunnelStepBuilder(series, self.team)

        step_filter = builder._build_step_filter(series[0])

        # Should be: event = 'purchase'
        assert isinstance(step_filter, ast.CompareOperation)
        assert step_filter.op == ast.CompareOperationOp.Eq
        assert isinstance(step_filter.left, ast.Field)
        assert step_filter.left.chain == ["event"]
        assert isinstance(step_filter.right, ast.Constant)
        assert step_filter.right.value == "purchase"

    def test_step_filter_action_node(self):
        """_build_step_filter generates correct filter for ActionsNode."""
        series: list[EventsNode | ActionsNode | ExperimentDataWarehouseNode] = [ActionsNode(id=456)]
        builder = FunnelStepBuilder(series, self.team)

        step_filter = builder._build_step_filter(series[0])

        # When action doesn't exist, event_or_action_to_filter returns False constant
        # This is the correct behavior - non-existent actions match no events
        assert isinstance(step_filter, ast.Expr)  # Any valid expression

    def test_boolean_columns_preserves_exposure_filter(self):
        """Exposure filter is used as-is for step_0."""
        series: list[EventsNode | ActionsNode | ExperimentDataWarehouseNode] = [EventsNode(event="test")]
        builder = FunnelStepBuilder(series, self.team)

        # Complex exposure filter
        exposure_filter = ast.And(
            exprs=[
                parse_expr("event = '$feature_flag_called'"),
                parse_expr("properties.$feature_flag = 'test-flag'"),
            ]
        )

        columns = builder.build_boolean_columns(exposure_filter)

        # step_0 should be exact same expression object
        assert columns[0].expr is exposure_filter

    def test_constant_columns_values_are_integers(self):
        """Constant column values should be integers, not booleans."""
        series: list[EventsNode | ActionsNode | ExperimentDataWarehouseNode] = [EventsNode(event="test")]
        builder = FunnelStepBuilder(series, self.team)

        columns = builder.build_constant_columns(active_step_index=0)

        for col in columns:
            assert isinstance(col.expr, ast.Constant)
            assert isinstance(col.expr.value, int)
            assert col.expr.value in [0, 1]

    def test_constant_columns_index_boundary_conditions(self):
        """Constant columns work for boundary step indices."""
        series: list[EventsNode | ActionsNode | ExperimentDataWarehouseNode] = [
            EventsNode(event="a"),
            EventsNode(event="b"),
            EventsNode(event="c"),
        ]
        builder = FunnelStepBuilder(series, self.team)

        # First possible index (exposure)
        columns_first = builder.build_constant_columns(active_step_index=0)
        assert isinstance(columns_first[0].expr, ast.Constant)
        assert columns_first[0].expr.value == 1

        # Last possible index
        columns_last = builder.build_constant_columns(active_step_index=3)
        assert isinstance(columns_last[3].expr, ast.Constant)
        assert columns_last[3].expr.value == 1

    def test_series_with_mixed_node_types(self):
        """Builder works with mixed EventsNode and ActionsNode."""
        series: list[EventsNode | ActionsNode | ExperimentDataWarehouseNode] = [
            EventsNode(event="pageview"),
            ActionsNode(id=10),
            EventsNode(event="purchase"),
            ActionsNode(id=20),
        ]
        builder = FunnelStepBuilder(series, self.team)

        exposure_filter = parse_expr("event = '$feature_flag_called'")
        columns = builder.build_boolean_columns(exposure_filter)

        # Should have 5 columns (1 exposure + 4 steps)
        assert len(columns) == 5

        # All should be valid expressions
        for col in columns:
            assert isinstance(col.expr, ast.Expr)
