from datetime import UTC, datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.hogql.parser import parse_select

from posthog.hogql_queries.sql_cache_window import SqlTimeWindow, SqlWindowClass, SqlWindowClassifier

NOW = datetime(2026, 10, 29, 15, 0, tzinfo=UTC)
LOS_ANGELES = ZoneInfo("America/Los_Angeles")
ABSOLUTE_PAST_WINDOW = SqlTimeWindow(
    start=NOW - timedelta(days=30), end=NOW - timedelta(days=2), start_absolute=True, end_absolute=True
)
RELATIVE_PAST_WINDOW = SqlTimeWindow(start=NOW - timedelta(days=30), end=NOW - timedelta(days=2))


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
                "yesterday_follows_the_clock",
                "select count() from events where toDate(timestamp) = yesterday()",
                SqlWindowClass.UP_TO_NOW_LONG,
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
                "select count() from (select distinct_id from events where timestamp > now() - interval 7 day) e "
                "join persons p on p.id = e.distinct_id",
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
                SqlWindowClass.UP_TO_NOW_LONG,
            ),
            (
                "exclusive_upper_bound_on_absolute_date",
                "select count() from events where toDate(timestamp) >= '2026-10-01' and toDate(timestamp) < '2026-10-15'",
                SqlWindowClass.FIXED_PAST,
            ),
            (
                "sliding_now_relative_end_is_never_fixed_past",
                "select count() from events where timestamp < now() - interval 2 day",
                SqlWindowClass.NO_TIME_FILTER,
            ),
            (
                "sliding_between_is_never_fixed_past",
                "select count() from events where timestamp between now() - interval 3 day and now() - interval 2 day",
                SqlWindowClass.UP_TO_NOW_LONG,
            ),
            (
                "sliding_now_relative_start_with_absolute_end_is_never_fixed_past",
                "select count() from events where timestamp >= now() - interval 30 day and timestamp < '2026-10-01'",
                SqlWindowClass.UP_TO_NOW_LONG,
            ),
            (
                "today_minus_days_end_is_never_fixed_past",
                "select count() from events where toDate(timestamp) >= '2026-10-01' and toDate(timestamp) <= today() - 3",
                SqlWindowClass.UP_TO_NOW_LONG,
            ),
            (
                "clock_in_select_list_is_never_fixed_past",
                "select dateDiff('day', timestamp, now()), count() from events where timestamp < '2025-01-01' group by 1",
                SqlWindowClass.NO_TIME_FILTER,
            ),
            (
                "clock_in_select_list_with_absolute_range",
                "select dateDiff('day', timestamp, now()), count() from events "
                "where timestamp >= '2025-01-01' and timestamp < '2025-02-01' group by 1",
                SqlWindowClass.UP_TO_NOW_LONG,
            ),
            (
                "clock_in_having_is_never_fixed_past",
                "select event, count() as total from events "
                "where timestamp >= '2025-01-01' and timestamp < '2025-02-01' group by event having max(timestamp) < today()",
                SqlWindowClass.UP_TO_NOW_LONG,
            ),
            (
                "clock_in_join_condition_is_never_fixed_past",
                "select count() from events e join events f on e.distinct_id = f.distinct_id and f.timestamp < now() "
                "where e.timestamp >= '2025-01-01' and e.timestamp < '2025-02-01' "
                "and f.timestamp >= '2025-01-01' and f.timestamp < '2025-02-01'",
                SqlWindowClass.UP_TO_NOW_LONG,
            ),
            (
                "scalar_cte_shadows_the_time_column",
                "with toDateTime('2020-01-01') as event_time "
                "select count() from events where event_time < '2025-01-01'",
                SqlWindowClass.UNCLASSIFIED,
            ),
            (
                "scalar_cte_hides_the_clock",
                "with now() as cutoff select count() from events "
                "where timestamp >= '2025-01-01' and timestamp < '2025-02-01' and timestamp < cutoff",
                SqlWindowClass.UNCLASSIFIED,
            ),
            (
                "group_property_on_historic_events",
                "select count() from events where timestamp >= '2025-01-01' and timestamp < '2025-02-01' "
                "and group_0.properties.plan = 'paid'",
                SqlWindowClass.NO_TIME_FILTER,
            ),
            (
                "group_key_column_on_historic_events",
                "select count() from events where timestamp >= '2025-01-01' and timestamp < '2025-02-01' "
                "and $group_0 = 'acme'",
                SqlWindowClass.NO_TIME_FILTER,
            ),
            (
                "person_property_on_historic_events",
                "select count() from events where timestamp >= '2025-01-01' and timestamp < '2025-02-01' "
                "and person.properties.email = 'a@example.com'",
                SqlWindowClass.NO_TIME_FILTER,
            ),
            (
                "aliased_person_property_on_historic_events",
                "select count() from events e where e.timestamp >= '2025-01-01' and e.timestamp < '2025-02-01' "
                "and e.person.properties.email = 'a@example.com'",
                SqlWindowClass.NO_TIME_FILTER,
            ),
            (
                "person_id_in_select_list_of_historic_events",
                "select person_id, count() from events where timestamp >= '2025-01-01' and timestamp < '2025-02-01' "
                "group by person_id",
                SqlWindowClass.NO_TIME_FILTER,
            ),
            (
                "session_property_on_historic_events",
                "select count() from events where timestamp >= '2025-01-01' and timestamp < '2025-02-01' "
                "and session.$session_duration > 10",
                SqlWindowClass.NO_TIME_FILTER,
            ),
            (
                "stored_event_columns_keep_the_window",
                "select count(distinct distinct_id) from events where timestamp >= '2025-01-01' and timestamp < '2025-02-01' "
                "and poe.properties.plan = 'paid' and person_properties like '%paid%'",
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
                "select count() from events e join events f on e.distinct_id = f.distinct_id "
                "where e.timestamp >= '2025-01-01' and e.timestamp < '2025-02-01' "
                "and f.timestamp >= '2025-01-01' and f.timestamp < '2025-02-01'",
                SqlWindowClass.FIXED_PAST,
            ),
            (
                "joined_events_alias_without_bound",
                "select count() from events e join events f on e.distinct_id = f.distinct_id "
                "where e.timestamp >= '2025-01-01' and e.timestamp < '2025-02-01'",
                SqlWindowClass.NO_TIME_FILTER,
            ),
            (
                "ambiguous_column_in_join",
                "select count() from events e join events f on e.distinct_id = f.distinct_id where timestamp < '2025-01-01'",
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
                "select count() from events e join persons p on e.distinct_id = p.id "
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
                "today_when_the_server_date_is_ahead_of_the_project_date",
                datetime(2026, 10, 29, 3, 0, tzinfo=UTC),
                "select count() from events where timestamp >= today()",
                SqlWindowClass.LIVE,
            ),
            (
                "yesterday_when_the_server_date_is_ahead_of_the_project_date",
                datetime(2026, 10, 29, 3, 0, tzinfo=UTC),
                "select count() from events where timestamp >= yesterday()",
                SqlWindowClass.UP_TO_NOW_SHORT,
            ),
            (
                "today_after_project_midnight",
                datetime(2026, 10, 29, 12, 0, tzinfo=UTC),
                "select count() from events where timestamp >= today()",
                SqlWindowClass.UP_TO_NOW_SHORT,
            ),
            (
                "yesterday_after_project_midnight",
                datetime(2026, 10, 29, 12, 0, tzinfo=UTC),
                "select count() from events where timestamp >= yesterday()",
                SqlWindowClass.UP_TO_NOW_LONG,
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
                "absolute_end_cached_hours_before_the_settle_buffer",
                "select count() from events where timestamp >= '2026-10-01' and timestamp < '2026-10-29'",
                datetime(2026, 10, 28, 17, 41, tzinfo=UTC),
                SqlWindowClass.UP_TO_NOW_LONG,
            ),
            (
                "yesterday_follows_the_clock_whenever_it_was_cached",
                "select count() from events where toDate(timestamp) = yesterday()",
                datetime(2026, 10, 29, 10, 0, tzinfo=UTC),
                SqlWindowClass.UP_TO_NOW_LONG,
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
                ABSOLUTE_PAST_WINDOW,
                SqlWindowClass.FIXED_PAST,
            ),
            (
                "relative_past_range_is_never_fixed_past",
                "select count() from events where {filters}",
                RELATIVE_PAST_WINDOW,
                SqlWindowClass.UP_TO_NOW_LONG,
            ),
            (
                "relative_end_with_absolute_start_is_never_fixed_past",
                "select count() from events where {filters}",
                SqlTimeWindow(start=NOW - timedelta(days=30), end=NOW - timedelta(days=1), start_absolute=True),
                SqlWindowClass.UP_TO_NOW_LONG,
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
                ABSOLUTE_PAST_WINDOW,
                SqlWindowClass.NO_TIME_FILTER,
            ),
            (
                "bound_filters_timestamp_column",
                "select count() from events where {filters(timestamp AS timestamp)}",
                ABSOLUTE_PAST_WINDOW,
                SqlWindowClass.FIXED_PAST,
            ),
            (
                "bound_filters_computed_timestamp",
                "select count() from events where {filters(coalesce(timestamp, now()) AS timestamp)}",
                ABSOLUTE_PAST_WINDOW,
                SqlWindowClass.UNCLASSIFIED,
            ),
            (
                "filters_in_join_without_a_single_table",
                "select count() from events e join events f on e.distinct_id = f.distinct_id where {filters}",
                ABSOLUTE_PAST_WINDOW,
                SqlWindowClass.UNCLASSIFIED,
            ),
            (
                "filters_in_join_does_not_leave_an_earlier_explicit_start_in_charge",
                "select count() from events e join events f on e.person_id = f.person_id "
                "where {filters} and e.timestamp >= now() - interval 7 day",
                SqlTimeWindow(start=NOW - timedelta(hours=1), end=None),
                SqlWindowClass.UNCLASSIFIED,
            ),
            (
                "filters_date_range_placeholders",
                "select count() from events where timestamp >= {filters.dateRange.from} "
                "and timestamp <= {filters.dateRange.to}",
                ABSOLUTE_PAST_WINDOW,
                SqlWindowClass.FIXED_PAST,
            ),
            (
                "relative_filters_date_range_placeholders",
                "select count() from events where timestamp >= {filters.dateRange.from} "
                "and timestamp <= {filters.dateRange.to}",
                RELATIVE_PAST_WINDOW,
                SqlWindowClass.UP_TO_NOW_LONG,
            ),
        ]
    )
    def test_classifies_filters_placeholder(
        self, _name: str, sql: str, filters_window: Optional[SqlTimeWindow], expected: SqlWindowClass
    ) -> None:
        classifier = SqlWindowClassifier(now=NOW, timezone=ZoneInfo("UTC"), filters_window=filters_window)
        assert classifier.classify(parse_select(sql)).window_class == expected

    @parameterized.expand(
        [
            ("filter_properties_set", True, SqlWindowClass.NO_TIME_FILTER),
            ("no_filter_properties", False, SqlWindowClass.FIXED_PAST),
        ]
    )
    def test_filters_with_properties_can_reach_mutable_data(
        self, _name: str, filters_read_mutable_data: bool, expected: SqlWindowClass
    ) -> None:
        classifier = SqlWindowClassifier(
            now=NOW,
            timezone=ZoneInfo("UTC"),
            filters_window=ABSOLUTE_PAST_WINDOW,
            filters_read_mutable_data=filters_read_mutable_data,
        )
        assert classifier.classify(parse_select("select count() from events where {filters}")).window_class == expected
