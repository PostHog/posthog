from datetime import date, datetime
from zoneinfo import ZoneInfo

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.hogql import ast
from posthog.hogql.cost.read_signature import read_signature
from posthog.hogql.parser import parse_select


class TestReadSignature(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "time_of_day",
                "SELECT count() FROM events WHERE event = 'a' AND timestamp >= '2026-03-01 05:00:00' AND timestamp <= '2026-03-14 08:59:59'",
                "SELECT count() FROM events WHERE event = 'a' AND timestamp >= '2026-03-01 09:30:00' AND timestamp <= '2026-03-14 11:59:59'",
            ),
            (
                "filters_and_aggregates_outside_the_sort_key",
                "SELECT count() FROM events WHERE event = 'a' AND timestamp >= '2026-03-01'",
                "SELECT uniq(person_id) FROM events AS e WHERE e.event = 'a' AND e.timestamp >= toDateTime('2026-03-01') AND properties.$browser = 'Chrome'",
            ),
            (
                "bound_spelling",
                "SELECT count() FROM events WHERE timestamp >= '2026-03-01' AND timestamp <= '2026-03-14'",
                "SELECT count() FROM events WHERE '2026-03-01' <= timestamp AND timestamp BETWEEN '2026-03-01' AND '2026-03-14'",
            ),
            (
                "event_list_spelling",
                "SELECT count() FROM events WHERE event IN ('b', 'a')",
                "SELECT count() FROM events WHERE event = 'a' OR event = 'b'",
            ),
            (
                "subquery_or_cte",
                "SELECT count() FROM (SELECT event FROM events WHERE timestamp > '2026-03-01')",
                "WITH scoped AS (SELECT event FROM events WHERE timestamp > '2026-03-01') SELECT count() FROM scoped",
            ),
            (
                "chart_bounds_wrapped_in_assume_not_null",
                "SELECT count() FROM events WHERE timestamp >= assumeNotNull(toDateTime('2026-03-01 00:00:00')) AND timestamp <= assumeNotNull(toDateTime('2026-03-14 23:59:59'))",
                "SELECT count() FROM events WHERE timestamp >= assumeNotNull(toDateTime('2026-03-01 08:15:00')) AND timestamp <= assumeNotNull(toDateTime('2026-03-14 08:14:59'))",
            ),
            (
                "same_utc_day_in_two_zones",
                "SELECT count() FROM events WHERE timestamp >= toDateTime('2026-03-01 20:00:00', 'America/New_York')",
                "SELECT count() FROM events WHERE timestamp >= toDateTime('2026-03-02 01:00:00', 'UTC')",
            ),
            (
                "qualified_events_table",
                "SELECT count() FROM posthog.events WHERE event = 'a' AND timestamp >= '2026-03-01'",
                "SELECT count() FROM events WHERE event = 'a' AND timestamp >= '2026-03-01'",
            ),
            (
                "filter_outside_a_subquery",
                "SELECT count() FROM (SELECT * FROM events) WHERE event = 'a'",
                "SELECT count() FROM events WHERE event = 'a'",
            ),
            (
                "unused_cte",
                "WITH unused AS (SELECT event FROM events WHERE event = 'x') SELECT count() FROM persons",
                "SELECT count() FROM persons",
            ),
        ]
    )
    def test_queries_reading_the_same_data_share_a_signature(self, _name, sql_a, sql_b):
        assert read_signature(parse_select(sql_a)) == read_signature(parse_select(sql_b))

    @parameterized.expand(
        [
            (
                "event_name",
                "SELECT count() FROM events WHERE event = 'a'",
                "SELECT count() FROM events WHERE event = 'b'",
            ),
            (
                "day_range",
                "SELECT count() FROM events WHERE timestamp >= '2026-03-01'",
                "SELECT count() FROM events WHERE timestamp >= '2026-03-02'",
            ),
            (
                "table",
                "SELECT count() FROM events",
                "SELECT count() FROM persons",
            ),
            (
                "relative_window",
                "SELECT count() FROM events WHERE timestamp > now() - INTERVAL 7 DAY",
                "SELECT count() FROM events WHERE timestamp > now() - INTERVAL 30 DAY",
            ),
            (
                "arithmetic_on_a_literal_date",
                "SELECT count() FROM events WHERE timestamp > toDateTime('2026-03-01')",
                "SELECT count() FROM events WHERE timestamp > toDateTime('2026-03-01') - INTERVAL 7 DAY",
            ),
            (
                "date_changing_function",
                "SELECT count() FROM events WHERE timestamp >= addDays('2026-03-01', 7)",
                "SELECT count() FROM events WHERE timestamp >= addDays('2026-03-01', 30)",
            ),
            (
                "event_names_containing_commas",
                "SELECT count() FROM events WHERE event IN ('a,b')",
                "SELECT count() FROM events WHERE event IN ('a', 'b')",
            ),
            (
                "join_constraint",
                "SELECT count() FROM events AS e INNER JOIN persons AS p ON e.event = 'a'",
                "SELECT count() FROM events AS e INNER JOIN persons AS p ON e.event = 'b'",
            ),
            (
                "unrecognized_timestamp_condition",
                "SELECT count() FROM events",
                "SELECT count() FROM events WHERE toDate(timestamp) = today()",
            ),
            (
                "table_named_like_a_cte_in_another_branch",
                "SELECT id FROM (WITH persons AS (SELECT 1 AS id) SELECT id FROM persons) UNION ALL SELECT 1",
                "SELECT id FROM (WITH persons AS (SELECT 1 AS id) SELECT id FROM persons) UNION ALL SELECT id FROM persons",
            ),
            (
                "filter_outside_a_subquery",
                "SELECT count() FROM (SELECT * FROM events) WHERE event = 'a'",
                "SELECT count() FROM (SELECT * FROM events) WHERE event = 'b'",
            ),
            (
                "filter_outside_a_cte",
                "WITH scoped AS (SELECT * FROM events) SELECT count() FROM scoped WHERE timestamp >= '2026-03-01'",
                "WITH scoped AS (SELECT * FROM events) SELECT count() FROM scoped WHERE timestamp >= '2026-03-02'",
            ),
            (
                "self_joined_bounds_swapped",
                "SELECT count() FROM events AS a JOIN events AS b ON a.distinct_id = b.distinct_id WHERE a.event = 'signup' AND a.timestamp >= '2026-03-01' AND b.event = 'purchase' AND b.timestamp >= '2026-03-02'",
                "SELECT count() FROM events AS a JOIN events AS b ON a.distinct_id = b.distinct_id WHERE a.event = 'signup' AND a.timestamp >= '2026-03-02' AND b.event = 'purchase' AND b.timestamp >= '2026-03-01'",
            ),
            (
                "qualified_events_table_event_name",
                "SELECT count() FROM posthog.events WHERE event = 'a'",
                "SELECT count() FROM posthog.events WHERE event = 'b'",
            ),
            (
                "projected_alias",
                "SELECT event AS name FROM events WHERE name = 'a'",
                "SELECT event AS name FROM events WHERE name = 'b'",
            ),
            (
                "scalar_cte_window",
                "WITH now() - INTERVAL 7 DAY AS start SELECT count() FROM events WHERE timestamp >= start",
                "WITH now() - INTERVAL 30 DAY AS start SELECT count() FROM events WHERE timestamp >= start",
            ),
            (
                "timezone_argument",
                "SELECT count() FROM events WHERE timestamp >= toDateTime('2026-03-01 23:00:00', 'America/Los_Angeles')",
                "SELECT count() FROM events WHERE timestamp >= toDateTime('2026-03-01 23:00:00', 'UTC')",
            ),
            (
                "event_condition_narrowed_by_another_filter",
                "SELECT count() FROM events WHERE event = 'a' OR event = 'b'",
                "SELECT count() FROM events WHERE event = 'a' OR (event = 'b' AND properties.plan = 'pro')",
            ),
        ]
    )
    def test_queries_reading_different_data_get_different_signatures(self, _name, sql_a, sql_b):
        assert read_signature(parse_select(sql_a)) != read_signature(parse_select(sql_b))

    @parameterized.expand(
        [
            ("naive_datetime", datetime(2026, 3, 1, 5, 0), "2026-03-01 09:30:00"),
            ("date", date(2026, 3, 1), "2026-03-01 09:30:00"),
            (
                "aware_datetime",
                datetime(2026, 3, 1, 23, 0, tzinfo=ZoneInfo("America/New_York")),
                "2026-03-02T01:00:00+00:00",
            ),
        ]
    )
    def test_date_object_bound_matches_its_string_form(self, _name, value, string_form):
        from_object = parse_select(
            "SELECT count() FROM events WHERE timestamp >= {start}", placeholders={"start": ast.Constant(value=value)}
        )
        from_string = parse_select(f"SELECT count() FROM events WHERE timestamp >= '{string_form}'")

        assert read_signature(from_object) == read_signature(from_string)

    def test_cte_named_events_is_not_a_read_of_the_events_table(self):
        assert read_signature(parse_select("WITH events AS (SELECT 'a' AS event) SELECT count() FROM events")) is None

    def test_root_cte_is_visible_in_every_union_branch(self):
        with_cte = parse_select(
            "WITH scoped AS (SELECT event FROM events) SELECT * FROM scoped UNION ALL SELECT * FROM scoped"
        )
        without_cte = parse_select("SELECT * FROM events UNION ALL SELECT * FROM events")

        assert read_signature(with_cte) == read_signature(without_cte)

    def test_query_reading_no_table_has_no_signature(self):
        assert read_signature(parse_select("SELECT 1")) is None
