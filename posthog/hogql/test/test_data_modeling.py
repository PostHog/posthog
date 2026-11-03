from typing import cast

from unittest.mock import Mock, patch

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.hogql.context import HogQLContext
from posthog.hogql.data_modeling import modeling_field_key
from posthog.hogql.database.database import Database, build_database_root_node
from posthog.hogql.database.models import StringDatabaseField, Table, TableNode
from posthog.hogql.errors import QueryError
from posthog.hogql.parser import parse_select
from posthog.hogql.property_access_types import RestrictedProperty
from posthog.hogql.resolver import resolve_types

from products.event_definitions.backend.models.property_definition import PropertyDefinition


class TestModelingFieldAccess(SimpleTestCase):
    def _database(self) -> Database:
        root = build_database_root_node()
        table = cast(Table, root.get_child(["system", "dashboards"]).table)
        table.fields["name"].modeling_allowed = False
        with patch("posthog.hogql.database.database.build_database_root_node", return_value=root):
            return Database()

    @parameterized.expand(
        [
            ("projection", "SELECT name FROM system.dashboards"),
            ("predicate", "SELECT id FROM system.dashboards WHERE name = 'example'"),
            ("aggregate", "SELECT countIf(name = 'example') FROM system.dashboards"),
            ("wildcard", "SELECT d.* FROM system.dashboards d"),
            ("nested", "WITH d AS (SELECT name FROM system.dashboards) SELECT * FROM d"),
            ("join", "SELECT d.id FROM system.dashboards d JOIN system.dashboards e ON d.name = e.name"),
            ("column_alias", "SELECT secret FROM system.dashboards AS d(a, b, secret)"),
        ]
    )
    def test_modeling_rejects_restricted_fields(self, _name: str, query: str) -> None:
        database = self._database()
        database.for_data_modeling = True

        with self.assertRaisesRegex(QueryError, "not available for data modeling"):
            resolve_types(parse_select(query), HogQLContext(database=database), dialect="clickhouse")

    def test_field_restrictions_allow_ordinary_queries(self) -> None:
        database = self._database()

        resolve_types(
            parse_select("SELECT name FROM system.dashboards"), HogQLContext(database=database), dialect="clickhouse"
        )

    def test_expression_field_restrictions_apply_before_expansion(self) -> None:
        database = Database()
        database.for_data_modeling = True
        database.get_table("system.dashboards").fields["deleted"].modeling_allowed = False

        with self.assertRaisesRegex(QueryError, "not available for data modeling"):
            resolve_types(
                parse_select("SELECT deleted FROM system.dashboards"),
                HogQLContext(database=database),
                dialect="clickhouse",
            )

    def test_modeling_rejects_source_property_masks(self) -> None:
        database = Database()
        database.for_data_modeling = True
        context = HogQLContext(
            database=database,
            user=Mock(),
            use_new_events_schema=False,
            restricted_properties={RestrictedProperty(name="private_key", property_type=PropertyDefinition.Type.EVENT)},
        )

        with self.assertRaisesRegex(QueryError, "restricted properties"):
            resolve_types(parse_select("SELECT properties FROM events"), context, dialect="clickhouse")

    @parameterized.expand([("blocked", ["name"], True), ("allowed", ["id"], False), ("legacy", None, True)])
    def test_stored_results_use_the_fields_of_the_materialization(
        self, _name: str, source_names: list[str] | None, denied: bool
    ) -> None:
        database = self._database()
        source = database.get_table("system.dashboards")
        source_fields = (
            [modeling_field_key(source, name) for name in source_names] if source_names is not None else None
        )
        database.tables.add_child(
            TableNode(
                name="stored_result",
                table=Table(
                    name="stored_result",
                    fields={"value": StringDatabaseField(name="value")},
                    is_materialized_view=True,
                    modeling_source_fields=source_fields,
                ),
            )
        )
        query = parse_select("SELECT value FROM stored_result")
        context = HogQLContext(database=database)
        if denied:
            with self.assertRaisesRegex(QueryError, "full rebuild"):
                resolve_types(query, context, dialect="clickhouse")
        else:
            database.for_data_modeling = True
            resolve_types(query, context, dialect="clickhouse")
            self.assertTrue(set(source_fields or []) <= database.modeling_source_fields)
