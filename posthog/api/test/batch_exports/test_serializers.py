from typing import cast

import pytest
from posthog.test.base import BaseTest

from parameterized import parameterized
from rest_framework import serializers as drf_serializers

from posthog.schema import HogQLQueryModifiers, PersonsOnEventsMode

from posthog.hogql import ast
from posthog.hogql.hogql import HogQLContext
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import prepare_ast_for_printing

from posthog.api.scoped_related_fields import TeamScopedPrimaryKeyRelatedField
from posthog.batch_exports.http import (
    _IDENTIFIER_FIELDS_BY_TYPE,
    BatchExportDestinationSerializer,
    BatchExportSerializer,
    _validate_identifier_fields,
)
from posthog.models import Organization, Team
from posthog.models.integration import Integration


def prepare_query(query: str, team_id: int) -> ast.SelectQuery:
    """Parse and resolve a HogQL query string into a prepared AST."""
    parsed = parse_select(query)
    return cast(
        ast.SelectQuery,
        prepare_ast_for_printing(
            parsed,
            context=HogQLContext(
                team_id=team_id,
                enable_select_queries=True,
                modifiers=HogQLQueryModifiers(
                    personsOnEventsMode=PersonsOnEventsMode.PERSON_ID_NO_OVERRIDE_PROPERTIES_ON_EVENTS
                ),
            ),
            dialect="clickhouse",
        ),
    )


class TestSerializeHogQLQueryToBatchExportSchema(BaseTest):
    def _make_serializer(self) -> BatchExportSerializer:
        return BatchExportSerializer(context={"team_id": self.team.pk})

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


# Hand-maintained as the spec of what we *intend* to validate. Acts as an
# independent check on the production dict: the drift test below asserts
# they agree, so accidental additions or deletions fail loudly.
_IDENTIFIER_FIELDS_BY_TYPE_CASES = [
    ("Snowflake", "database"),
    ("Snowflake", "warehouse"),
    ("Snowflake", "schema"),
    ("Snowflake", "table_name"),
    ("Snowflake", "role"),
    ("Databricks", "catalog"),
    ("Databricks", "schema"),
    ("Databricks", "table_name"),
    ("Redshift", "database"),
    ("Redshift", "schema"),
    ("Redshift", "table_name"),
    ("Postgres", "database"),
    ("Postgres", "schema"),
    ("Postgres", "table_name"),
    ("BigQuery", "project_id"),
    ("BigQuery", "dataset_id"),
    ("BigQuery", "table_id"),
]

_FORBIDDEN_PAYLOADS = [
    'events"; DROP TABLE x; --',
    "events`; DROP TABLE x; --",
    "events\x00extra",
    "events\nextra",
    "events\rextra",
]


class TestValidateIdentifierFields:
    def test_spec_matches_production_dict(self):
        # Drift check: if a destination or field is added/removed in http.py's
        # _IDENTIFIER_FIELDS_BY_TYPE, this test fails until the spec above is
        # updated too. Forces a deliberate choice (and PR review) on any
        # change to which fields we validate as identifiers.
        spec_pairs = {(destination, field) for destination, field in _IDENTIFIER_FIELDS_BY_TYPE_CASES}
        prod_pairs = {
            (destination, field) for destination, fields in _IDENTIFIER_FIELDS_BY_TYPE.items() for field in fields
        }
        assert spec_pairs == prod_pairs, (
            "Identifier-field spec drifted from production dict. "
            f"Missing from spec: {prod_pairs - spec_pairs}. "
            f"Extra in spec: {spec_pairs - prod_pairs}."
        )

    @parameterized.expand(
        [
            (f"{destination}-{field}-{idx}", destination, field, payload)
            for destination, field in _IDENTIFIER_FIELDS_BY_TYPE_CASES
            for idx, payload in enumerate(_FORBIDDEN_PAYLOADS)
        ]
    )
    def test_rejects_forbidden_chars(self, _name, destination, field, payload):
        with pytest.raises(drf_serializers.ValidationError, match=f"'{field}' contains forbidden characters"):
            _validate_identifier_fields(destination, {field: payload})

    @parameterized.expand(
        [
            (
                "snowflake",
                "Snowflake",
                {"database": "ANALYTICS", "warehouse": "WH", "schema": "public", "table_name": "events"},
            ),
            ("databricks", "Databricks", {"catalog": "main", "schema": "default", "table_name": "events"}),
            ("redshift", "Redshift", {"database": "prod", "schema": "public", "table_name": "events"}),
            ("postgres", "Postgres", {"database": "prod", "schema": "public", "table_name": "events"}),
            ("bigquery", "BigQuery", {"project_id": "my-project-123", "dataset_id": "analytics", "table_id": "events"}),
        ]
    )
    def test_accepts_benign_identifiers(self, _name, destination, config):
        _validate_identifier_fields(destination, config)

    def test_non_sql_destination_types_are_skipped(self):
        # Destinations not in the identifier map (S3, AzureBlob, HTTP, etc.) must not reject
        # config values — they don't reach SQL identifier positions.
        _validate_identifier_fields("S3", {"bucket_name": 'evil"; DROP'})
        _validate_identifier_fields("HTTP", {"url": "https://evil`.example"})

    def test_non_string_values_are_skipped(self):
        # Type checks are handled by the destination-field type validation earlier in
        # the serializer; this helper only filters dangerous chars from strings.
        _validate_identifier_fields("Snowflake", {"table_name": 123, "schema": None})

    def test_unrelated_fields_are_not_checked(self):
        # A forbidden char in a non-identifier field (e.g. 'user') must not raise — only
        # fields that reach SQL identifier positions are validated here.
        _validate_identifier_fields("Snowflake", {"user": 'svc"; DROP', "table_name": "events"})


class TestBatchExportDestinationSerializerTeamScoping(BaseTest):
    def _make_integration(self, team: Team) -> Integration:
        return Integration.objects.create(team=team, kind="databricks", integration_id="server")

    @parameterized.expand([("integration",), ("integration_id",)])
    def test_field_rejects_cross_team_integration(self, field_name):
        foreign_org = Organization.objects.create(name="Foreign")
        foreign_team = Team.objects.create(organization=foreign_org, name="Foreign")
        foreign_integration = self._make_integration(foreign_team)

        serializer = BatchExportDestinationSerializer(
            data={"type": "Databricks", "config": {}, field_name: foreign_integration.pk},
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
