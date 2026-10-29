from datetime import UTC, datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.hogql.parser import parse_select

from posthog.hogql_queries.sql_cache_window import SqlTimeWindow, SqlWindowClass, SqlWindowClassifier

NOW = datetime(2026, 10, 29, 15, 0, tzinfo=UTC)


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
                "select count() from persons where created_at < '2025-01-01' and last_seen_at > now() - interval 10 minute",
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
        ]
    )
    def test_classifies_sql(self, _name: str, sql: str, expected: SqlWindowClass) -> None:
        classifier = SqlWindowClassifier(now=NOW, timezone=ZoneInfo("UTC"), filters_window=None)
        assert classifier.classify(parse_select(sql)) == expected

    @parameterized.expand(
        [
            ("relative_range", SqlTimeWindow(start=NOW - timedelta(days=7), end=None), SqlWindowClass.UP_TO_NOW_LONG),
            (
                "past_range",
                SqlTimeWindow(start=NOW - timedelta(days=30), end=NOW - timedelta(days=2)),
                SqlWindowClass.FIXED_PAST,
            ),
            ("no_date_range", None, SqlWindowClass.NO_TIME_FILTER),
        ]
    )
    def test_classifies_filters_placeholder(
        self, _name: str, filters_window: Optional[SqlTimeWindow], expected: SqlWindowClass
    ) -> None:
        classifier = SqlWindowClassifier(now=NOW, timezone=ZoneInfo("UTC"), filters_window=filters_window)
        assert classifier.classify(parse_select("select count() from events where {filters}")) == expected
