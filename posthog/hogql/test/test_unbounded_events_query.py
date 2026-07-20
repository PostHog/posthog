from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.hogql.parser import parse_select
from posthog.hogql.unbounded_events_query import query_reads_events_without_timestamp_filter


class TestUnboundedEventsQuery(SimpleTestCase):
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
            # A timestamp bound under an OR does not constrain the scan.
            (
                "timestamp_under_or",
                "SELECT count() FROM events WHERE timestamp > now() OR event = 'x'",
                True,
            ),
            # A timestamp bound in every OR branch does constrain it.
            (
                "timestamp_in_all_or_branches",
                "SELECT count() FROM events WHERE (timestamp > now() AND event = 'a') OR (timestamp > now() AND event = 'b')",
                False,
            ),
            # HAVING is post-aggregation and does not bound the scan.
            (
                "having_timestamp_not_bounding",
                "SELECT event, count() FROM events GROUP BY event HAVING max(timestamp) > now()",
                True,
            ),
            # ClickHouse pushes an outer predicate into the single subquery / CTE feeding it.
            (
                "subquery_prefilter_outer_bound",
                "SELECT count() FROM (SELECT event, timestamp FROM events) WHERE timestamp > now()",
                False,
            ),
            (
                "cte_prefilter_outer_bound",
                "WITH pv AS (SELECT event, timestamp FROM events WHERE event = '$pageview') "
                "SELECT count() FROM pv WHERE timestamp > now()",
                False,
            ),
            # But a bound does NOT reach an independent subquery — one in WHERE, or a joined source
            # the predicate doesn't touch — so an unbounded events read there is still caught.
            (
                "bound_does_not_reach_where_subquery",
                "SELECT count() FROM events AS e WHERE e.timestamp > now() "
                "AND e.distinct_id IN (SELECT distinct_id FROM events)",
                True,
            ),
            (
                "bound_does_not_reach_joined_subquery",
                "SELECT count() FROM events AS e JOIN (SELECT * FROM events) AS s "
                "ON s.distinct_id = e.distinct_id WHERE e.timestamp > now()",
                True,
            ),
            # A CTE named `events` shadows the real table.
            ("cte_named_events_shadow", "WITH events AS (SELECT 1 AS x) SELECT x FROM events", False),
            # A plain LIMIT read is not a full-history scan; a filtered or aggregating one still is.
            ("editor_default_limit", "SELECT * FROM events LIMIT 100", False),
            ("count_with_limit", "SELECT count() FROM events LIMIT 100", True),
            ("filtered_limit_can_scan", "SELECT * FROM events WHERE event = 'rare' LIMIT 100", True),
            # No events table at all.
            ("no_events_table", "SELECT id FROM persons", False),
        ]
    )
    def test_detects_unbounded_events_reads(self, _name, sql, expected):
        assert query_reads_events_without_timestamp_filter(parse_select(sql)) is expected

    def test_handles_none(self):
        assert query_reads_events_without_timestamp_filter(None) is False
