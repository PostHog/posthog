from posthog.test.base import BaseTest

from posthog.schema import ActionsNode, EventsNode, ExperimentDataWarehouseNode

from posthog.hogql import ast

from posthog.hogql_queries.experiments.metric_source import MetricSourceInfo


class TestMetricSourceInfo(BaseTest):
    def test_from_events_node(self):
        """EventsNode creates correct MetricSourceInfo."""
        source = EventsNode(event="purchase")
        info = MetricSourceInfo.from_source(source, entity_key="person_id")

        assert info.kind == "events"
        assert info.table_name == "events"
        assert info.timestamp_field == "timestamp"
        assert info.has_uuid is True
        assert info.has_session_id is True
        # entity_key should be parsed from the provided string
        assert isinstance(info.entity_key, ast.Field)

    def test_from_actions_node(self):
        """ActionsNode creates correct MetricSourceInfo."""
        source = ActionsNode(id=123)
        info = MetricSourceInfo.from_source(source, entity_key="person_id")

        assert info.kind == "actions"
        assert info.table_name == "events"
        assert info.has_uuid is True
        assert info.has_session_id is True

    def test_from_datawarehouse_node(self):
        """ExperimentDataWarehouseNode creates correct MetricSourceInfo."""
        source = ExperimentDataWarehouseNode(
            table_name="revenue_table",
            timestamp_field="purchase_date",
            data_warehouse_join_key="customer_id",
            events_join_key="properties.$user_id",
        )
        info = MetricSourceInfo.from_source(source, entity_key="person_id")

        assert info.kind == "datawarehouse"
        assert info.table_name == "revenue_table"
        assert info.timestamp_field == "purchase_date"
        assert info.has_uuid is False
        assert info.has_session_id is False
        # entity_key should be parsed from data_warehouse_join_key
        assert isinstance(info.entity_key, ast.Field)

    def test_actions_node_behavior(self):
        """ActionsNode behaves correctly as events table source."""
        source = ActionsNode(id=456)
        info = MetricSourceInfo.from_source(source, entity_key="person_id")

        # Actions use events table, same as events
        assert info.table_name == "events"
        assert info.kind == "actions"
