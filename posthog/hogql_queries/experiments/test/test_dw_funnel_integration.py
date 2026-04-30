"""
Integration tests for datawarehouse funnel metrics.

Tests DW funnel validation with comprehensive edge cases.
Query builder tests are in test_funnel_validation.py.
"""

import pytest

from rest_framework.exceptions import ValidationError

from posthog.schema import EventsNode, ExperimentDataWarehouseNode, ExperimentFunnelMetric, StepOrderValue

from posthog.hogql_queries.experiments.funnel_validation import FunnelDWValidator


class TestFunnelDWValidation:
    """Test FunnelDWValidator validation logic."""

    def test_valid_funnel_with_dw_step(self):
        """Valid funnel with DW step should not raise."""
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

        FunnelDWValidator.validate_funnel_metric(metric)

    def test_valid_funnel_without_dw_steps(self):
        """Funnel without DW steps should skip validation."""
        metric = ExperimentFunnelMetric(
            series=[
                EventsNode(event="pageview"),
                EventsNode(event="purchase"),
            ],
            funnel_order_type=StepOrderValue.ORDERED,
        )

        FunnelDWValidator.validate_funnel_metric(metric)

    @pytest.mark.parametrize(
        "missing_field,expected_error",
        [
            ("table_name", "table_name is required"),
            ("timestamp_field", "timestamp_field is required"),
            ("data_warehouse_join_key", "data_warehouse_join_key is required"),
            ("events_join_key", "events_join_key is required"),
        ],
    )
    def test_missing_required_field(self, missing_field, expected_error):
        """Missing required field should raise ValidationError with appropriate message."""
        fields = {
            "table_name": "revenue",
            "timestamp_field": "purchase_date",
            "data_warehouse_join_key": "user_id",
            "events_join_key": "properties.$user_id",
        }
        # Blank out the missing field
        fields[missing_field] = ""

        metric = ExperimentFunnelMetric(
            series=[
                EventsNode(event="pageview"),
                ExperimentDataWarehouseNode(**fields),
            ],
            funnel_order_type=StepOrderValue.ORDERED,
        )

        with pytest.raises(ValidationError) as exc_info:
            FunnelDWValidator.validate_funnel_metric(metric)
        assert expected_error in str(exc_info.value)

    def test_inconsistent_join_keys(self):
        """Different events_join_keys should raise ValueError."""
        metric = ExperimentFunnelMetric(
            series=[
                EventsNode(event="pageview"),
                ExperimentDataWarehouseNode(
                    table_name="revenue",
                    timestamp_field="purchase_date",
                    data_warehouse_join_key="user_id",
                    events_join_key="properties.$user_id",  # First join key
                ),
                ExperimentDataWarehouseNode(
                    table_name="subscriptions",
                    timestamp_field="subscribed_at",
                    data_warehouse_join_key="customer_email",
                    events_join_key="properties.$email",  # Different join key
                ),
            ],
            funnel_order_type=StepOrderValue.ORDERED,
        )

        with pytest.raises(ValidationError) as exc_info:
            FunnelDWValidator.validate_funnel_metric(metric)
        assert "same join key" in str(exc_info.value)

    def test_too_many_dw_steps(self):
        """Exceeding MAX_DW_STEPS should raise ValidationError."""
        dw_steps = [
            ExperimentDataWarehouseNode(
                table_name=f"table_{i}",
                timestamp_field="ts",
                data_warehouse_join_key="user_id",
                events_join_key="properties.$user_id",
            )
            for i in range(FunnelDWValidator.MAX_DW_STEPS + 1)
        ]

        metric = ExperimentFunnelMetric(
            series=dw_steps,
            funnel_order_type=StepOrderValue.ORDERED,
        )

        with pytest.raises(ValidationError) as exc_info:
            FunnelDWValidator.validate_funnel_metric(metric)
        assert "Too many datawarehouse steps" in str(exc_info.value)

    def test_too_many_distinct_tables(self):
        """Exceeding MAX_DISTINCT_DW_TABLES should raise ValidationError."""
        dw_steps = [
            ExperimentDataWarehouseNode(
                table_name=f"table_{i}",  # Different table for each step
                timestamp_field="ts",
                data_warehouse_join_key="user_id",
                events_join_key="properties.$user_id",
            )
            for i in range(FunnelDWValidator.MAX_DISTINCT_DW_TABLES + 1)
        ]

        metric = ExperimentFunnelMetric(
            series=dw_steps,
            funnel_order_type=StepOrderValue.ORDERED,
        )

        with pytest.raises(ValidationError) as exc_info:
            FunnelDWValidator.validate_funnel_metric(metric)
        assert "Too many distinct datawarehouse tables" in str(exc_info.value)

    def test_multiple_errors_reported(self):
        """Multiple missing fields should all be reported in error message."""
        metric = ExperimentFunnelMetric(
            series=[
                EventsNode(event="pageview"),
                ExperimentDataWarehouseNode(
                    table_name="",  # Missing
                    timestamp_field="",  # Missing
                    data_warehouse_join_key="",  # Missing
                    events_join_key="",  # Missing
                ),
            ],
            funnel_order_type=StepOrderValue.ORDERED,
        )

        with pytest.raises(ValidationError) as exc_info:
            FunnelDWValidator.validate_funnel_metric(metric)

        error_msg = str(exc_info.value)
        assert "table_name is required" in error_msg
        assert "timestamp_field is required" in error_msg
        assert "data_warehouse_join_key is required" in error_msg
        assert "events_join_key is required" in error_msg
