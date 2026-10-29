from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.parser import parse_select
from posthog.hogql.resolver import resolve_types

from posthog.hogql_queries.sql_cache_window import SqlFreshness, SqlFreshnessClassifier, SqlWindowClass

NOW = datetime(2026, 10, 29, 15, 0, tzinfo=UTC)
JUST_AFTER_MIDNIGHT = datetime(2026, 10, 29, 0, 30, tzinfo=UTC)
NEXT_MIDNIGHT = datetime(2026, 10, 30, tzinfo=UTC)
PAST_DAY = "select count() from events where timestamp >= '2026-10-28' and timestamp < '2026-10-29'"


class TestSqlFreshnessClassifier(BaseTest):
    database: Database

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.database = Database.create_for(team=cls.team)

    def _classify(
        self, sql: str, now: datetime = NOW, relative_date_range: bool = False, timezone: ZoneInfo | None = None
    ) -> SqlFreshness | None:
        context = HogQLContext(team_id=self.team.pk, database=self.database, enable_select_queries=True)
        resolved = resolve_types(parse_select(sql), context, dialect="hogql")
        classifier = SqlFreshnessClassifier(
            now=now, timezone=timezone or self.team.timezone_info, relative_date_range=relative_date_range
        )
        return classifier.classify(resolved)

    @parameterized.expand(
        [
            (
                "last_30_minutes",
                "select count() from events where timestamp > now() - interval 30 minute",
                SqlWindowClass.LIVE,
                NOW + timedelta(minutes=5),
            ),
            (
                "numeric_offset_is_seconds",
                "select count() from events where timestamp >= now() - 3600",
                SqlWindowClass.LIVE,
                NOW + timedelta(minutes=5),
            ),
            (
                "last_6_hours_with_alias",
                "select count() as c from events where timestamp >= now() - interval 6 hour order by c",
                SqlWindowClass.UP_TO_NOW_SHORT,
                NOW + timedelta(minutes=30),
            ),
            (
                "today",
                "select count() from events where toDate(timestamp) = today()",
                SqlWindowClass.UP_TO_NOW_SHORT,
                NOW + timedelta(minutes=30),
            ),
            (
                "last_7_days",
                "select event, count() from events where timestamp > now() - interval 7 day group by event",
                SqlWindowClass.UP_TO_NOW_LONG,
                NOW + timedelta(hours=1),
            ),
            (
                "through_today_is_not_past",
                "select count() from events where toDate(timestamp) <= today() and timestamp >= '2026-10-01'",
                SqlWindowClass.UP_TO_NOW_LONG,
                NOW + timedelta(hours=1),
            ),
            (
                "cte_of_events",
                "with recent as (select event from events where timestamp > now() - interval 7 day) "
                "select count() from recent",
                SqlWindowClass.UP_TO_NOW_LONG,
                NOW + timedelta(hours=1),
            ),
            (
                "or_without_time",
                "select count() from events where (event = 'a' or event = 'b') and timestamp > now() - interval 2 day",
                SqlWindowClass.UP_TO_NOW_LONG,
                NOW + timedelta(hours=1),
            ),
            (
                "absolute_past_range",
                "select count() from events where timestamp between '2026-10-01' and '2026-10-15'",
                SqlWindowClass.FIXED_PAST,
                NOW + timedelta(hours=24),
            ),
            (
                "yesterday_expires_at_midnight",
                "select count() from events where toDate(timestamp) = yesterday()",
                SqlWindowClass.FIXED_PAST,
                NEXT_MIDNIGHT,
            ),
            (
                "now_anchored_past_window_moves",
                "select count() from events where timestamp > now() - interval 9 day and timestamp < now() - interval 2 day",
                SqlWindowClass.FIXED_PAST,
                NOW + timedelta(hours=1),
            ),
            (
                "union_takes_the_freshest",
                "select count() from events where timestamp < '2026-10-01' and timestamp >= '2026-09-01' "
                "union all select count() from events where timestamp > now() - interval 10 minute",
                SqlWindowClass.LIVE,
                NOW + timedelta(minutes=5),
            ),
        ]
    )
    def test_grants_window_age(
        self, _name: str, sql: str, expected_window: SqlWindowClass, expected_fresh_until: datetime
    ) -> None:
        freshness = self._classify(sql)
        assert freshness is not None
        assert (freshness.window, freshness.fresh_until) == (expected_window, expected_fresh_until)

    @parameterized.expand(
        [
            ("no_time_filter", "select count() from events"),
            ("upper_bound_only", "select count() from events where timestamp < now()"),
            ("person_id_follows_merges", "select uniq(person_id) from events where timestamp > now() - interval 7 day"),
            (
                "person_properties",
                "select count() from events where timestamp > now() - interval 7 day and person.properties.email = 'a'",
            ),
            (
                "group_properties",
                "select count() from events where timestamp < '2026-10-01' and group_0.properties.plan = 'x'",
            ),
            (
                "revenue_join",
                "select poe.revenue_analytics.revenue from events "
                "where timestamp >= '2025-01-01' and timestamp < '2025-02-01'",
            ),
            ("clock_in_select_list", "select current_date(), count() from events where timestamp < '2025-01-01'"),
            ("shifted_timestamp", "select count() from events where subtractDays(timestamp, 30) < '2026-10-28'"),
            (
                "or_of_time_ranges",
                "select count() from events where timestamp > now() - interval 7 day or timestamp < '2020-01-01'",
            ),
            ("join", "select count() from events e join events f on e.uuid = f.uuid where e.timestamp > '2026-01-01'"),
            ("persons_table", "select count() from persons where created_at < '2025-01-01'"),
            (
                "timezone_on_a_non_literal",
                "select count() from events where timestamp < toDateTime(now(), 'America/Los_Angeles')",
            ),
        ]
    )
    def test_keeps_default_age(self, _name: str, sql: str) -> None:
        assert self._classify(sql) is None

    def test_unsettled_past_range_is_not_fixed(self) -> None:
        freshness = self._classify(PAST_DAY, now=JUST_AFTER_MIDNIGHT)
        assert freshness is not None
        assert freshness.window == SqlWindowClass.UP_TO_NOW_LONG

    def test_relative_filters_expire_at_midnight(self) -> None:
        freshness = self._classify(PAST_DAY, relative_date_range=True)
        assert freshness == SqlFreshness(window=SqlWindowClass.FIXED_PAST, fresh_until=NEXT_MIDNIGHT)

    @parameterized.expand(
        [
            ("morning_utc_yesterday_is_closed", datetime(2026, 10, 29, 15, 0, tzinfo=UTC), SqlWindowClass.FIXED_PAST),
            (
                "evening_utc_yesterday_is_the_local_today",
                datetime(2026, 10, 30, 3, 0, tzinfo=UTC),
                SqlWindowClass.UP_TO_NOW_SHORT,
            ),
        ]
    )
    def test_today_and_yesterday_follow_the_utc_day(self, _name: str, now: datetime, expected: SqlWindowClass) -> None:
        freshness = self._classify(
            "select count() from events where toDate(timestamp) = yesterday()",
            now=now,
            timezone=ZoneInfo("America/Los_Angeles"),
        )
        assert freshness is not None
        assert freshness.window == expected
