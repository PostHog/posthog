from types import SimpleNamespace
from typing import cast

from posthog.test.base import BaseTest, materialized
from unittest.mock import patch

from django.test import override_settings

from parameterized import parameterized
from rest_framework import serializers

from posthog.hogql import ast
from posthog.hogql.property_access_types import RestrictedProperty

from posthog.api.scoped_related_fields import TeamScopedPrimaryKeyRelatedField
from posthog.models import Organization, PropertyDefinition, Team
from posthog.models.integration import Integration

from products.batch_exports.backend.api.batch_export import (
    BatchExportDestinationSerializer,
    BatchExportSerializer,
    HogQLSelectQueryField,
)


def prepare_query(query: str, team_id: int) -> ast.SelectQuery:
    """Parse and resolve a HogQL query string into a prepared AST."""
    serializer = BatchExportSerializer(context={"team_id": team_id, "request": SimpleNamespace(user=None)})
    field = HogQLSelectQueryField()
    field.bind("hogql_query", serializer)
    return cast(ast.SelectQuery, field.to_internal_value(query))


class TestSerializeHogQLQueryToBatchExportSchema(BaseTest):
    def _make_serializer(self) -> BatchExportSerializer:
        return BatchExportSerializer(context={"team_id": self.team.pk})

    @override_settings(CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA=False)
    def test_resaving_legacy_query_preserves_types_and_column_names(self):
        PropertyDefinition.objects.create(
            team=self.team, name="amount", type=PropertyDefinition.Type.EVENT, property_type="Numeric"
        )
        query = "SELECT round(e.properties.amount) AS rounded, lower(e.event) FROM events AS e"
        serializer = self._make_serializer()

        schema = serializer.serialize_hogql_query_to_batch_export_schema(prepare_query(query, self.team.pk))
        resaved = serializer.serialize_hogql_query_to_batch_export_schema(prepare_query(query, self.team.pk))

        assert schema == resaved
        assert [field["alias"] for field in schema["fields"]] == ["rounded", "`lower(e.event)`"]
        assert schema["fields"][0]["expression"].startswith("round(accurateCastOrNull(")
        assert schema["values"] == {"hogql_val_0": "amount", "hogql_val_1": "Float64"}
        assert "toFloat(" in schema["hogql_query"]

    @parameterized.expand(
        [
            (
                "simple_fields_use_original_name_as_alias",
                "SELECT event, person_id FROM events",
                [
                    {"expression": "events.event", "alias": "event"},
                    {"expression": "events.person_id", "alias": "person_id"},
                ],
                {},
            ),
            (
                "aliased_fields",
                "SELECT event AS my_event, team_id AS my_team FROM events",
                [
                    {"expression": "events.event", "alias": "my_event"},
                    {"expression": "events.team_id", "alias": "my_team"},
                ],
                {},
            ),
            (
                "property_access_populates_values",
                "SELECT properties.$browser AS browser FROM events",
                [
                    {
                        "expression": "replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(events.properties, %(hogql_val_0)s), ''), 'null'), '^\"|\"$', '')",
                        "alias": "browser",
                    },
                ],
                {"hogql_val_0": "$browser"},
            ),
            (
                "mixed_simple_and_property_fields",
                "SELECT event, properties.$browser AS browser, properties.custom AS custom, person_id FROM events",
                [
                    {"expression": "events.event", "alias": "event"},
                    {
                        "expression": "replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(events.properties, %(hogql_val_0)s), ''), 'null'), '^\"|\"$', '')",
                        "alias": "browser",
                    },
                    {
                        "expression": "replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(events.properties, %(hogql_val_1)s), ''), 'null'), '^\"|\"$', '')",
                        "alias": "custom",
                    },
                    {"expression": "events.person_id", "alias": "person_id"},
                ],
                {"hogql_val_0": "$browser", "hogql_val_1": "custom"},
            ),
        ],
    )
    def test_serialize_hogql_query(self, _name, query, expected_fields, expected_values):
        prepared = prepare_query(query, self.team.pk)
        serializer = self._make_serializer()

        result = serializer.serialize_hogql_query_to_batch_export_schema(prepared)

        assert result["fields"] == expected_fields
        assert result["values"] == expected_values
        assert "hogql_query" in result

    @parameterized.expand(
        [
            ("integer", "SELECT 1 FROM events", "1", "`1`"),
            ("string", "SELECT 'hello' FROM events", "%(hogql_val_0)s", "hello"),
            ("float", "SELECT 3.14 FROM events", "3.14", "`3.14`"),
            ("null", "SELECT null FROM events", "NULL", "NULL"),
            ("boolean", "SELECT true FROM events", "1", "`1`"),
        ],
    )
    def test_serialize_hogql_query_with_bare_constant(self, _name, query, expected_expression, expected_alias):
        prepared = prepare_query(query, self.team.pk)
        serializer = self._make_serializer()

        result = serializer.serialize_hogql_query_to_batch_export_schema(prepared)

        assert len(result["fields"]) == 1
        field = result["fields"][0]
        assert field["expression"] == expected_expression
        assert field["alias"] == expected_alias

    def test_serialize_hogql_query_escapes_injected_alias(self):
        """An alias containing SQL injection attempts is escaped with backticks."""
        query = "SELECT uuid AS `x, (SELECT query FROM another_table LIMIT 100) AS leaked` FROM events"
        prepared = prepare_query(query, self.team.pk)
        serializer = self._make_serializer()

        result = serializer.serialize_hogql_query_to_batch_export_schema(prepared)

        assert len(result["fields"]) == 1
        field = result["fields"][0]
        # The alias must be wrapped in backticks, keeping the malicious string as a single identifier
        assert field["alias"] == "`x, (SELECT query FROM another_table LIMIT 100) AS leaked`"
        assert field["expression"] == "events.uuid"

    @override_settings(CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA=True)
    def test_native_query_keeps_property_type_casts(self):
        PropertyDefinition.objects.create(
            team=self.team, name="amount", type=PropertyDefinition.Type.EVENT, property_type="Numeric"
        )
        query = "SELECT e.properties.amount AS amount FROM events AS e"

        schema = self._make_serializer().serialize_hogql_query_to_batch_export_schema(
            prepare_query(query, self.team.pk)
        )

        assert schema["fields"][0]["expression"].startswith("accurateCastOrNull(")
        assert schema["values"]["hogql_val_1"] == "Float64"

    @parameterized.expand([("unrestricted", False), ("restricted", True)])
    @override_settings(CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA=False)
    def test_materialized_columns_are_kept_out_of_a_query_that_cannot_be_recompiled(self, _name: str, restricted: bool):
        restrictions = (
            {RestrictedProperty(name="secret", property_type=PropertyDefinition.Type.EVENT)} if restricted else set()
        )
        with (
            patch(
                "products.batch_exports.backend.api.batch_export."
                "get_restricted_properties_with_group_type_index_for_team",
                return_value=restrictions,
            ),
            materialized("events", "$browser"),
        ):
            query = prepare_query("SELECT properties.$browser AS browser FROM events", self.team.pk)
            serializer = BatchExportSerializer(
                context={"team_id": self.team.pk, "request": SimpleNamespace(user=self.user)}
            )

            schema = serializer.serialize_hogql_query_to_batch_export_schema(query)

        expression = schema["fields"][0]["expression"]
        if restricted:
            assert "hogql_query" not in schema
            assert "mat_" not in expression
        else:
            assert "mat_$browser" in expression

    @override_settings(CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA=True)
    @patch("products.batch_exports.backend.api.batch_export.get_restricted_properties_with_group_type_index_for_team")
    @patch("posthog.models.event.new_events_schema.use_new_events_schema", return_value=True)
    def test_restricted_property_query_is_not_recompiled_without_user(
        self, _use_new_events_schema, get_restricted_properties
    ):
        get_restricted_properties.return_value = {
            RestrictedProperty(name="secret", property_type=PropertyDefinition.Type.EVENT)
        }
        query = prepare_query("SELECT properties.secret AS secret FROM events", self.team.pk)
        serializer = BatchExportSerializer(
            context={"team_id": self.team.pk, "request": SimpleNamespace(user=self.user)}
        )

        schema = serializer.serialize_hogql_query_to_batch_export_schema(query)

        assert schema["fields"] == [{"expression": "NULL", "alias": "secret"}]
        assert "hogql_query" not in schema

        with self.assertRaises(serializers.ValidationError):
            serializer.serialize_hogql_query_to_batch_export_schema(
                prepare_query("SELECT properties FROM events", self.team.pk)
            )


class TestBatchExportDestinationSerializerTeamScoping(BaseTest):
    def _make_integration(self, team: Team) -> Integration:
        return Integration.objects.create(team=team, kind="databricks", integration_id="server")

    @parameterized.expand([("integration",), ("integration_id",)])
    def test_field_rejects_cross_team_integration(self, field_name):
        foreign_org = Organization.objects.create(name="Foreign")
        foreign_team = Team.objects.create(organization=foreign_org, name="Foreign")
        foreign_integration = self._make_integration(foreign_team)

        serializer = BatchExportDestinationSerializer(
            data={
                "type": "Databricks",
                "config": {
                    "http_path": "/sql/1.0/warehouses/abc",
                    "catalog": "main",
                    "schema": "default",
                    "table_name": "events",
                },
                field_name: foreign_integration.pk,
            },
            context={"team_id": self.team.pk},
        )
        assert not serializer.is_valid()
        assert field_name in serializer.errors

    @parameterized.expand([("integration",), ("integration_id",)])
    def test_field_accepts_same_team_integration(self, field_name):
        own_integration = self._make_integration(self.team)

        serializer = BatchExportDestinationSerializer(context={"team_id": self.team.pk})
        # Field-level queryset filter should include same-team integrations.
        field = cast(TeamScopedPrimaryKeyRelatedField, serializer.fields[field_name])
        queryset = field.get_queryset()
        assert queryset is not None and own_integration in queryset
