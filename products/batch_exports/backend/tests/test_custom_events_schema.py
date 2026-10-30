from typing import cast

from posthog.test.base import BaseTest, materialized
from unittest.mock import patch

from django.test import override_settings

from parameterized import parameterized

from posthog.hogql import ast
from posthog.hogql.property_access_types import RestrictedProperty

from posthog.models import PropertyDefinition

from products.batch_exports.backend.custom_events_schema import parse_events_hogql_query, serialize_events_query_schema
from products.batch_exports.backend.facade.contracts import UnsupportedHogQLQueryError


def prepare_query(query: str, team_id: int) -> ast.SelectQuery:
    """Parse and resolve a HogQL query string into a prepared AST."""
    return cast(ast.SelectQuery, parse_events_hogql_query(query, team_id=team_id, user=None))


class TestSerializeEventsQuerySchema(BaseTest):
    @override_settings(CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA=False)
    def test_resaving_legacy_query_preserves_types_and_column_names(self):
        PropertyDefinition.objects.create(
            team=self.team, name="amount", type=PropertyDefinition.Type.EVENT, property_type="Numeric"
        )
        query = "SELECT round(e.properties.amount) AS rounded, lower(e.event) FROM events AS e"

        schema = serialize_events_query_schema(self.team.pk, None, prepare_query(query, self.team.pk))
        resaved = serialize_events_query_schema(self.team.pk, None, prepare_query(query, self.team.pk))

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

        result = serialize_events_query_schema(self.team.pk, None, prepared)

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

        result = serialize_events_query_schema(self.team.pk, None, prepared)

        assert len(result["fields"]) == 1
        field = result["fields"][0]
        assert field["expression"] == expected_expression
        assert field["alias"] == expected_alias

    def test_serialize_hogql_query_escapes_injected_alias(self):
        """An alias containing SQL injection attempts is escaped with backticks."""
        query = "SELECT uuid AS `x, (SELECT query FROM another_table LIMIT 100) AS leaked` FROM events"
        prepared = prepare_query(query, self.team.pk)

        result = serialize_events_query_schema(self.team.pk, None, prepared)

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

        schema = serialize_events_query_schema(self.team.pk, None, prepare_query(query, self.team.pk))

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
                "products.access_control.backend.facade.api.get_restricted_properties_with_group_type_index_for_team",
                return_value=restrictions,
            ),
            materialized("events", "$browser"),
        ):
            query = prepare_query("SELECT properties.$browser AS browser FROM events", self.team.pk)

            schema = serialize_events_query_schema(self.team.pk, self.user, query)

        expression = schema["fields"][0]["expression"]
        if restricted:
            assert "hogql_query" not in schema
            assert "mat_" not in expression
        else:
            assert "mat_$browser" in expression

    @override_settings(CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA=True)
    @patch("products.access_control.backend.facade.api.get_restricted_properties_with_group_type_index_for_team")
    @patch("posthog.models.event.new_events_schema.use_new_events_schema", return_value=True)
    def test_restricted_property_query_is_not_recompiled_without_user(
        self, _use_new_events_schema, get_restricted_properties
    ):
        get_restricted_properties.return_value = {
            RestrictedProperty(name="secret", property_type=PropertyDefinition.Type.EVENT)
        }
        query = prepare_query("SELECT properties.secret AS secret FROM events", self.team.pk)

        schema = serialize_events_query_schema(self.team.pk, self.user, query)

        assert schema["fields"] == [{"expression": "NULL", "alias": "secret"}]
        assert "hogql_query" not in schema

        with self.assertRaises(UnsupportedHogQLQueryError):
            serialize_events_query_schema(
                self.team.pk, self.user, prepare_query("SELECT properties FROM events", self.team.pk)
            )

    @parameterized.expand(
        [
            ("restricted", "SELECT properties.`$feature/secret` AS flag FROM events", "NULL"),
            ("visible", "SELECT properties.`$feature/checkout` AS flag FROM events", "JSONExtractRaw("),
        ]
    )
    @override_settings(CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA=True)
    @patch("products.access_control.backend.facade.api.get_restricted_properties_with_group_type_index_for_team")
    @patch("posthog.models.event.new_events_schema.use_new_events_schema", return_value=True)
    def test_native_export_hides_a_restricted_flag(
        self, _name: str, query: str, expected: str, _use_new_events_schema, get_restricted_properties
    ):
        get_restricted_properties.return_value = {
            RestrictedProperty(name="$feature/secret", property_type=PropertyDefinition.Type.EVENT)
        }

        schema = serialize_events_query_schema(self.team.pk, self.user, prepare_query(query, self.team.pk))

        expression = schema["fields"][0]["expression"]
        assert expression == expected if expected == "NULL" else expected in expression, expression

    @override_settings(CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA=True)
    @patch("posthog.models.event.new_events_schema.use_new_events_schema", return_value=True)
    def test_native_export_names_a_bare_flag_column(self, _use_new_events_schema):

        schema = serialize_events_query_schema(
            self.team.pk, self.user, prepare_query("SELECT properties.`$feature/checkout` FROM events", self.team.pk)
        )

        field = schema["fields"][0]
        assert field["alias"] == "`$feature/checkout`", field
        assert "JSONExtractRaw(" in field["expression"], field
