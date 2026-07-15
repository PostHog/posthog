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
                "SELECT count() FROM events WHERE event IN ('c', 'd')",
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

    # Fingerprints are persisted in query_log and grouped over time: a change in
    # output for the same version silently re-shards every downstream series.
    # If this test fails, your change altered fingerprint output (possibly
    # indirectly, via the parser or the HogQL printer). Bump FINGERPRINT_VERSION
    # and re-pin these values in the same PR; never re-pin without bumping.
    @parameterized.expand(
        [
            ("v1:3f567df03e7683df", "SELECT event, count() FROM events WHERE event = 'x' GROUP BY event"),
            (
                "v1:033325ddcb92a8a6",
                "SELECT event, count() AS cnt FROM events WHERE timestamp > now() - INTERVAL 7 DAY GROUP BY 1 ORDER BY cnt DESC LIMIT 10",
            ),
            ("v1:11e4c038992f75e6", "SELECT e.event FROM events e WHERE e.event ILIKE '%x%'"),
            ("v1:6536973b299a961c", "SELECT count() FROM events WHERE event IN ('a', 'b', 'c')"),
            ("v1:ff828fffc7532f96", "SELECT person.properties.email FROM events WHERE timestamp > '2026-01-01'"),
            (
                "v1:6e040279d7a70204",
                "SELECT uuid FROM (SELECT uuid, count() AS c FROM events GROUP BY uuid) WHERE c > 5",
            ),
            ("v1:13bb56577e78da73", "SELECT event FROM events UNION ALL SELECT event FROM events WHERE event = 'y'"),
        ]
    )
    def test_fingerprint_values_are_pinned_to_the_version(self, expected, query):
        self.assertEqual(
            _fp(query),
            expected,
            "Fingerprint output changed for an unchanged version. If intentional, bump "
            "FINGERPRINT_VERSION and re-pin every value in this test in the same PR.",
        )
        self.assertTrue(expected.startswith(f"{FINGERPRINT_VERSION}:"), "pinned values must match the current version")
