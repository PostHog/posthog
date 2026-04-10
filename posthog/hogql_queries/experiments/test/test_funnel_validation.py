"""
Tests for FunnelDWValidator.

Created by: Rodrigo
Date: 2026-03-05

NOTE: These tests use unittest.mock to bypass schema validation since
ExperimentFunnelMetric.series doesn't yet support ExperimentDataWarehouseNode
(that schema change happens in Phase 3). The validator logic is tested
independently of schema validation.
"""

from posthog.test.base import BaseTest
from unittest.mock import MagicMock

from parameterized import parameterized
from rest_framework.exceptions import ValidationError

from posthog.schema import EventsNode, ExperimentDataWarehouseNode

from posthog.hogql_queries.experiments.funnel_validation import FunnelDWValidator


def create_mock_metric(series):
    """
    Create mock ExperimentFunnelMetric with given series.

    This bypasses schema validation to allow testing with ExperimentDataWarehouseNode
    before the schema is updated in Phase 3.
    """
    metric = MagicMock()
    metric.series = series
    return metric


class TestFunnelDWValidator(BaseTest):
    """Test FunnelDWValidator for DW funnel configuration validation."""

    def test_validate_required_fields_all_present(self):
        """Valid DW node with all required fields returns no errors."""
        node = ExperimentDataWarehouseNode(
            table_name="revenue_table",
            timestamp_field="purchase_date",
            data_warehouse_join_key="user_id",
            events_join_key="properties.$user_id",
        )

        errors = FunnelDWValidator.validate_required_fields(node, step_index=1)

        assert errors == []

    @parameterized.expand(
        [
            ("table_name", "", 2, "table_name is required", None),
            ("timestamp_field", "", 3, "timestamp_field is required", "time-based filtering"),
            ("data_warehouse_join_key", "", 1, "data_warehouse_join_key is required", "user_id"),
            ("events_join_key", "", 2, "events_join_key is required", "properties.$user_id"),
        ]
    )
    def test_validate_required_fields_missing_single_field(
        self, missing_field, field_value, step_index, error_keyword, additional_check
    ):
        """Missing required field produces clear error."""
        # Build node with all fields valid except the one being tested
        fields = {
            "table_name": "revenue_table",
            "timestamp_field": "purchase_date",
            "data_warehouse_join_key": "user_id",
            "events_join_key": "properties.$user_id",
        }
        fields[missing_field] = field_value
        node = ExperimentDataWarehouseNode(**fields)

        errors = FunnelDWValidator.validate_required_fields(node, step_index=step_index)

        self.assertEqual(len(errors), 1)
        self.assertIn(f"Step {step_index}", errors[0])
        self.assertIn(error_keyword, errors[0])
        if additional_check:
            self.assertIn(additional_check, errors[0])

    def test_validate_required_fields_multiple_missing(self):
        """Multiple missing fields produces multiple errors."""
        node = ExperimentDataWarehouseNode(
            table_name="",  # Missing
            timestamp_field="",  # Missing
            data_warehouse_join_key="user_id",
            events_join_key="properties.$user_id",
        )

        errors = FunnelDWValidator.validate_required_fields(node, step_index=1)

        assert len(errors) == 2
        assert any("table_name" in error for error in errors)
        assert any("timestamp_field" in error for error in errors)

    def test_validate_required_fields_all_missing(self):
        """All missing fields produces all errors."""
        node = ExperimentDataWarehouseNode(
            table_name="",
            timestamp_field="",
            data_warehouse_join_key="",
            events_join_key="",
        )

        errors = FunnelDWValidator.validate_required_fields(node, step_index=5)

        assert len(errors) == 4
        assert all("Step 5" in error for error in errors)

    def test_validate_consistent_join_keys_single_dw_step(self):
        """Single DW step has no consistency issues."""
        metric = create_mock_metric(
            series=[
                EventsNode(event="pageview"),
                ExperimentDataWarehouseNode(
                    table_name="revenue",
                    timestamp_field="ds",
                    data_warehouse_join_key="user_id",
                    events_join_key="properties.$user_id",
                ),
            ]
        )

        error = FunnelDWValidator.validate_consistent_join_keys(metric)

        assert error is None

    def test_validate_consistent_join_keys_no_dw_steps(self):
        """Funnel with no DW steps has no consistency issues."""
        metric = create_mock_metric(
            series=[
                EventsNode(event="pageview"),
                EventsNode(event="purchase"),
            ]
        )

        error = FunnelDWValidator.validate_consistent_join_keys(metric)

        assert error is None

    def test_validate_consistent_join_keys_multiple_same_key(self):
        """Multiple DW steps with same events_join_key is valid."""
        metric = create_mock_metric(
            series=[
                EventsNode(event="pageview"),
                ExperimentDataWarehouseNode(
                    table_name="revenue",
                    timestamp_field="ds",
                    data_warehouse_join_key="user_id",
                    events_join_key="properties.$user_id",
                ),
                ExperimentDataWarehouseNode(
                    table_name="subscriptions",
                    timestamp_field="created_at",
                    data_warehouse_join_key="customer_id",
                    events_join_key="properties.$user_id",  # Same as step 2
                ),
            ]
        )

        error = FunnelDWValidator.validate_consistent_join_keys(metric)

        assert error is None

    def test_validate_consistent_join_keys_different_keys(self):
        """Multiple DW steps with different events_join_key produces error."""
        metric = create_mock_metric(
            series=[
                ExperimentDataWarehouseNode(
                    table_name="revenue",
                    timestamp_field="ds",
                    data_warehouse_join_key="user_id",
                    events_join_key="properties.$user_id",
                ),
                ExperimentDataWarehouseNode(
                    table_name="subscriptions",
                    timestamp_field="created_at",
                    data_warehouse_join_key="email",
                    events_join_key="properties.$email",  # Different!
                ),
            ]
        )

        error = FunnelDWValidator.validate_consistent_join_keys(metric)

        assert error is not None
        assert "join_key_mismatch" in error
        assert "properties.$user_id" in error["join_key_mismatch"]
        assert "properties.$email" in error["join_key_mismatch"]
        assert "same join key" in error["join_key_mismatch"]

    def test_validate_consistent_join_keys_error_shows_step_numbers(self):
        """Join key mismatch error shows which steps use which keys."""
        metric = create_mock_metric(
            series=[
                EventsNode(event="pageview"),  # Step 1
                ExperimentDataWarehouseNode(  # Step 2
                    table_name="revenue",
                    timestamp_field="ds",
                    data_warehouse_join_key="user_id",
                    events_join_key="properties.$user_id",
                ),
                EventsNode(event="add_to_cart"),  # Step 3
                ExperimentDataWarehouseNode(  # Step 4
                    table_name="subscriptions",
                    timestamp_field="created_at",
                    data_warehouse_join_key="email",
                    events_join_key="properties.$email",
                ),
            ]
        )

        error = FunnelDWValidator.validate_consistent_join_keys(metric)

        assert error is not None
        error_msg = error["join_key_mismatch"]
        # Should mention step numbers (2 and 4, the DW steps)
        assert "Step 2" in error_msg
        assert "Step 4" in error_msg

    def test_validate_complexity_limits_within_limits(self):
        """Funnel within complexity limits passes validation."""
        metric = create_mock_metric(
            series=[
                EventsNode(event="pageview"),
                ExperimentDataWarehouseNode(
                    table_name="revenue",
                    timestamp_field="ds",
                    data_warehouse_join_key="user_id",
                    events_join_key="properties.$user_id",
                ),
                ExperimentDataWarehouseNode(
                    table_name="subscriptions",
                    timestamp_field="created_at",
                    data_warehouse_join_key="customer_id",
                    events_join_key="properties.$user_id",
                ),
            ]
        )

        error = FunnelDWValidator.validate_complexity_limits(metric)

        assert error is None

    def test_validate_complexity_limits_too_many_dw_steps(self):
        """More than 3 DW steps produces error."""
        metric = create_mock_metric(
            series=[
                ExperimentDataWarehouseNode(
                    table_name="table1",
                    timestamp_field="ds",
                    data_warehouse_join_key="id",
                    events_join_key="properties.$id",
                ),
                ExperimentDataWarehouseNode(
                    table_name="table2",
                    timestamp_field="ds",
                    data_warehouse_join_key="id",
                    events_join_key="properties.$id",
                ),
                ExperimentDataWarehouseNode(
                    table_name="table1",
                    timestamp_field="ds",
                    data_warehouse_join_key="id",
                    events_join_key="properties.$id",
                ),
                ExperimentDataWarehouseNode(  # 4th DW step
                    table_name="table2",
                    timestamp_field="ds",
                    data_warehouse_join_key="id",
                    events_join_key="properties.$id",
                ),
            ]
        )

        error = FunnelDWValidator.validate_complexity_limits(metric)

        assert error is not None
        assert "complexity_limit" in error
        assert "4" in error["complexity_limit"]  # Number of DW steps
        assert "3" in error["complexity_limit"]  # Maximum
        assert "UNION" in error["complexity_limit"]

    def test_validate_complexity_limits_too_many_tables(self):
        """More than 2 distinct DW tables produces error."""
        metric = create_mock_metric(
            series=[
                ExperimentDataWarehouseNode(
                    table_name="table_a",
                    timestamp_field="ds",
                    data_warehouse_join_key="id",
                    events_join_key="properties.$id",
                ),
                ExperimentDataWarehouseNode(
                    table_name="table_b",
                    timestamp_field="ds",
                    data_warehouse_join_key="id",
                    events_join_key="properties.$id",
                ),
                ExperimentDataWarehouseNode(
                    table_name="table_c",  # 3rd distinct table
                    timestamp_field="ds",
                    data_warehouse_join_key="id",
                    events_join_key="properties.$id",
                ),
            ]
        )

        error = FunnelDWValidator.validate_complexity_limits(metric)

        assert error is not None
        assert "complexity_limit" in error
        assert "3" in error["complexity_limit"]  # Number of distinct tables
        assert "2" in error["complexity_limit"]  # Maximum
        assert "table_a" in error["complexity_limit"]
        assert "table_b" in error["complexity_limit"]
        assert "table_c" in error["complexity_limit"]

    def test_validate_complexity_limits_same_table_multiple_times(self):
        """Same table used multiple times counts as 1 distinct table."""
        metric = create_mock_metric(
            series=[
                ExperimentDataWarehouseNode(
                    table_name="revenue",
                    timestamp_field="ds",
                    data_warehouse_join_key="id",
                    events_join_key="properties.$id",
                ),
                ExperimentDataWarehouseNode(
                    table_name="revenue",  # Same table again
                    timestamp_field="ds",
                    data_warehouse_join_key="id",
                    events_join_key="properties.$id",
                ),
                ExperimentDataWarehouseNode(
                    table_name="revenue",  # And again
                    timestamp_field="ds",
                    data_warehouse_join_key="id",
                    events_join_key="properties.$id",
                ),
            ]
        )

        # Should be valid (3 DW steps but only 1 distinct table)
        error = FunnelDWValidator.validate_complexity_limits(metric)

        assert error is None

    def test_validate_funnel_metric_all_valid(self):
        """Valid DW funnel passes all validations."""
        metric = create_mock_metric(
            series=[
                EventsNode(event="pageview"),
                ExperimentDataWarehouseNode(
                    table_name="revenue",
                    timestamp_field="purchase_date",
                    data_warehouse_join_key="user_id",
                    events_join_key="properties.$user_id",
                ),
            ]
        )

        # Should not raise - valid configuration
        FunnelDWValidator.validate_funnel_metric(metric)

    def test_validate_funnel_metric_missing_fields_raises(self):
        """DW funnel with missing fields raises validation error."""
        metric = create_mock_metric(
            series=[
                ExperimentDataWarehouseNode(
                    table_name="",  # Missing
                    timestamp_field="",  # Missing
                    data_warehouse_join_key="user_id",
                    events_join_key="properties.$user_id",
                ),
            ]
        )

        with self.assertRaises(ValidationError) as context:
            FunnelDWValidator.validate_funnel_metric(metric)

        error_detail = context.exception.detail
        self.assertIn("datawarehouse_configuration", error_detail)

    def test_validate_funnel_metric_join_key_mismatch_raises(self):
        """DW funnel with inconsistent join keys raises validation error."""
        metric = create_mock_metric(
            series=[
                ExperimentDataWarehouseNode(
                    table_name="revenue",
                    timestamp_field="ds",
                    data_warehouse_join_key="user_id",
                    events_join_key="properties.$user_id",
                ),
                ExperimentDataWarehouseNode(
                    table_name="subscriptions",
                    timestamp_field="created_at",
                    data_warehouse_join_key="email",
                    events_join_key="properties.$email",  # Different!
                ),
            ]
        )

        with self.assertRaises(ValidationError) as context:
            FunnelDWValidator.validate_funnel_metric(metric)

        error_detail = context.exception.detail
        self.assertIn("join_key_mismatch", error_detail)

    def test_validate_funnel_metric_complexity_limit_raises(self):
        """DW funnel exceeding complexity limits raises validation error."""
        metric = create_mock_metric(
            series=[
                ExperimentDataWarehouseNode(
                    table_name="table_a",
                    timestamp_field="ds",
                    data_warehouse_join_key="id",
                    events_join_key="properties.$id",
                ),
                ExperimentDataWarehouseNode(
                    table_name="table_b",
                    timestamp_field="ds",
                    data_warehouse_join_key="id",
                    events_join_key="properties.$id",
                ),
                ExperimentDataWarehouseNode(
                    table_name="table_c",  # 3rd table exceeds limit
                    timestamp_field="ds",
                    data_warehouse_join_key="id",
                    events_join_key="properties.$id",
                ),
            ]
        )

        with self.assertRaises(ValidationError) as context:
            FunnelDWValidator.validate_funnel_metric(metric)

        error_detail = context.exception.detail
        self.assertIn("complexity_limit", error_detail)

    def test_validate_funnel_metric_multiple_errors(self):
        """DW funnel with missing fields returns field error first (early return)."""
        metric = create_mock_metric(
            series=[
                ExperimentDataWarehouseNode(
                    table_name="",  # Missing - field error
                    timestamp_field="ds",
                    data_warehouse_join_key="id",
                    events_join_key="properties.$user_id",
                ),
                ExperimentDataWarehouseNode(
                    table_name="table_b",
                    timestamp_field="ds",
                    data_warehouse_join_key="id",
                    events_join_key="properties.$email",  # Different join key - consistency error
                ),
            ]
        )

        with self.assertRaises(ValidationError) as context:
            FunnelDWValidator.validate_funnel_metric(metric)

        error_detail = context.exception.detail
        # Early return on field errors, so join_key_mismatch won't be checked
        self.assertIn("datawarehouse_configuration", error_detail)
        self.assertNotIn("join_key_mismatch", error_detail)

    def test_validate_funnel_metric_events_only_passes(self):
        """Events-only funnel requires no DW validation."""
        metric = create_mock_metric(
            series=[
                EventsNode(event="pageview"),
                EventsNode(event="add_to_cart"),
                EventsNode(event="purchase"),
            ]
        )

        # Should not raise
        FunnelDWValidator.validate_funnel_metric(metric)


class TestFunnelDWValidationIntegration(BaseTest):
    """Integration tests for FunnelDWValidator in query execution context."""

    def test_query_runner_raises_not_implemented_for_dw_funnels(self):
        """Query runner should raise NotImplementedError for DW funnels."""
        from posthog.schema import ExperimentFunnelMetric, ExperimentQuery, StepOrderValue

        from posthog.hogql_queries.experiments.experiment_query_runner import ExperimentQueryRunner

        # Create experiment
        feature_flag = self.team.featureflag_set.create(
            name="Test Feature",
            key="test-feature",
            filters={
                "groups": [{"properties": [], "rollout_percentage": 100}],
                "multivariate": {
                    "variants": [
                        {"key": "control", "rollout_percentage": 50},
                        {"key": "test", "rollout_percentage": 50},
                    ]
                },
            },
        )

        experiment = self.team.experiment_set.create(
            name="Test Experiment",
            feature_flag=feature_flag,
        )

        # Create metric with DW step
        metric = ExperimentFunnelMetric(
            series=[
                EventsNode(event="pageview"),
                ExperimentDataWarehouseNode(
                    table_name="revenue",
                    timestamp_field="purchase_date",
                    data_warehouse_join_key="user_id",
                    events_join_key="properties.$user_id",
                ),
            ],
            funnel_order_type=StepOrderValue.ORDERED,
        )

        query = ExperimentQuery(
            experiment_id=experiment.id,
            metric=metric,
        )

        runner = ExperimentQueryRunner(query=query, team=self.team)

        # Should raise NotImplementedError when trying to calculate
        with self.assertRaises(NotImplementedError) as context:
            runner.calculate()

        assert "UNION ALL pattern" in str(context.exception)
        assert "not yet fully implemented" in str(context.exception)
