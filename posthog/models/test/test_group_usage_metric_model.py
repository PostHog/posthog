from posthog.test.base import BaseTest

from posthog.hogql import ast

from posthog.models import GroupUsageMetric


class GroupUsageMetricTestCase(BaseTest):
    def test_bytecode_generation(self):
        metric = GroupUsageMetric.objects.create(
            team=self.team,
            group_type_index=0,
            name="test",
            filters={
                "events": [
                    {"id": "$pageview", "name": "$pageview", "type": "events", "order": 0},
                ],
                "actions": [],
                "filter_test_accounts": True,
            },
        )

        self.assertIsNotNone(metric.bytecode)
        self.assertIsNone(metric.bytecode_error)
        assert isinstance(metric.bytecode, list)  # Using assert to help mypy with the types
        self.assertGreater(len(metric.bytecode), 0)

    def test_data_warehouse_source_detection(self):
        events_metric = GroupUsageMetric.objects.create(
            team=self.team,
            group_type_index=0,
            name="events_metric",
            filters={"events": [{"id": "$pageview", "type": "events", "order": 0}]},
        )
        dw_metric = GroupUsageMetric.objects.create(
            team=self.team,
            group_type_index=0,
            name="dw_metric",
            filters={
                "source": "data_warehouse",
                "table_name": "stripe_charges",
                "timestamp_field": "created",
                "key_field": "customer_id",
            },
        )

        assert events_metric.is_data_warehouse is False
        assert events_metric.source == GroupUsageMetric.Source.EVENTS
        assert dw_metric.is_data_warehouse is True
        assert dw_metric.source == GroupUsageMetric.Source.DATA_WAREHOUSE

    def test_data_warehouse_get_expr_returns_constant_true(self):
        dw_metric = GroupUsageMetric.objects.create(
            team=self.team,
            group_type_index=0,
            name="dw_metric",
            filters={
                "source": "data_warehouse",
                "table_name": "stripe_charges",
                "timestamp_field": "created",
                "key_field": "customer_id",
            },
        )

        assert dw_metric.get_expr() == ast.Constant(value=True)
