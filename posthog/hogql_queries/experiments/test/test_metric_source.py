from posthog.test.base import BaseTest

from posthog.schema import ActionsNode, EventsNode, ExperimentDataWarehouseNode

from posthog.hogql import ast

from posthog.hogql_queries.experiments.metric_source import MetricSourceInfo


class TestMetricSourceInfo(BaseTest):
    """Test MetricSourceInfo abstraction for uniform source handling."""

    def test_from_events_node(self):
        """EventsNode creates correct MetricSourceInfo."""
        source = EventsNode(event="purchase")
        info = MetricSourceInfo.from_source(source, entity_key="person_id")

        assert info.kind == "events"
        assert info.table_name == "events"
        assert info.timestamp_field == "timestamp"
        assert info.has_uuid is True
        assert info.has_session_id is True
        # entity_key should be an AST expression for person_id
        assert isinstance(info.entity_key, ast.Field)

    def test_from_actions_node(self):
        """ActionsNode creates correct MetricSourceInfo."""
        source = ActionsNode(id=123)
        info = MetricSourceInfo.from_source(source, entity_key="person_id")

        assert info.kind == "actions"
        assert info.table_name == "events"
        assert info.timestamp_field == "timestamp"
        assert info.has_uuid is True
        assert info.has_session_id is True
        assert isinstance(info.entity_key, ast.Field)

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

    def test_build_select_fields_events_without_string_conversion(self):
        """Events source builds full SELECT fields without toString conversion."""
        source = EventsNode(event="purchase")
        info = MetricSourceInfo.from_source(source, entity_key="person_id")
        fields = info.build_select_fields(convert_entity_id_to_string=False)

        # Verify we got all expected fields
        field_names = [f.alias for f in fields]
        assert field_names == ["entity_id", "timestamp", "uuid", "session_id"]

        # Verify entity_id is NOT wrapped in toString
        entity_id_field = fields[0]
        assert entity_id_field.alias == "entity_id"
        assert isinstance(entity_id_field.expr, ast.Field)  # Direct field, not Call

        # Verify timestamp is correct
        timestamp_field = fields[1]
        assert timestamp_field.alias == "timestamp"
        assert isinstance(timestamp_field.expr, ast.Field)

        # Verify uuid is real field (not placeholder)
        uuid_field = fields[2]
        assert uuid_field.alias == "uuid"
        assert isinstance(uuid_field.expr, ast.Field)

        # Verify session_id is real field (not placeholder)
        session_id_field = fields[3]
        assert session_id_field.alias == "session_id"
        assert isinstance(session_id_field.expr, ast.Field)

    def test_build_select_fields_events_with_string_conversion(self):
        """Events source with toString conversion for UNION compatibility."""
        source = EventsNode(event="purchase")
        info = MetricSourceInfo.from_source(source, entity_key="person_id")
        fields = info.build_select_fields(convert_entity_id_to_string=True)

        # Verify entity_id is wrapped in toString for UNION compatibility
        entity_id_field = fields[0]
        assert entity_id_field.alias == "entity_id"
        assert isinstance(entity_id_field.expr, ast.Call)
        assert entity_id_field.expr.name == "toString"

    def test_build_select_fields_datawarehouse_without_conversion(self):
        """DW source builds SELECT fields with placeholders, no conversion."""
        source = ExperimentDataWarehouseNode(
            table_name="revenue_table",
            timestamp_field="purchase_date",
            data_warehouse_join_key="customer_id",
            events_join_key="properties.$user_id",
        )
        info = MetricSourceInfo.from_source(source, entity_key="person_id")
        fields = info.build_select_fields(convert_entity_id_to_string=False)

        field_names = [f.alias for f in fields]
        assert field_names == ["entity_id", "timestamp", "uuid", "session_id"]

        # Entity ID should be direct field (already string type in DW)
        entity_id_field = fields[0]
        assert isinstance(entity_id_field.expr, ast.Field)

        # Timestamp should use DW table.field format
        timestamp_field = fields[1]
        assert isinstance(timestamp_field.expr, ast.Field)
        # Should reference revenue_table.purchase_date

        # UUID should be placeholder
        uuid_field = fields[2]
        assert isinstance(uuid_field.expr, ast.Call)
        assert uuid_field.expr.name == "toUUID"
        # Verify placeholder value
        uuid_arg = uuid_field.expr.args[0]
        assert isinstance(uuid_arg, ast.Constant)
        assert uuid_arg.value == "00000000-0000-0000-0000-000000000000"

        # Session ID should be empty string placeholder
        session_id_field = fields[3]
        assert isinstance(session_id_field.expr, ast.Constant)
        assert session_id_field.expr.value == ""

    def test_build_select_fields_datawarehouse_with_conversion(self):
        """DW source with toString conversion (redundant but safe)."""
        source = ExperimentDataWarehouseNode(
            table_name="revenue_table",
            timestamp_field="purchase_date",
            data_warehouse_join_key="customer_id",
            events_join_key="properties.$user_id",
        )
        info = MetricSourceInfo.from_source(source, entity_key="person_id")
        fields = info.build_select_fields(convert_entity_id_to_string=True)

        # Entity ID should be wrapped in toString
        entity_id_field = fields[0]
        assert isinstance(entity_id_field.expr, ast.Call)
        assert entity_id_field.expr.name == "toString"

    def test_get_timestamp_field_expr_events(self):
        """Events source returns correct timestamp field expression."""
        source = EventsNode(event="purchase")
        info = MetricSourceInfo.from_source(source, entity_key="person_id")
        timestamp_expr = info.get_timestamp_field_expr()

        assert isinstance(timestamp_expr, ast.Field)
        assert timestamp_expr.chain == ["events", "timestamp"]

    def test_get_timestamp_field_expr_datawarehouse(self):
        """DW source returns correct timestamp field expression."""
        source = ExperimentDataWarehouseNode(
            table_name="revenue_table",
            timestamp_field="purchase_date",
            data_warehouse_join_key="customer_id",
            events_join_key="properties.$user_id",
        )
        info = MetricSourceInfo.from_source(source, entity_key="person_id")
        timestamp_expr = info.get_timestamp_field_expr()

        assert isinstance(timestamp_expr, ast.Field)
        assert timestamp_expr.chain == ["revenue_table", "purchase_date"]

    def test_actions_node_behavior(self):
        """ActionsNode behaves same as EventsNode for field building."""
        source = ActionsNode(id=456)
        info = MetricSourceInfo.from_source(source, entity_key="person_id")
        fields = info.build_select_fields()

        # Should have same structure as EventsNode
        field_names = [f.alias for f in fields]
        assert field_names == ["entity_id", "timestamp", "uuid", "session_id"]

        # All should be real fields (not placeholders)
        uuid_field = next(f for f in fields if f.alias == "uuid")
        assert isinstance(uuid_field.expr, ast.Field)

    def test_multiple_sources_with_conversion(self):
        """Multiple sources can be normalized for UNION compatibility."""
        event_source = EventsNode(event="purchase")
        dw_source = ExperimentDataWarehouseNode(
            table_name="revenue_table",
            timestamp_field="purchase_date",
            data_warehouse_join_key="customer_id",
            events_join_key="properties.$user_id",
        )

        event_info = MetricSourceInfo.from_source(event_source, entity_key="person_id")
        dw_info = MetricSourceInfo.from_source(dw_source, entity_key="person_id")

        # Both with string conversion should have compatible types
        event_fields = event_info.build_select_fields(convert_entity_id_to_string=True)
        dw_fields = dw_info.build_select_fields(convert_entity_id_to_string=True)

        # Same field names
        assert [f.alias for f in event_fields] == [f.alias for f in dw_fields]

        # Both entity_ids wrapped in toString
        assert isinstance(event_fields[0].expr, ast.Call)
        assert event_fields[0].expr.name == "toString"
        assert isinstance(dw_fields[0].expr, ast.Call)
        assert dw_fields[0].expr.name == "toString"

    def test_datawarehouse_with_complex_table_name(self):
        """DW source with schema-qualified table name."""
        source = ExperimentDataWarehouseNode(
            table_name="bigquery.revenue_events",
            timestamp_field="created_at",
            data_warehouse_join_key="user_id",
            events_join_key="properties.$user_id",
        )
        info = MetricSourceInfo.from_source(source, entity_key="person_id")

        assert info.table_name == "bigquery.revenue_events"

        # Timestamp field should use full table name
        timestamp_expr = info.get_timestamp_field_expr()
        assert timestamp_expr.chain == ["bigquery.revenue_events", "created_at"]

    def test_datawarehouse_with_nested_join_key(self):
        """DW source with complex join key expression."""
        source = ExperimentDataWarehouseNode(
            table_name="revenue_table",
            timestamp_field="purchase_date",
            data_warehouse_join_key="customer.external_id",  # Nested field
            events_join_key="properties.$user_id",
        )
        info = MetricSourceInfo.from_source(source, entity_key="person_id")

        # entity_key should be parsed expression
        assert isinstance(info.entity_key, ast.Field)

        # Should build fields correctly
        fields = info.build_select_fields()
        assert len(fields) == 4

    def test_field_order_consistency(self):
        """Field order is consistent across all source types."""
        sources: list[EventsNode | ActionsNode | ExperimentDataWarehouseNode] = [
            EventsNode(event="test"),
            ActionsNode(id=1),
            ExperimentDataWarehouseNode(
                table_name="test_table",
                timestamp_field="ts",
                data_warehouse_join_key="id",
                events_join_key="properties.$id",
            ),
        ]

        expected_order = ["entity_id", "timestamp", "uuid", "session_id"]

        for source in sources:
            info = MetricSourceInfo.from_source(source, entity_key="person_id")
            fields = info.build_select_fields()
            field_names = [f.alias for f in fields]
            assert field_names == expected_order, f"Field order mismatch for {type(source).__name__}"

    def test_placeholder_uuid_value(self):
        """DW placeholder UUID is correct format."""
        source = ExperimentDataWarehouseNode(
            table_name="test_table",
            timestamp_field="ts",
            data_warehouse_join_key="id",
            events_join_key="properties.$id",
        )
        info = MetricSourceInfo.from_source(source, entity_key="person_id")
        fields = info.build_select_fields()

        uuid_field = next(f for f in fields if f.alias == "uuid")
        assert isinstance(uuid_field.expr, ast.Call)
        assert uuid_field.expr.name == "toUUID"

        # Verify it's a valid UUID format (all zeros)
        uuid_arg = uuid_field.expr.args[0]
        assert isinstance(uuid_arg, ast.Constant)
        assert uuid_arg.value == "00000000-0000-0000-0000-000000000000"

    def test_session_id_placeholder_value(self):
        """DW placeholder session_id is empty string."""
        source = ExperimentDataWarehouseNode(
            table_name="test_table",
            timestamp_field="ts",
            data_warehouse_join_key="id",
            events_join_key="properties.$id",
        )
        info = MetricSourceInfo.from_source(source, entity_key="person_id")
        fields = info.build_select_fields()

        session_id_field = next(f for f in fields if f.alias == "session_id")
        assert isinstance(session_id_field.expr, ast.Constant)
        assert session_id_field.expr.value == ""
