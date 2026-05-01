"""
Integration tests for FunnelStepBuilder with ExperimentQueryBuilder.

Tests that FunnelStepBuilder is correctly integrated into the query building pipeline
and produces the expected step columns in generated queries.
"""

from posthog.test.base import BaseTest

from posthog.schema import ActionsNode, EventsNode, ExperimentDataWarehouseNode, ExperimentFunnelMetric

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr

from posthog.hogql_queries.experiments.funnel_step_builder import FunnelStepBuilder


class TestFunnelStepBuilderIntegration(BaseTest):
    """Test FunnelStepBuilder integration with experiment queries."""

    def test_boolean_columns_integration(self):
        """Test that boolean columns are generated correctly for integration."""
        series: list[EventsNode | ActionsNode | ExperimentDataWarehouseNode] = [
            EventsNode(event="pageview"),
            EventsNode(event="purchase"),
        ]

        builder = FunnelStepBuilder(series, self.team)
        exposure_filter = parse_expr("event = '$feature_flag_called'")

        # Generate boolean columns
        columns = builder.build_boolean_columns(exposure_filter)

        # Verify we got the right number of columns
        assert len(columns) == 3  # step_0 + 2 metric steps

        # Verify they're all ast.Alias nodes (ready for SELECT clause)
        for col in columns:
            assert isinstance(col, ast.Alias)
            assert col.alias.startswith("step_")

    def test_constant_columns_integration(self):
        """Test that constant columns are generated correctly for UNION ALL queries."""
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

        # Generate constant columns for exposure step
        exposure_columns = builder.build_constant_columns(active_step_index=0)
        assert len(exposure_columns) == 3
        assert isinstance(exposure_columns[0].expr, ast.Constant)
        assert exposure_columns[0].expr.value == 1  # step_0 active
        assert isinstance(exposure_columns[1].expr, ast.Constant)
        assert exposure_columns[1].expr.value == 0
        assert isinstance(exposure_columns[2].expr, ast.Constant)
        assert exposure_columns[2].expr.value == 0

        # Generate constant columns for DW step (step 2)
        dw_columns = builder.build_constant_columns(active_step_index=2)
        assert len(dw_columns) == 3
        assert isinstance(dw_columns[0].expr, ast.Constant)
        assert dw_columns[0].expr.value == 0
        assert isinstance(dw_columns[1].expr, ast.Constant)
        assert dw_columns[1].expr.value == 0
        assert isinstance(dw_columns[2].expr, ast.Constant)
        assert dw_columns[2].expr.value == 1  # step_2 active

    def test_mixed_node_types_integration(self):
        """Test that FunnelStepBuilder handles mixed EventsNode and ActionsNode."""
        # Create an action first
        action = self.team.action_set.create(name="Test Action")

        series: list[EventsNode | ActionsNode | ExperimentDataWarehouseNode] = [
            EventsNode(event="pageview"),
            ActionsNode(id=action.id),
            EventsNode(event="purchase"),
        ]

        builder = FunnelStepBuilder(series, self.team)
        exposure_filter = parse_expr("event = '$feature_flag_called'")

        # Should be able to generate boolean columns
        columns = builder.build_boolean_columns(exposure_filter)

        # Should have 4 columns: step_0 + 3 metric steps
        assert len(columns) == 4
        assert all(isinstance(col, ast.Alias) for col in columns)
        assert all(col.alias.startswith("step_") for col in columns)

    def test_datawarehouse_node_in_series_accepted_by_schema(self):
        """ExperimentFunnelMetric schema should accept ExperimentDataWarehouseNode in series."""
        # This tests the schema extension we made
        metric = ExperimentFunnelMetric(
            metric_type="funnel",
            series=[
                EventsNode(event="pageview"),
                ExperimentDataWarehouseNode(
                    table_name="revenue",
                    timestamp_field="ds",
                    data_warehouse_join_key="user_id",
                    events_join_key="properties.$user_id",
                ),
            ],
        )

        # Should not raise validation error
        assert len(metric.series) == 2
        assert isinstance(metric.series[0], EventsNode)
        assert isinstance(metric.series[1], ExperimentDataWarehouseNode)

    def test_datawarehouse_node_rejected_in_boolean_mode(self):
        """Verify DW nodes are properly rejected when building boolean columns."""
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

        # Should raise ValueError when trying to build boolean columns with DW node
        with self.assertRaises(ValueError) as context:
            builder.build_boolean_columns(exposure_filter)

        assert "Cannot build boolean filter" in str(context.exception)
        assert "ExperimentDataWarehouseNode" in str(context.exception)
