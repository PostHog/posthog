from datetime import UTC, datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.hogql.parser import parse_select

from posthog.hogql_queries.sql_cache_window import SqlTimeWindow, SqlWindowClass, SqlWindowClassifier

NOW = datetime(2026, 10, 29, 15, 0, tzinfo=UTC)
LOS_ANGELES = ZoneInfo("America/Los_Angeles")


class TestSqlWindowClassifier(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "last_30_minutes",
                "select count() from events where timestamp > now() - interval 30 minute",
                SqlWindowClass.LIVE,
            ),
            (
                "last_6_hours",
                "select count() from events where timestamp >= now() - interval 6 hour",
                SqlWindowClass.UP_TO_NOW_SHORT,
            ),
            ("today", "select count() from events where toDate(timestamp) = today()", SqlWindowClass.UP_TO_NOW_SHORT),
            (
                "last_7_days",
                "select count() from events where timestamp > now() - interval 7 day",
                SqlWindowClass.UP_TO_NOW_LONG,
            ),
            (
                "subtract_days",
                "select count() from events where timestamp >= subtractDays(now(), 3)",
                SqlWindowClass.UP_TO_NOW_LONG,
            ),
            (
                "open_fixed_start",
                "select count() from events where timestamp >= '2026-10-01'",
                SqlWindowClass.UP_TO_NOW_LONG,
            ),
            (
                "yesterday",
                "select count() from events where toDate(timestamp) = yesterday()",
                SqlWindowClass.FIXED_PAST,
            ),
            (
                "fixed_past_range",
                "select count() from events where timestamp between '2026-10-01' and toDateTime('2026-10-15 00:00:00')",
                SqlWindowClass.FIXED_PAST,
            ),
            (
                "range_ending_today",
                "select count() from events where timestamp >= '2026-10-01' and timestamp < now()",
                SqlWindowClass.UP_TO_NOW_LONG,
            ),
            ("no_time_filter", "select count() from events", SqlWindowClass.NO_TIME_FILTER),
            ("upper_bound_only", "select count() from events where timestamp < now()", SqlWindowClass.NO_TIME_FILTER),
            (
                "freshest_column_wins",
                "select count() from events where created_at < '2025-01-01' and timestamp > now() - interval 10 minute",
                SqlWindowClass.LIVE,
            ),
            (
                "freshest_select_wins",
                "select 1 from events where timestamp > now() - interval 30 day "
                "union all select 1 from events where timestamp > now() - interval 5 minute",
                SqlWindowClass.LIVE,
            ),
            (
                "cte_reference_is_not_a_table",
                "with recent as (select event from events where timestamp > now() - interval 7 day) select count() from recent",
                SqlWindowClass.UP_TO_NOW_LONG,
            ),
            (
                "unfiltered_join_keeps_default",
                "select count() from (select person_id from events where timestamp > now() - interval 7 day) e "
                "join persons p on p.id = e.person_id",
                SqlWindowClass.NO_TIME_FILTER,
            ),
            (
                "property_date_is_not_a_window",
                "select count() from events where timestamp > now() - interval 10 minute and properties.signup < '2025-01-01'",
                SqlWindowClass.UNCLASSIFIED,
            ),
            (
                "or_of_windows",
                "select count() from events where timestamp > now() - interval 7 day or timestamp < '2020-01-01'",
                SqlWindowClass.UNCLASSIFIED,
            ),
            (
                "variable_bound",
                "select count() from events where timestamp > {variables.start}",
                SqlWindowClass.UNCLASSIFIED,
            ),
            (
                "date_diff",
                "select count() from events where dateDiff('day', timestamp, now()) < 7",
                SqlWindowClass.UNCLASSIFIED,
            ),
            (
                "inclusive_upper_bound_on_truncated_column",
                "select count() from events where toDate(timestamp) >= '2026-10-01' and toDate(timestamp) <= today()",
                SqlWindowClass.UP_TO_NOW_LONG,
            ),
            (
                "between_high_on_truncated_column",
                "select count() from events where toDate(timestamp) between '2026-10-01' and today()",
                SqlWindowClass.UP_TO_NOW_LONG,
            ),
            (
                "exclusive_upper_bound_on_truncated_column",
                "select count() from events where toDate(timestamp) >= '2026-10-01' and toDate(timestamp) < today()",
                SqlWindowClass.FIXED_PAST,
            ),
            (
                "greater_than_on_truncated_column",
                "select count() from events where toDate(timestamp) > yesterday()",
                SqlWindowClass.UP_TO_NOW_SHORT,
            ),
            (
                "shifted_column",
                "select count() from events where subtractDays(timestamp, 30) < '2026-10-28'",
                SqlWindowClass.UNCLASSIFIED,
            ),
            (
                "time_zone_conversion_inside_truncation",
                "select count() from events where toDate(toTimeZone(timestamp, 'Asia/Tokyo')) = yesterday()",
                SqlWindowClass.UNCLASSIFIED,
            ),
            (
                "select_alias_hides_shift",
                "select timestamp - interval 3 year as event_time from events where event_time < '2025-01-01'",
                SqlWindowClass.UNCLASSIFIED,
            ),
            (
                "select_alias_of_truncation",
                "select toStartOfDay(timestamp) as day from events where day >= '2026-10-01' and day <= '2026-10-29'",
                SqlWindowClass.UP_TO_NOW_LONG,
            ),
            (
                "joined_events_aliases_both_bounded",
                "select count() from events e join events f on e.person_id = f.person_id "
                "where e.timestamp >= '2025-01-01' and e.timestamp < '2025-02-01' "
                "and f.timestamp >= '2025-01-01' and f.timestamp < '2025-02-01'",
                SqlWindowClass.FIXED_PAST,
            ),
            (
                "joined_events_alias_without_bound",
                "select count() from events e join events f on e.person_id = f.person_id "
                "where e.timestamp >= '2025-01-01' and e.timestamp < '2025-02-01'",
                SqlWindowClass.NO_TIME_FILTER,
            ),
            (
                "ambiguous_column_in_join",
                "select count() from events e join events f on e.person_id = f.person_id where timestamp < '2025-01-01'",
                SqlWindowClass.UNCLASSIFIED,
            ),
            (
                "numeric_offset_is_seconds_on_datetime",
                "select count() from events where timestamp >= now() - 3600",
                SqlWindowClass.LIVE,
            ),
            (
                "numeric_offset_is_seconds_on_start_of_day",
                "select count() from events where timestamp >= toStartOfDay(now()) - 3",
                SqlWindowClass.UP_TO_NOW_SHORT,
            ),
            (
                "numeric_offset_is_days_on_date",
                "select count() from events where toDate(timestamp) >= today() - 3",
                SqlWindowClass.UP_TO_NOW_LONG,
            ),
            (
                "numeric_offset_on_string_literal",
                "select count() from events where timestamp >= '2026-10-01' - 3",
                SqlWindowClass.UNCLASSIFIED,
            ),
            (
                "time_zone_argument_on_literal",
                "select count() from events where timestamp >= '2026-10-01' "
                "and timestamp < toDateTime64('2026-10-29 10:00:00', 6, 'America/Los_Angeles')",
                SqlWindowClass.UP_TO_NOW_LONG,
            ),
            (
                "time_zone_argument_on_truncation",
                "select count() from events where toDate(timestamp, 'UTC') = today()",
                SqlWindowClass.UNCLASSIFIED,
            ),
            (
                "time_zone_argument_on_value_truncation",
                "select count() from events where toDate(timestamp) = toDate(now(), 'UTC')",
                SqlWindowClass.UNCLASSIFIED,
            ),
            (
                "time_zone_argument_on_best_effort_parse",
                "select count() from events where timestamp > parseDateTimeBestEffort('2026-10-01', 'UTC')",
                SqlWindowClass.UNCLASSIFIED,
            ),
            (
                "mutable_table_with_closed_range",
                "select count() from persons where created_at >= '2025-01-01' and created_at < '2025-02-01'",
                SqlWindowClass.NO_TIME_FILTER,
            ),
            (
                "mutable_system_table_with_closed_range",
                "select count() from system.insights where created_at >= '2025-01-01' and created_at < '2025-02-01'",
                SqlWindowClass.NO_TIME_FILTER,
            ),
            (
                "events_joined_to_mutable_table",
                "select count() from events e join persons p on e.person_id = p.id "
                "where e.timestamp >= '2025-01-01' and e.timestamp < '2025-02-01'",
                SqlWindowClass.NO_TIME_FILTER,
            ),
            (
                "person_column_is_not_the_event_time",
                "select count() from events where person.created_at >= '2025-01-01' and person.created_at < '2025-02-01'",
                SqlWindowClass.UNCLASSIFIED,
            ),
        ]
    )
    def test_classifies_sql(self, _name: str, sql: str, expected: SqlWindowClass) -> None:
        classifier = SqlWindowClassifier(now=NOW, timezone=ZoneInfo("UTC"), filters_window=None)
        assert classifier.classify(parse_select(sql)).window_class == expected

    @parameterized.expand(
        [
            (
                "yesterday_in_project_tz_before_utc_midnight",
                datetime(2026, 10, 29, 3, 0, tzinfo=UTC),
                "select count() from events where toDate(timestamp) >= '2026-10-01' and toDate(timestamp) < today()",
                SqlWindowClass.UP_TO_NOW_LONG,
            ),
            (
                "timestamp_before_today_in_project_tz",
                datetime(2026, 10, 29, 3, 0, tzinfo=UTC),
                "select count() from events where timestamp >= '2026-10-01' and timestamp < today()",
                SqlWindowClass.UP_TO_NOW_LONG,
            ),
            (
                "up_to_yesterday_in_project_tz",
                datetime(2026, 10, 29, 3, 0, tzinfo=UTC),
                "select count() from events where toDate(timestamp) >= '2026-10-01' and toDate(timestamp) <= yesterday()",
                SqlWindowClass.UP_TO_NOW_LONG,
            ),
            (
                "before_today_after_project_midnight_has_passed",
                datetime(2026, 10, 29, 12, 0, tzinfo=UTC),
                "select count() from events where toDate(timestamp) >= '2026-10-01' and toDate(timestamp) < today()",
                SqlWindowClass.FIXED_PAST,
            ),
        ]
    )
    def test_evaluates_today_in_server_time_zone(
        self, _name: str, now: datetime, sql: str, expected: SqlWindowClass
    ) -> None:
        classifier = SqlWindowClassifier(now=now, timezone=LOS_ANGELES, filters_window=None)
        assert classifier.classify(parse_select(sql)).window_class == expected

    @parameterized.expand(
        [
            (
                "yesterday_cached_before_midnight",
                "select count() from events where toDate(timestamp) = yesterday()",
                datetime(2026, 10, 28, 17, 41, tzinfo=UTC),
                SqlWindowClass.UP_TO_NOW_LONG,
            ),
            (
                "yesterday_cached_after_it_settled",
                "select count() from events where toDate(timestamp) = yesterday()",
                datetime(2026, 10, 29, 10, 0, tzinfo=UTC),
                SqlWindowClass.FIXED_PAST,
            ),
            (
                "absolute_end_cached_before_it_passed",
                "select count() from events where timestamp >= '2026-10-01' and timestamp < '2026-10-29'",
                datetime(2026, 10, 28, 15, 0, tzinfo=UTC),
                SqlWindowClass.UP_TO_NOW_LONG,
            ),
            (
                "cached_inside_the_settle_buffer",
                "select count() from events where timestamp >= '2026-10-01' and timestamp < '2026-10-29'",
                datetime(2026, 10, 29, 0, 30, tzinfo=UTC),
                SqlWindowClass.UP_TO_NOW_LONG,
            ),
            (
                "past_range_cached_well_after_its_end",
                "select count() from events where timestamp >= '2026-10-01' and timestamp < '2026-10-15'",
                datetime(2026, 10, 28, 20, 0, tzinfo=UTC),
                SqlWindowClass.FIXED_PAST,
            ),
        ]
    )
    def test_fixed_past_needs_a_window_that_ended_before_the_cache_write(
        self, _name: str, sql: str, last_refresh: datetime, expected: SqlWindowClass
    ) -> None:
        classifier = SqlWindowClassifier(now=NOW, timezone=ZoneInfo("UTC"), filters_window=None)
        assert classifier.classify(parse_select(sql)).class_at(last_refresh) == expected

    @parameterized.expand(
        [
            (
                "relative_range",
                "select count() from events where {filters}",
                SqlTimeWindow(start=NOW - timedelta(days=7), end=None),
                SqlWindowClass.UP_TO_NOW_LONG,
            ),
            (
                "past_range",
                "select count() from events where {filters}",
                SqlTimeWindow(start=NOW - timedelta(days=30), end=NOW - timedelta(days=2)),
                SqlWindowClass.FIXED_PAST,
            ),
            ("no_date_range", "select count() from events where {filters}", None, SqlWindowClass.NO_TIME_FILTER),
            (
                "date_only_date_to_today",
                "select count() from events where {filters}",
                SqlTimeWindow(
                    start=NOW - timedelta(days=7),
                    end=datetime(2026, 10, 29, 23, 59, 59, 999999, tzinfo=UTC),
                    end_inclusive=True,
                ),
                SqlWindowClass.UP_TO_NOW_LONG,
            ),
            (
                "bound_filters_opt_out_of_timestamp",
                "select count() from events where {filters(null AS timestamp)}",
                SqlTimeWindow(start=NOW - timedelta(days=30), end=NOW - timedelta(days=2)),
                SqlWindowClass.NO_TIME_FILTER,
            ),
            (
                "bound_filters_timestamp_column",
                "select count() from events where {filters(timestamp AS timestamp)}",
                SqlTimeWindow(start=NOW - timedelta(days=30), end=NOW - timedelta(days=2)),
                SqlWindowClass.FIXED_PAST,
            ),
            (
                "bound_filters_computed_timestamp",
                "select count() from events where {filters(coalesce(timestamp, now()) AS timestamp)}",
                SqlTimeWindow(start=NOW - timedelta(days=30), end=NOW - timedelta(days=2)),
                SqlWindowClass.NO_TIME_FILTER,
            ),
            (
                "filters_in_join_without_a_single_table",
                "select count() from events e join events f on e.person_id = f.person_id where {filters}",
                SqlTimeWindow(start=NOW - timedelta(days=30), end=NOW - timedelta(days=2)),
                SqlWindowClass.NO_TIME_FILTER,
            ),
            (
                "filters_date_range_placeholders",
                "select count() from events where timestamp >= {filters.dateRange.from} "
                "and timestamp <= {filters.dateRange.to}",
                SqlTimeWindow(start=NOW - timedelta(days=30), end=NOW - timedelta(days=2)),
                SqlWindowClass.FIXED_PAST,
            ),
        ]
    )
    def test_classifies_filters_placeholder(
        self, _name: str, sql: str, filters_window: Optional[SqlTimeWindow], expected: SqlWindowClass
    ) -> None:
        classifier = SqlWindowClassifier(now=NOW, timezone=ZoneInfo("UTC"), filters_window=filters_window)
        assert classifier.classify(parse_select(sql)).window_class == expected
