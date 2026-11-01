import re
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.parser import parse_select
from posthog.hogql.resolver import resolve_types

from posthog.hogql_queries.sql_freshness.classifier import SqlFreshness, classify
from posthog.hogql_queries.sql_freshness.rules import SQL_WINDOW_MAX_AGE, FreshnessReason, Reject, SqlWindowClass

NOW = datetime(2026, 10, 29, 15, 0, tzinfo=UTC)
NEXT_MIDNIGHT = datetime(2026, 10, 30, tzinfo=UTC)
EVENING = datetime(2026, 10, 29, 20, 0, tzinfo=UTC)
LOS_ANGELES = ZoneInfo("America/Los_Angeles")
PAST_DAY = "select count() from events where timestamp >= '2026-10-28' and timestamp < '2026-10-29'"
YESTERDAY = "select count() from events where toDate(timestamp) = yesterday()"


GRANT_CASES: list[tuple[Any, ...]] = [
    (
        "last_30_minutes",
        "select count() from events where timestamp > now() - interval 30 minute",
        SqlWindowClass.LIVE,
    ),
    (
        "numeric_offset_is_seconds",
        "select count() from events where timestamp >= now() - 3600",
        SqlWindowClass.LIVE,
    ),
    (
        "last_6_hours_with_alias",
        "select count() as c from events where timestamp >= now() - interval 6 hour order by c",
        SqlWindowClass.UP_TO_NOW_SHORT,
    ),
    ("today", "select count() from events where toDate(timestamp) = today()", SqlWindowClass.UP_TO_NOW_SHORT),
    (
        "last_7_days",
        "select event, count() from events where timestamp > now() - interval 7 day group by event",
        SqlWindowClass.UP_TO_NOW_LONG,
    ),
    (
        "subtract_days",
        "select count() from events where timestamp >= subtractDays(now(), 3)",
        SqlWindowClass.UP_TO_NOW_LONG,
    ),
    (
        "through_today_is_not_past",
        "select count() from events where toDate(timestamp) <= today() and timestamp >= '2026-10-01'",
        SqlWindowClass.UP_TO_NOW_LONG,
    ),
    (
        "cte_of_events",
        "with recent as (select event from events where timestamp > now() - interval 7 day) select count() from recent",
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
        "truncated_bound_covers_its_whole_period",
        "select count() from events where toStartOfMonth(timestamp) < '2026-10-29' and timestamp >= '2026-09-01'",
        SqlWindowClass.UP_TO_NOW_LONG,
    ),
    (
        "truncated_bound_before_a_period_start_is_closed",
        "select count() from events where toStartOfMonth(timestamp) < '2026-10-01' and timestamp >= '2026-09-01'",
        SqlWindowClass.FIXED_PAST,
    ),
    (
        "truncated_lower_bound_starts_at_the_next_period",
        "select count() from events where toStartOfDay(timestamp) >= '2026-10-28 10:00:00'",
        SqlWindowClass.UP_TO_NOW_SHORT,
    ),
    (
        "truncated_strict_lower_bound_skips_its_period",
        "select count() from events where toStartOfDay(timestamp) > '2026-10-28'",
        SqlWindowClass.UP_TO_NOW_SHORT,
    ),
    (
        "truncation_keeps_the_value_timezone",
        "select count() from events where timestamp >= '2026-10-01' "
        "and timestamp < toStartOfDay(toDateTime('2026-10-29 12:00:00', 'America/Los_Angeles'))",
        SqlWindowClass.UP_TO_NOW_LONG,
        {"now": datetime(2026, 10, 29, 6, 0, tzinfo=UTC)},
    ),
    (
        "date_of_a_zoned_value_is_its_local_date",
        "select count() from events where timestamp >= '2026-10-01' "
        "and timestamp < toDate(toDateTime('2026-10-29 03:00:00', 'Asia/Tokyo'))",
        SqlWindowClass.UP_TO_NOW_LONG,
        {"now": datetime(2026, 10, 28, 23, 30, tzinfo=UTC)},
    ),
    (
        "absolute_past_range",
        "select count() from events where timestamp >= '2026-10-01' and timestamp <= '2026-10-15'",
        SqlWindowClass.FIXED_PAST,
    ),
    (
        "yesterday_expires_at_midnight",
        YESTERDAY,
        SqlWindowClass.FIXED_PAST,
        {"now": EVENING, "fresh_until": NEXT_MIDNIGHT},
    ),
    (
        "today_expires_at_midnight",
        "select count() from events where toDate(timestamp) = today()",
        SqlWindowClass.UP_TO_NOW_SHORT,
        {"now": datetime(2026, 10, 29, 23, 55, tzinfo=UTC), "fresh_until": NEXT_MIDNIGHT},
    ),
    (
        "relative_window_up_to_now_expires_at_midnight",
        "select count() from events where timestamp >= '2026-10-22'",
        SqlWindowClass.UP_TO_NOW_LONG,
        {
            "now": datetime(2026, 10, 29, 23, 30, tzinfo=UTC),
            "relative_inputs": True,
            "fresh_until": NEXT_MIDNIGHT,
        },
    ),
    (
        "now_anchored_past_window_moves",
        "select count() from events where timestamp > now() - interval 9 day and timestamp < now() - interval 2 day",
        SqlWindowClass.FIXED_PAST,
        {"fresh_until": NOW + timedelta(hours=1)},
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
        "relative_inputs_expire_within_the_hour",
        PAST_DAY,
        SqlWindowClass.FIXED_PAST,
        {"relative_inputs": True, "fresh_until": NOW + timedelta(hours=1)},
    ),
    (
        "today_bound_ends_at_the_project_midnight",
        "select count() from events where timestamp <= today() and timestamp >= '2026-10-01'",
        SqlWindowClass.UP_TO_NOW_LONG,
        {"timezone": LOS_ANGELES, "now": datetime(2026, 10, 29, 7, 5, tzinfo=UTC)},
    ),
    (
        "utc_yesterday_is_closed_during_the_local_day",
        YESTERDAY,
        SqlWindowClass.FIXED_PAST,
        {"timezone": LOS_ANGELES, "now": EVENING, "fresh_until": NEXT_MIDNIGHT},
    ),
    (
        "utc_yesterday_is_the_local_today_in_the_evening",
        YESTERDAY,
        SqlWindowClass.UP_TO_NOW_SHORT,
        {"timezone": LOS_ANGELES, "now": datetime(2026, 10, 30, 3, 0, tzinfo=UTC)},
    ),
]
CLOCK_CALL = re.compile(r"\b(now|today|yesterday)\(")
CLOCK_RELATIVE_CASES = [
    case for case in GRANT_CASES if CLOCK_CALL.search(case[1]) or (len(case) > 3 and case[3].get("relative_inputs"))
]


class TestClassify(BaseTest):
    database: Database

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.database = Database.create_for(team=cls.team)

    def _classify(
        self,
        sql: str,
        now: datetime = NOW,
        relative_inputs: bool = False,
        timezone: Any = None,
    ):
        context = HogQLContext(team_id=self.team.pk, database=self.database, enable_select_queries=True)
        return classify(
            resolve_types(parse_select(sql), context, dialect="hogql"),
            now=now,
            timezone=timezone or self.team.timezone_info,
            week_start_day=self.team.week_start_day,
            relative_inputs=relative_inputs,
        )

    @parameterized.expand(GRANT_CASES)
    def test_grants_window_age(
        self, _name: str, sql: str, expected_window: SqlWindowClass, options: dict[str, Any] | None = None
    ) -> None:
        options = options or {}
        now = options.get("now", NOW)
        freshness = self._classify(
            sql,
            now=now,
            relative_inputs=options.get("relative_inputs", False),
            timezone=options.get("timezone"),
        )
        assert isinstance(freshness, SqlFreshness)
        expected_fresh_until = options.get("fresh_until", now + SQL_WINDOW_MAX_AGE[expected_window])
        assert (freshness.window, freshness.fresh_until) == (expected_window, expected_fresh_until)

    @parameterized.expand(CLOCK_RELATIVE_CASES)
    def test_clock_relative_results_expire_by_midnight(
        self, _name: str, sql: str, _expected_window: SqlWindowClass, options: dict[str, Any] | None = None
    ) -> None:
        options = options or {}
        freshness = self._classify(
            sql,
            now=NEXT_MIDNIGHT - timedelta(minutes=5),
            relative_inputs=options.get("relative_inputs", False),
            timezone=options.get("timezone"),
        )
        assert isinstance(freshness, SqlFreshness)
        assert freshness.fresh_until <= NEXT_MIDNIGHT

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
                "select current_date(), count() from events where timestamp < '2025-01-01' and timestamp >= '2024-01-01'",
                FreshnessReason.CLOCK_OUTSIDE_BOUNDS,
            ),
            (
                "shifted_timestamp",
                "select count() from events where subtractDays(timestamp, 30) < '2026-10-28'",
                FreshnessReason.UNSUPPORTED_BOUND,
            ),
            (
                "or_of_time_ranges",
                "select count() from events where timestamp > now() - interval 7 day or timestamp < '2020-01-01'",
                FreshnessReason.UNSUPPORTED_BOUND,
            ),
            (
                "today_plus_hours",
                "select count() from events where timestamp < today() + interval 12 hour and timestamp >= '2026-10-01'",
                FreshnessReason.UNSUPPORTED_BOUND,
            ),
            (
                "join_after_a_subquery",
                "select count() from (select uuid from events where timestamp >= '2026-01-01' and timestamp < '2026-02-01') e "
                "cross join persons p",
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
                "timezone_on_a_non_literal",
                "select count() from events where timestamp < toDateTime(now(), 'America/Los_Angeles') "
                "and timestamp >= '2026-01-01'",
                FreshnessReason.UNSUPPORTED_BOUND,
            ),
        ]
    )
    def test_keeps_default_age(self, _name: str, sql: str, expected_reason: FreshnessReason) -> None:
        assert self._classify(sql) == Reject(reason=expected_reason)
