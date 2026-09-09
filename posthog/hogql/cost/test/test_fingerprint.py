from typing import cast

from posthog.test.base import BaseTest

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.cost.fingerprint import fingerprint_query
from posthog.hogql.database.database import Database
from posthog.hogql.parser import parse_select
from posthog.hogql.resolver import resolve_types


class TestFingerprintQueryShape(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "date_range",
                "SELECT count() FROM events WHERE timestamp > '2024-01-01' AND timestamp < '2024-02-01'",
                "SELECT count() FROM events WHERE timestamp > '2025-06-01' AND timestamp < '2025-09-01'",
            ),
            (
                "event_name",
                "SELECT count() FROM events WHERE event = '$pageview'",
                "SELECT count() FROM events WHERE event = 'signup'",
            ),
            (
                "limit",
                "SELECT event FROM events LIMIT 10",
                "SELECT event FROM events LIMIT 100000",
            ),
            (
                "in_list_values",
                "SELECT count() FROM events WHERE event IN ('a', 'b')",
                "SELECT count() FROM events WHERE event IN ('c', 'd')",
            ),
        ]
    )
    def test_queries_differing_only_in_literals_share_a_fingerprint(self, _name, sql_a, sql_b):
        assert fingerprint_query(parse_select(sql_a)) == fingerprint_query(parse_select(sql_b))

    @parameterized.expand(
        [
            (
                "extra_predicate",
                "SELECT count() FROM events WHERE event = 'x'",
                "SELECT count() FROM events WHERE event = 'x' AND properties.$browser = 'y'",
            ),
            (
                "table",
                "SELECT count() FROM events",
                "SELECT count() FROM persons",
            ),
            (
                "join",
                "SELECT count() FROM events",
                "SELECT count() FROM events JOIN persons ON persons.id = events.person_id",
            ),
            (
                "aggregate_function",
                "SELECT count() FROM events",
                "SELECT uniq(distinct_id) FROM events",
            ),
            (
                "literal_type",
                "SELECT count() FROM events WHERE properties.n = 1",
                "SELECT count() FROM events WHERE properties.n = '1'",
            ),
            (
                "operator",
                "SELECT count() FROM events WHERE timestamp > '2024-01-01'",
                "SELECT count() FROM events WHERE timestamp < '2024-01-01'",
            ),
            (
                "group_by",
                "SELECT count() FROM events",
                "SELECT count() FROM events GROUP BY event",
            ),
        ]
    )
    def test_structural_differences_produce_distinct_fingerprints(self, _name, sql_a, sql_b):
        assert fingerprint_query(parse_select(sql_a)) != fingerprint_query(parse_select(sql_b))


class TestFingerprintQueryResolution(BaseTest):
    def test_resolved_types_do_not_change_the_fingerprint(self):
        node = parse_select("SELECT count() AS c FROM events WHERE event = '$pageview' AND timestamp > '2024-01-01'")
        raw = fingerprint_query(node)

        database = Database.create_for(team=self.team)
        context = HogQLContext(database=database, team_id=self.team.pk, enable_select_queries=True)
        resolved = cast(ast.SelectQuery, resolve_types(node, context, dialect="clickhouse"))

        assert fingerprint_query(resolved) == raw
