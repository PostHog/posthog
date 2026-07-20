from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.hogql.parser import parse_select
from posthog.hogql.unbounded_events_query import query_reads_events_without_timestamp_filter


class TestUnboundedEventsQuery(BaseTest):
    @parameterized.expand(
        [
            # Unbounded: reads events, no timestamp constraint anywhere in a filter position.
            ("bare_events", "SELECT count() FROM events", True),
            ("events_with_event_filter_only", "SELECT count() FROM events WHERE event = '$pageview'", True),
            ("aliased_events_no_bound", "SELECT count() FROM events AS e WHERE e.event = '$pageview'", True),
            ("timestamp_only_in_select", "SELECT timestamp FROM events", True),
            ("unbounded_cte", "WITH x AS (SELECT distinct_id FROM events) SELECT count() FROM x", True),
            (
                "join_events_no_bound",
                "SELECT * FROM events AS e JOIN persons AS p ON p.id = e.person_id WHERE e.event = 'x'",
                True,
            ),
            # Bounded: a timestamp constraint exists in a filter position.
            ("bounded_timestamp", "SELECT count() FROM events WHERE timestamp > now() - interval 1 day", False),
            ("aliased_bounded_timestamp", "SELECT count() FROM events AS e WHERE e.timestamp > now()", False),
            (
                "bounded_alongside_event_filter",
                "SELECT count() FROM events WHERE event = '$pageview' AND timestamp > now()",
                False,
            ),
            # A timestamp bound inside a subquery does not bound the outer unbounded events read.
            (
                "outer_unbounded_inner_bounded",
                "SELECT count() FROM events WHERE distinct_id IN "
                "(SELECT distinct_id FROM events WHERE timestamp > now())",
                True,
            ),
            # A timestamp filter on a JOINed non-events table does not bound the events read.
            (
                "join_other_table_timestamp_not_events",
                "SELECT count() FROM events AS e JOIN some_table AS s ON s.id = e.person_id WHERE s.timestamp > now()",
                True,
            ),
            # A timestamp filter qualified with the events alias does bound it.
            (
                "join_events_alias_timestamp_bounded",
                "SELECT count() FROM events AS e JOIN some_table AS s ON s.id = e.person_id WHERE e.timestamp > now()",
                False,
            ),
            # A bounded outer query wrapping a bounded subquery is fine.
            (
                "bounded_subquery_only",
                "SELECT * FROM (SELECT count() FROM events WHERE timestamp > now()) AS sub",
                False,
            ),
            # No events table at all.
            ("no_events_table", "SELECT id FROM persons", False),
        ]
    )
    def test_detects_unbounded_events_reads(self, _name, sql, expected):
        assert query_reads_events_without_timestamp_filter(parse_select(sql)) is expected

    def test_handles_none(self):
        assert query_reads_events_without_timestamp_filter(None) is False
