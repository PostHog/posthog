from posthog.models import Team
from parameterized import parameterized

from posthog.clickhouse.client.execute import sync_execute
from posthog.models.web_preaggregated.sql import (
    WEB_STATS_INSERT_SQL,
    WEB_BOUNCES_INSERT_SQL,
    WEB_STATS_DAILY_SQL,
    WEB_STATS_HOURLY_SQL,
    WEB_BOUNCES_DAILY_SQL,
    WEB_BOUNCES_HOURLY_SQL,
)
from posthog.models.utils import uuid7
from posthog.hogql_queries.web_analytics.test.web_preaggregated_test_base import WebAnalyticsPreAggregatedTestBase
from posthog.test.base import (
    _create_event,
    _create_person,
    flush_persons_and_events,
    snapshot_clickhouse_queries,
)
from posthog.hogql_queries.web_analytics.stats_table import WebStatsTableQueryRunner
from posthog.schema import (
    DateRange,
    WebStatsTableQuery,
    WebStatsBreakdown,
    HogQLQueryModifiers,
)


@snapshot_clickhouse_queries
class TestTimezonePreAggregatedIntegration(WebAnalyticsPreAggregatedTestBase):
    """
    Test timezone-aware hourly bucketing in pre-aggregated tables.
    All tests use BROWSER breakdown but with different team timezones.
    """

    def setUp(self):
        super().setUp()
        self._create_test_tables()

    def _create_test_tables(self):
        sync_execute(WEB_STATS_DAILY_SQL())
        sync_execute(WEB_BOUNCES_DAILY_SQL())
        sync_execute(WEB_STATS_HOURLY_SQL())
        sync_execute(WEB_BOUNCES_HOURLY_SQL())

    def _setup_test_data(self):
        """Required by WebAnalyticsPreAggregatedTestBase. Each test handles its own data setup."""
        pass

    def _create_timezone_team(self, timezone_name: str):
        return Team.objects.create(
            organization=self.organization, name=f"Team {timezone_name.replace('/', '_')}", timezone=timezone_name
        )

    def _setup_cross_timezone_test_data(self, team):
        sessions = [str(uuid7("2024-01-15")) for _ in range(4)]

        for i in range(4):
            _create_person(team_id=team.pk, distinct_ids=[f"user_{i}"])

        # Create events at specific UTC times that will bucket differently in different timezones
        # 2024-01-15 06:00:00 UTC = 22:00 PT (prev day) / 15:00 JST / 06:00 UTC
        _create_event(
            team=team,
            event="$pageview",
            distinct_id="user_0",
            timestamp="2024-01-15T06:00:00Z",
            properties={
                "$session_id": sessions[0],
                "$current_url": "https://example.com/early",
                "$pathname": "/early",
                "$device_type": "Desktop",
                "$browser": "Chrome",
                "$os": "Windows",
            },
        )

        # 2024-01-15 12:00:00 UTC = 04:00 PT / 21:00 JST / 12:00 UTC
        _create_event(
            team=team,
            event="$pageview",
            distinct_id="user_1",
            timestamp="2024-01-15T12:00:00Z",
            properties={
                "$session_id": sessions[1],
                "$current_url": "https://example.com/noon",
                "$pathname": "/noon",
                "$device_type": "Mobile",
                "$browser": "Safari",
                "$os": "iOS",
            },
        )

        # 2024-01-15 18:00:00 UTC = 10:00 PT / 03:00 JST (next day) / 18:00 UTC
        _create_event(
            team=team,
            event="$pageview",
            distinct_id="user_2",
            timestamp="2024-01-15T18:00:00Z",
            properties={
                "$session_id": sessions[2],
                "$current_url": "https://example.com/evening",
                "$pathname": "/evening",
                "$device_type": "Desktop",
                "$browser": "Firefox",
                "$os": "macOS",
            },
        )

        # 2024-01-15 23:00:00 UTC = 15:00 PT / 08:00 JST (next day) / 23:00 UTC
        _create_event(
            team=team,
            event="$pageview",
            distinct_id="user_3",
            timestamp="2024-01-15T23:00:00Z",
            properties={
                "$session_id": sessions[3],
                "$current_url": "https://example.com/late",
                "$pathname": "/late",
                "$device_type": "Desktop",
                "$browser": "Chrome",
                "$os": "Windows",
            },
        )

        flush_persons_and_events()

    def _populate_preaggregated_tables(self, team):
        stats_insert = WEB_STATS_INSERT_SQL(
            date_start="2024-01-14",  # Start earlier to catch cross-day timezone buckets
            date_end="2024-01-17",  # End later to catch cross-day timezone buckets
            team_ids=[team.pk],
            granularity="hourly",
        )
        bounces_insert = WEB_BOUNCES_INSERT_SQL(
            date_start="2024-01-14",
            date_end="2024-01-17",
            team_ids=[team.pk],
            granularity="hourly",
        )

        sync_execute(stats_insert)
        sync_execute(bounces_insert)

    def _calculate_browser_breakdown(self, team, compare_approaches=False):
        query = WebStatsTableQuery(
            dateRange=DateRange(date_from="2024-01-15", date_to="2024-01-16"),
            properties=[],
            breakdownBy=WebStatsBreakdown.BROWSER,
            limit=100,
        )

        if compare_approaches:
            # Run both pre-aggregated and raw queries
            preagg_modifiers = HogQLQueryModifiers(useWebAnalyticsPreAggregatedTables=True)
            raw_modifiers = HogQLQueryModifiers(useWebAnalyticsPreAggregatedTables=False)

            preagg_runner = WebStatsTableQueryRunner(query=query, team=team, modifiers=preagg_modifiers)
            raw_runner = WebStatsTableQueryRunner(query=query, team=team, modifiers=raw_modifiers)

            preagg_response = preagg_runner.calculate()
            raw_response = raw_runner.calculate()

            return {
                "preagg_response": preagg_response,
                "raw_response": raw_response,
                "preagg_used": preagg_runner.used_preaggregated_tables,
                "raw_used": raw_runner.used_preaggregated_tables,
            }
        else:
            # Single pre-aggregated query (original behavior)
            modifiers = HogQLQueryModifiers(useWebAnalyticsPreAggregatedTables=True)
            runner = WebStatsTableQueryRunner(query=query, team=team, modifiers=modifiers)
            return runner.calculate()

    @parameterized.expand(
        [
            (
                "UTC (UTC+00:00)",
                "UTC",
                # UTC timezone: all 4 events fall within 2024-01-15 in UTC
                [
                    ["Chrome", (2.0, None), (2.0, None), ""],  # user_0, user_3
                    ["Firefox", (1.0, None), (1.0, None), ""],  # user_2
                    ["Safari", (1.0, None), (1.0, None), ""],  # user_1
                ],
            ),
            (
                "Pacific (UTC-08:00)",
                "America/Los_Angeles",
                # Pacific timezone: 06:00 UTC = 22:00 PT (prev day), so only 3 events in date range
                [
                    ["Chrome", (1.0, None), (1.0, None), ""],  # user_3 only (user_0 is prev day in PT)
                    ["Firefox", (1.0, None), (1.0, None), ""],  # user_2
                    ["Safari", (1.0, None), (1.0, None), ""],  # user_1
                ],
            ),
            (
                "Tokyo (UTC+09:00)",
                "Asia/Tokyo",
                # Tokyo timezone: All events appear to be included in the date range
                [
                    ["Chrome", (2.0, None), (2.0, None), ""],  # user_0, user_3
                    ["Firefox", (1.0, None), (1.0, None), ""],  # user_2
                    ["Safari", (1.0, None), (1.0, None), ""],  # user_1
                ],
            ),
            (
                "London (UTC+00:00)",
                "Europe/London",
                # London timezone in January = UTC+0 (GMT), same as UTC
                [
                    ["Chrome", (2.0, None), (2.0, None), ""],  # user_0, user_3
                    ["Firefox", (1.0, None), (1.0, None), ""],  # user_2
                    ["Safari", (1.0, None), (1.0, None), ""],  # user_1
                ],
            ),
            (
                "Sydney (UTC+11:00)",
                "Australia/Sydney",
                # Sydney timezone: All events appear to be included in the date range
                [
                    ["Chrome", (2.0, None), (2.0, None), ""],  # user_0, user_3
                    ["Firefox", (1.0, None), (1.0, None), ""],  # user_2
                    ["Safari", (1.0, None), (1.0, None), ""],  # user_1
                ],
            ),
        ]
    )
    def test_timezone_hourly_bucketing(self, test_name, timezone_name, expected_results):
        team = self._create_timezone_team(timezone_name)

        try:
            self._setup_cross_timezone_test_data(team)
            self._populate_preaggregated_tables(team)

            # Test both pre-aggregated and raw queries
            comparison = self._calculate_browser_breakdown(team, compare_approaches=True)

            preagg_results = self._sort_results(comparison["preagg_response"].results)
            raw_results = self._sort_results(comparison["raw_response"].results)

            assert preagg_results == self._sort_results(expected_results)
            assert preagg_results == raw_results, (
                f"Timezone {timezone_name}: Pre-aggregated and raw results differ\n"
                f"Pre-agg: {preagg_results}\n"
                f"Raw: {raw_results}"
            )

            # Verify query routing worked correctly
            assert comparison["preagg_used"]
            assert not comparison["raw_used"]

        finally:
            team.delete()

    def test_timezone_consistency_verification(self):
        utc_team = self._create_timezone_team("UTC")
        pt_team = self._create_timezone_team("America/Los_Angeles")

        try:
            self._setup_cross_timezone_test_data(utc_team)
            self._setup_cross_timezone_test_data(pt_team)

            self._populate_preaggregated_tables(utc_team)
            self._populate_preaggregated_tables(pt_team)

            utc_response = self._calculate_browser_breakdown(utc_team)
            pt_response = self._calculate_browser_breakdown(pt_team)

            # Extract total pageviews
            utc_total = sum(result[2][0] for result in utc_response.results if result[2][0] is not None)
            pt_total = sum(result[2][0] for result in pt_response.results if result[2][0] is not None)

            # UTC should see all 4 events, PT should see only 3 (one event is in prev day PT)
            assert utc_total == 4.0
            assert pt_total == 3.0

            # Both should use pre-aggregated tables
            assert utc_response.usedPreAggregatedTables
            assert pt_response.usedPreAggregatedTables

        finally:
            utc_team.delete()
            pt_team.delete()
