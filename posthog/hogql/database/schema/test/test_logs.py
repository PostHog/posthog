"""Unit tests for the logs HogQL schema's Map-typed access path.

These tests intentionally avoid Django and ClickHouse setup. They pin the schema
declarations that make Map subscript printing possible — without them, anyone
querying the `attributes_map_str` column directly would silently fall back to
JSON-extract semantics that don't work on a CH `Map(...)` column.

The user-facing `attributes` field stays `StringJSONDatabaseField` to preserve
existing query-runner behavior; `attributes_map_str` is the hidden Map-typed
field used internally (e.g. by the bot detection helper) for direct Map access.
"""

from posthog.hogql.database.models import StringJSONDatabaseField, StringMapDatabaseField
from posthog.hogql.database.schema.logs import LogsTable
from posthog.hogql.database.schema.spans import TraceSpansTable


class TestLogsTableFieldTypes:
    def test_attributes_stays_json_field(self):
        attrs = LogsTable.model_fields["fields"].default["attributes"]
        assert isinstance(attrs, StringJSONDatabaseField)

    def test_attributes_map_str_is_map_field(self):
        attrs = LogsTable.model_fields["fields"].default["attributes_map_str"]
        assert isinstance(attrs, StringMapDatabaseField)
        assert attrs.hidden is True

    def test_resource_attributes_stays_json_field(self):
        attrs = LogsTable.model_fields["fields"].default["resource_attributes"]
        assert isinstance(attrs, StringJSONDatabaseField)


class TestTraceSpansTableFieldTypes:
    def test_attributes_map_str_is_map_field(self):
        attrs = TraceSpansTable.model_fields["fields"].default["attributes_map_str"]
        assert isinstance(attrs, StringMapDatabaseField)


class TestStringMapDatabaseField:
    def test_get_constant_type_returns_string(self):
        from posthog.hogql.ast import StringType

        field = StringMapDatabaseField(name="attributes_map_str", nullable=False)
        constant = field.get_constant_type()
        assert isinstance(constant, StringType)
        assert constant.nullable is False

    def test_get_constant_type_propagates_nullable(self):
        field = StringMapDatabaseField(name="attributes_map_str", nullable=True)
        assert field.get_constant_type().nullable is True

    def test_default_value_is_empty_string(self):
        field = StringMapDatabaseField(name="attributes_map_str", nullable=False)
        assert field.default_value() == ""
