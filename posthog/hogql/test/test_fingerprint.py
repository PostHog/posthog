from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.hogql.fingerprint import FINGERPRINT_VERSION, fingerprint_hogql_query
from posthog.hogql.parser import parse_select


def _fp(query: str) -> str:
    return fingerprint_hogql_query(parse_select(query))


class TestHogQLFingerprint(BaseTest):
    @parameterized.expand(
        [
            (
                "literals",
                "SELECT event FROM events WHERE timestamp > now() - INTERVAL 7 DAY AND event ILIKE '%invoice%' LIMIT 10",
                "SELECT event FROM events WHERE timestamp > now() - INTERVAL 30 DAY AND event ILIKE '%billing%' LIMIT 50",
            ),
            (
                "alias_names_and_keyword_case",
                "SELECT event, count() AS cnt FROM events GROUP BY event",
                "select event, COUNT() total from events group by event",
            ),
            (
                "whitespace_and_newlines",
                "SELECT event FROM events WHERE event = 'a'",
                "SELECT\n    event\nFROM events\nWHERE\n    event = 'b'",
            ),
            (
                "positional_group_and_order_refs",
                "SELECT event, count() AS c FROM events GROUP BY event ORDER BY c DESC",
                "SELECT event, count() FROM events GROUP BY 1 ORDER BY 2 DESC",
            ),
            (
                "table_alias_qualification",
                "SELECT event FROM events WHERE event = 'a'",
                "SELECT e.event FROM events e WHERE e.event = 'b'",
            ),
            (
                "literal_list_lengths",
                "SELECT count() FROM events WHERE event IN ('a', 'b')",
                "SELECT count() FROM events WHERE event IN ('c', 'd', 'e')",
            ),
            (
                "literal_array_vs_tuple",
                "SELECT count() FROM events WHERE event IN ['a', 'b']",
                "SELECT count() FROM events WHERE event IN ('a', 'b')",
            ),
            (
                "bracket_vs_dot_property_access",
                "SELECT properties['foo'] FROM events",
                "SELECT properties.foo FROM events",
            ),
            (
                "cte_names",
                "WITH x AS (SELECT event FROM events) SELECT event FROM x",
                "WITH y AS (SELECT event FROM events) SELECT event FROM y",
            ),
            (
                "cte_names_across_union_branches",
                "WITH x AS (SELECT event FROM events) SELECT event FROM x UNION ALL SELECT event FROM x",
                "WITH y AS (SELECT event FROM events) SELECT event FROM y UNION ALL SELECT event FROM y",
            ),
            (
                "count_star_vs_count",
                "SELECT count(*) FROM events",
                "SELECT count() FROM events",
            ),
            (
                "template_placeholder_vs_literals",
                "SELECT count() FROM events WHERE distinct_id IN {ids}",
                "SELECT count() FROM events WHERE distinct_id IN ('a', 'b')",
            ),
            (
                "join_alias_names",
                "SELECT e.event, g.key FROM events e JOIN groups g ON e.$group_0 = g.key",
                "SELECT a.event, b.key FROM events a JOIN groups b ON a.$group_0 = b.key",
            ),
        ]
    )
    def test_equivalent_queries_share_a_fingerprint(self, _name, query_a, query_b):
        self.assertEqual(_fp(query_a), _fp(query_b))

    @parameterized.expand(
        [
            (
                "comparison_operator",
                "SELECT count() FROM events WHERE timestamp > now()",
                "SELECT count() FROM events WHERE timestamp >= now()",
            ),
            (
                "filtered_column",
                "SELECT count() FROM events WHERE properties.plan = 'x'",
                "SELECT count() FROM events WHERE properties.status = 'x'",
            ),
            (
                "extra_select_column",
                "SELECT event FROM events",
                "SELECT event, timestamp FROM events",
            ),
            (
                "different_table",
                "SELECT count() FROM events",
                "SELECT count() FROM persons",
            ),
            (
                "aggregate_function",
                "SELECT count() FROM events GROUP BY event",
                "SELECT uniq(person_id) FROM events GROUP BY event",
            ),
            (
                "bracket_property_name",
                "SELECT properties['foo'] FROM events",
                "SELECT properties['bar'] FROM events",
            ),
            (
                "join_source_of_column",
                "SELECT a.event FROM events a JOIN events b ON a.person_id = b.person_id",
                "SELECT b.event FROM events a JOIN events b ON a.person_id = b.person_id",
            ),
            (
                "self_join_condition_sources",
                "SELECT count() FROM events a JOIN events b ON a.person_id = b.person_id",
                "SELECT count() FROM events a JOIN events b ON a.person_id = a.person_id",
            ),
        ]
    )
    def test_structurally_different_queries_differ(self, _name, query_a, query_b):
        self.assertNotEqual(_fp(query_a), _fp(query_b))

    def test_fingerprint_is_deterministic_and_versioned(self):
        query = "SELECT event, count() FROM events WHERE event = 'x' GROUP BY event"
        first, second = _fp(query), _fp(query)
        self.assertEqual(first, second)
        self.assertTrue(first.startswith(f"{FINGERPRINT_VERSION}:"))

    def test_lazy_join_hops_are_not_stripped_as_qualifiers(self):
        with_hop = "SELECT count() FROM events WHERE person.properties.email = 'x'"
        without_hop = "SELECT count() FROM events WHERE properties.email = 'x'"
        self.assertNotEqual(_fp(with_hop), _fp(without_hop))
