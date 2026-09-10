from unittest import TestCase

from parameterized import parameterized

from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.errors import QueryError
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import print_prepared_ast
from posthog.hogql.property_access_types import RestrictedProperty
from posthog.hogql.resolver import resolve_types


class TestPersonPropertyMutationLog(TestCase):
    def setUp(self) -> None:
        self.context = HogQLContext(
            team_id=42,
            database=Database(),
            enable_select_queries=True,
            use_new_events_schema=False,
            restricted_properties=set(),
        )

    def test_point_lookup_scopes_tenant(self) -> None:
        query = resolve_types(
            parse_select(
                "SELECT properties FROM posthog.person_property_mutation_log WHERE event_uuid = '0192a5c8-0000-0000-0000-000000000000' LIMIT 1"
            ),
            self.context,
            "clickhouse",
        )
        sql = print_prepared_ast(query, self.context, "clickhouse")
        self.assertIn("equals(person_property_mutation_log.team_id, 42)", sql)
        self.assertIn("equals(person_property_mutation_log.event_uuid", sql)
        self.assertNotIn("JOIN", sql)

    @parameterized.expand(
        [
            "SELECT m.properties FROM events e JOIN posthog.person_property_mutation_log m ON e.uuid=m.event_uuid",
            "SELECT m.properties FROM posthog.person_property_mutation_log m JOIN events e ON e.uuid=m.event_uuid",
            "SELECT m.properties FROM events e LEFT JOIN (SELECT * FROM posthog.person_property_mutation_log) m ON e.uuid=m.event_uuid",
            "WITH m AS (SELECT * FROM posthog.person_property_mutation_log) SELECT m.properties FROM events e JOIN m ON e.uuid=m.event_uuid",
            "SELECT m.properties FROM events e, posthog.person_property_mutation_log m",
            "SELECT m.properties FROM events e CROSS JOIN posthog.person_property_mutation_log m",
            "SELECT m.properties FROM events e JOIN (SELECT * FROM posthog.person_property_mutation_log UNION ALL SELECT * FROM posthog.person_property_mutation_log) m ON e.uuid=m.event_uuid",
        ]
    )
    def test_rejects_joins(self, query: str) -> None:
        with self.assertRaisesRegex(QueryError, "cannot be joined"):
            resolve_types(parse_select(query), self.context, "clickhouse")

    def test_restricted_person_properties_cannot_leak_through_raw_payloads(self) -> None:
        self.context.restricted_properties = {RestrictedProperty(name="email", property_type=2)}
        query = resolve_types(
            parse_select("SELECT properties FROM posthog.person_property_mutation_log"), self.context, "clickhouse"
        )
        with self.assertRaisesRegex(QueryError, "unavailable when person properties are restricted"):
            print_prepared_ast(query, self.context, "clickhouse")

    @parameterized.expand(["$set", "$set_once", "$unset"])
    def test_event_property_restrictions_scrub_mutation_payloads(self, property_name: str) -> None:
        self.context.restricted_properties = {RestrictedProperty(name=property_name, property_type=1)}
        query = resolve_types(
            parse_select(f"SELECT properties, properties.`{property_name}` FROM posthog.person_property_mutation_log"),
            self.context,
            "clickhouse",
        )
        sql = print_prepared_ast(query, self.context, "clickhouse")
        self.assertEqual(sql.count("JSONDropKeys("), 2)
        self.assertIn([property_name], self.context.values.values())
