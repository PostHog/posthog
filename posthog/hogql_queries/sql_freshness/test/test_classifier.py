from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from posthog.test.base import APIBaseTest, BaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events

from parameterized import parameterized

from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query
from posthog.hogql.resolver import resolve_types

from posthog.hogql_queries.sql_freshness.classifier import SqlFreshness, classify, freshness_from_record
from posthog.hogql_queries.sql_freshness.facts import extract_facts
from posthog.hogql_queries.sql_freshness.rules import SQL_WINDOW_MAX_AGE, FreshnessReason, Reject, SqlWindowClass

NOW = datetime(2026, 10, 29, 15, 0, tzinfo=UTC)
AMSTERDAM = ZoneInfo("Europe/Amsterdam")
PAST_DAY = "select count() from events where timestamp >= '2026-10-28' and timestamp < '2026-10-29'"
ACCEPTED_BOUNDS = [
    ("date_literal", "'2026-03-29'", "Europe/Amsterdam"),
    ("datetime_literal", "'2026-03-29 03:30:00'", "Europe/Amsterdam"),
    ("utc_literal", "'2026-10-29T08:00:00Z'", "Europe/Amsterdam"),
    ("zoned_literal", "toDateTime('2026-10-29 08:00:00', 'Asia/Tokyo')", "UTC"),
    ("zoned_datetime64", "toDateTime64('2026-10-29 08:00:00', 6, 'Asia/Tokyo')", "UTC"),
    ("datetime64_with_precision_only", "toDateTime64('2026-10-29 08:00:00', 3)", "Europe/Amsterdam"),
    ("best_effort_with_offset", "parseDateTimeBestEffort('2026-10-29T08:00:00Z')", "Europe/Amsterdam"),
    ("best_effort_with_zone", "parseDateTimeBestEffort('2026-10-29 08:00:00', 'Asia/Tokyo')", "UTC"),
    ("epoch", "toDateTime(1761955200)", "Europe/Amsterdam"),
    ("from_unix_timestamp", "fromUnixTimestamp(1761955200)", "Europe/Amsterdam"),
    ("epoch_plus_a_day_across_a_fall_back", "toDateTime(1792836000) + interval 1 day", "Europe/Amsterdam"),
    ("from_unix_timestamp_plus_a_month", "fromUnixTimestamp(1769815800) + interval 1 month", "Europe/Amsterdam"),
    ("day_interval_across_a_fall_back", "toDateTime('2026-10-24 12:00:00') + interval 1 day", "Europe/Amsterdam"),
    ("hour_interval_across_a_fall_back", "toDateTime('2026-10-25 01:30:00') + interval 3 hour", "Europe/Amsterdam"),
    ("month_interval_at_a_month_end", "toDateTime('2026-01-31 12:00:00') + interval 1 month", "Europe/Amsterdam"),
    ("wall_time_in_a_dst_fold", "'2026-10-25 02:30:00'", "Europe/Amsterdam"),
    (
        "hour_interval_across_a_spring_forward",
        "toDateTime('2026-03-29 01:30:00') + interval 1 hour",
        "Europe/Amsterdam",
    ),
    ("now_minus_hours", "now() - interval 6 hour", "Europe/Amsterdam"),
    ("now_minus_days", "now() - interval 7 day", "Europe/Amsterdam"),
]


def _resolve(sql: str, team: Any) -> Any:
    context = HogQLContext(team_id=team.pk, database=Database.create_for(team=team), enable_select_queries=True)
    return resolve_types(parse_select(sql), context, dialect="hogql")


class TestClassify(BaseTest):
    def _classify(self, sql: str, now: datetime = NOW, timezone: Any = None) -> SqlFreshness | Reject:
        return classify(_resolve(sql, self.team), now=now, timezone=timezone or self.team.timezone_info)

    @parameterized.expand(
        [
            (
                "last_30_minutes",
                "select count() from events where timestamp > now() - interval 30 minute",
                SqlWindowClass.LIVE,
            ),
            (
                "last_6_hours_with_alias",
                "select count() as c from events where timestamp >= now() - interval 6 hour order by c",
                SqlWindowClass.UP_TO_NOW_SHORT,
            ),
            (
                "last_7_days",
                "select event, count() from events where timestamp > now() - interval 7 day group by event",
                SqlWindowClass.UP_TO_NOW_LONG,
            ),
            (
                "cte_of_events",
                "with recent as (select event from events where timestamp > now() - interval 7 day) "
                "select count() from recent",
                SqlWindowClass.UP_TO_NOW_LONG,
            ),
            (
                "or_without_time",
                "select count() from events where (event = 'a' or event = 'b') and timestamp > now() - interval 2 day",
                SqlWindowClass.UP_TO_NOW_LONG,
            ),
            (
                "person_id",
                "select uniq(person_id) from events where timestamp > now() - interval 7 day",
                SqlWindowClass.UP_TO_NOW_LONG,
            ),
            (
                "person_properties",
                "select count() from events where timestamp > now() - interval 7 day and person.properties.email = 'a'",
                SqlWindowClass.UP_TO_NOW_LONG,
            ),
            (
                "group_properties",
                "select count() from events where timestamp < '2026-10-01' and timestamp >= '2026-09-01' "
                "and group_0.properties.plan = 'x'",
                SqlWindowClass.FIXED_PAST,
            ),
            (
                "session_properties",
                "select count() from events where timestamp > now() - interval 2 day and session.$session_duration > 10",
                SqlWindowClass.UP_TO_NOW_LONG,
            ),
            (
                "absolute_past_range",
                "select count() from events where timestamp >= '2026-10-01' and timestamp <= '2026-10-15'",
                SqlWindowClass.FIXED_PAST,
            ),
            (
                "zoned_literal_uses_its_timezone",
                "select count() from events where timestamp >= '2026-10-01' "
                "and timestamp < toDateTime('2026-10-29 08:00:00', 'Asia/Tokyo')",
                SqlWindowClass.FIXED_PAST,
            ),
            (
                "epoch_seconds",
                "select count() from events where timestamp >= toDateTime(1759276800) "
                "and timestamp < fromUnixTimestamp(1760486400)",
                SqlWindowClass.FIXED_PAST,
            ),
            (
                "literal_plus_days",
                "select count() from events where timestamp >= toDateTime('2026-10-01 00:00:00') "
                "and timestamp < toDateTime('2026-10-01 00:00:00') + interval 14 day",
                SqlWindowClass.FIXED_PAST,
            ),
            (
                "now_anchored_past_window_moves",
                "select count() from events where timestamp > now() - interval 9 day and timestamp < now() - interval 2 day",
                SqlWindowClass.FIXED_PAST,
                {"fresh_until": NOW + timedelta(hours=1)},
            ),
            (
                "narrow_now_anchored_window_expires_within_its_width",
                "select count() from events where timestamp >= now() - interval 25 hour and timestamp < now() - interval 24 hour",
                SqlWindowClass.FIXED_PAST,
                {"fresh_until": NOW + timedelta(minutes=5)},
            ),
            (
                "latest_event_time_up_to_now",
                "select max(timestamp) from events where timestamp > now() - interval 2 day",
                SqlWindowClass.UP_TO_NOW_LONG,
                {"fresh_until": NOW + timedelta(minutes=5)},
            ),
            (
                "latest_rows_up_to_now",
                "select event from events where timestamp > now() - interval 7 day order by timestamp desc limit 10",
                SqlWindowClass.UP_TO_NOW_LONG,
                {"fresh_until": NOW + timedelta(minutes=5)},
            ),
            (
                "latest_rows_by_an_alias",
                "select timestamp as ts from events where timestamp > now() - interval 7 day order by ts desc limit 10",
                SqlWindowClass.UP_TO_NOW_LONG,
                {"fresh_until": NOW + timedelta(minutes=5)},
            ),
            (
                "latest_value_by_time",
                "select argMax(event, timestamp) from events where timestamp > now() - interval 7 day",
                SqlWindowClass.UP_TO_NOW_LONG,
                {"fresh_until": NOW + timedelta(minutes=5)},
            ),
            (
                "latest_event_time_with_a_condition",
                "select maxIf(timestamp, event = 'signup') from events where timestamp > now() - interval 7 day",
                SqlWindowClass.UP_TO_NOW_LONG,
                {"fresh_until": NOW + timedelta(minutes=5)},
            ),
            (
                "latest_value_in_a_window_function",
                "select last_value(event) over (partition by person_id order by timestamp) from events "
                "where timestamp > now() - interval 7 day",
                SqlWindowClass.UP_TO_NOW_LONG,
                {"fresh_until": NOW + timedelta(minutes=5)},
            ),
            (
                "latest_rows_by_position",
                "select timestamp, event from events where timestamp > now() - interval 7 day order by 1 desc limit 10",
                SqlWindowClass.UP_TO_NOW_LONG,
                {"fresh_until": NOW + timedelta(minutes=5)},
            ),
            (
                "latest_event_time_through_a_subquery",
                "select max(ts) from (select toStartOfMinute(timestamp) as ts from events "
                "where timestamp > now() - interval 7 day)",
                SqlWindowClass.UP_TO_NOW_LONG,
                {"fresh_until": NOW + timedelta(minutes=5)},
            ),
            (
                "latest_event_time_in_a_fixed_past_range",
                "select max(timestamp) from events where timestamp >= '2026-10-01' and timestamp < '2026-10-15'",
                SqlWindowClass.FIXED_PAST,
            ),
            (
                "union_takes_the_freshest",
                "select count() from events where timestamp < '2026-10-01' and timestamp >= '2026-09-01' "
                "union all select count() from events where timestamp > now() - interval 10 minute",
                SqlWindowClass.LIVE,
            ),
            (
                "unsettled_past_range",
                PAST_DAY,
                SqlWindowClass.UP_TO_NOW_LONG,
                {"now": datetime(2026, 10, 29, 0, 30, tzinfo=UTC)},
            ),
            (
                "age_counts_elapsed_time_across_a_dst_fall_back",
                "select count() from events where timestamp >= now() - interval 7 day",
                SqlWindowClass.UP_TO_NOW_LONG,
                {"timezone": AMSTERDAM, "now": datetime(2026, 10, 25, 0, 30, tzinfo=UTC)},
            ),
            (
                "hour_interval_counts_elapsed_time_across_a_dst_fall_back",
                "select count() from events where timestamp >= now() - interval 1 hour",
                SqlWindowClass.LIVE,
                {"timezone": AMSTERDAM, "now": datetime(2026, 10, 25, 1, 30, tzinfo=UTC)},
            ),
        ]
    )
    def test_grants_window_age(
        self, _name: str, sql: str, expected_window: SqlWindowClass, options: dict[str, Any] | None = None
    ) -> None:
        options = {"now": NOW, **(options or {})}
        expected_fresh_until = options.pop("fresh_until", options["now"] + SQL_WINDOW_MAX_AGE[expected_window])
        freshness = self._classify(sql, **options)
        assert isinstance(freshness, SqlFreshness)
        assert (freshness.window, freshness.fresh_until) == (expected_window, expected_fresh_until)

    @parameterized.expand(
        [
            ("no_time_filter", "select count() from events", FreshnessReason.UNBOUNDED),
            ("upper_bound_only", "select count() from events where timestamp < now()", FreshnessReason.UNBOUNDED),
            (
                "revenue_join",
                "select poe.revenue_analytics.revenue from events "
                "where timestamp >= '2025-01-01' and timestamp < '2025-02-01'",
                FreshnessReason.UNSUPPORTED_FIELD,
            ),
            (
                "clock_in_select_list",
                "select now(), count() from events where timestamp < '2025-01-01' and timestamp >= '2024-01-01'",
                FreshnessReason.CLOCK_OUTSIDE_BOUNDS,
            ),
            (
                "or_of_time_ranges",
                "select count() from events where timestamp > now() - interval 7 day or timestamp < '2020-01-01'",
                FreshnessReason.UNSUPPORTED_BOUND,
            ),
            (
                "today",
                "select count() from events where toDate(timestamp) = today()",
                FreshnessReason.UNSUPPORTED_BOUND,
            ),
            (
                "yesterday",
                "select count() from events where timestamp >= yesterday()",
                FreshnessReason.UNSUPPORTED_BOUND,
            ),
            (
                "truncated_column",
                "select count() from events where toStartOfMonth(timestamp) < '2026-10-01' and timestamp >= '2026-09-01'",
                FreshnessReason.UNSUPPORTED_BOUND,
            ),
            (
                "truncated_value",
                "select count() from events where timestamp >= toStartOfDay(now())",
                FreshnessReason.UNSUPPORTED_BOUND,
            ),
            (
                "shift_function",
                "select count() from events where timestamp >= subtractDays(now(), 3)",
                FreshnessReason.UNSUPPORTED_BOUND,
            ),
            (
                "integer_offset",
                "select count() from events where timestamp >= now() - 3600",
                FreshnessReason.UNSUPPORTED_BOUND,
            ),
            (
                "date_value",
                "select count() from events where timestamp >= '2026-10-01' and timestamp < toDate('2026-10-27')",
                FreshnessReason.UNSUPPORTED_BOUND,
            ),
            (
                "timezone_on_a_non_literal",
                "select count() from events where timestamp < toDateTime(now(), 'America/Los_Angeles') "
                "and timestamp >= '2026-01-01'",
                FreshnessReason.UNSUPPORTED_BOUND,
            ),
            (
                "join_after_a_subquery",
                "select count() from (select uuid from events where timestamp >= '2026-01-01' "
                "and timestamp < '2026-02-01') e cross join persons p",
                FreshnessReason.JOIN,
            ),
            (
                "join",
                "select count() from events e join events f on e.uuid = f.uuid where e.timestamp > '2026-01-01'",
                FreshnessReason.JOIN,
            ),
            (
                "persons_table",
                "select count() from persons where created_at < '2025-01-01'",
                FreshnessReason.UNSUPPORTED_FIELD,
            ),
            (
                "cohort_membership",
                "select count() from events where timestamp < '2026-10-01' and timestamp >= '2026-09-01' "
                "and person_id not in cohort 1",
                FreshnessReason.FOREIGN_SOURCE,
            ),
            (
                "string_plus_interval",
                "select count() from events where timestamp >= '2026-11-01' and timestamp < '2026-11-01' + interval 1 day",
                FreshnessReason.UNSUPPORTED_BOUND,
            ),
            (
                "before_the_datetime_range",
                "select count() from events where timestamp > toDateTime(0) - interval 1 second",
                FreshnessReason.UNSUPPORTED_BOUND,
            ),
            (
                "base_before_the_datetime_range",
                "select count() from events where timestamp >= toDateTime('1960-01-01 00:00:00') + interval 20 year",
                FreshnessReason.UNSUPPORTED_BOUND,
            ),
            (
                "after_the_datetime_range",
                "select count() from events where timestamp >= toDateTime('2100-01-01 00:00:00') + interval 10 year",
                FreshnessReason.UNSUPPORTED_BOUND,
            ),
            (
                "literal_at_the_year_limit",
                "select count() from events where timestamp >= '9999-12-31 23:00:00'",
                FreshnessReason.UNSUPPORTED_BOUND,
                ZoneInfo("America/New_York"),
            ),
            (
                "wall_time_in_a_dst_gap",
                "select count() from events where timestamp >= '2026-03-29 02:30:00'",
                FreshnessReason.UNSUPPORTED_BOUND,
                AMSTERDAM,
            ),
            (
                "hour_interval_into_a_repeated_dst_hour",
                "select count() from events where timestamp >= toDateTime('2026-10-25 01:30:00') + interval 2 hour",
                FreshnessReason.UNSUPPORTED_BOUND,
                AMSTERDAM,
            ),
            (
                "calendar_shift_into_a_dst_gap",
                "select count() from events where timestamp >= toDateTime('2026-03-28 02:30:00') + interval 1 day",
                FreshnessReason.UNSUPPORTED_BOUND,
                AMSTERDAM,
            ),
        ]
    )
    def test_keeps_default_age(
        self, _name: str, sql: str, expected_reason: FreshnessReason, timezone: Any = None
    ) -> None:
        assert self._classify(sql, timezone=timezone) == Reject(reason=expected_reason)

    def test_record_without_a_timezone_is_missing(self) -> None:
        assert (
            freshness_from_record({"window": "live", "fresh_until": "2026-10-29T15:05:00", "reason": "window_age"})
            is None
        )


class TestAcceptedBoundsMatchClickHouse(ClickhouseTestMixin, APIBaseTest):
    @parameterized.expand(
        [
            (f"{name}_{side}", value, timezone, side)
            for name, value, timezone in ACCEPTED_BOUNDS
            for side in ("start", "end")
        ]
    )
    def test_bound_matches_clickhouse(self, _name: str, value: str, timezone: str, side: str) -> None:
        self.team.timezone = timezone
        self.team.save()
        bound = f"{value} <= timestamp" if side == "start" else f"timestamp > toDateTime(0) and timestamp < {value}"
        sql = f"select count() from events where event = 'bound_check' and {bound}"
        window = extract_facts(
            _resolve(sql, self.team), now=datetime.now(UTC), timezone=self.team.timezone_info
        ).windows[0]
        at = window.start if side == "start" else window.end
        assert at is not None
        margin = timedelta(seconds=30 if "now()" in value else 1)
        for offset in (-margin, margin):
            _create_event(team=self.team, event="bound_check", distinct_id="d", timestamp=at + offset)
        flush_persons_and_events()
        assert execute_hogql_query(sql, team=self.team).results == [(1,)]
