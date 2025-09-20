from posthog.test.base import _create_event, _create_person, flush_persons_and_events, snapshot_clickhouse_queries

from parameterized import parameterized

from posthog.schema import DateRange, HogQLQueryModifiers, WebStatsBreakdown, WebStatsTableQuery

from posthog.clickhouse.client.execute import sync_execute
from posthog.hogql_queries.web_analytics.stats_table import WebStatsTableQueryRunner
from posthog.hogql_queries.web_analytics.test.test_web_stats_table import FloatAwareTestCase
from posthog.hogql_queries.web_analytics.test.web_preaggregated_test_base import WebAnalyticsPreAggregatedTestBase
from posthog.models import Team
from posthog.models.utils import uuid7
from posthog.models.web_preaggregated.sql import (
    WEB_BOUNCES_DAILY_SQL,
    WEB_BOUNCES_HOURLY_SQL,
    WEB_BOUNCES_INSERT_SQL,
    WEB_STATS_DAILY_SQL,
    WEB_STATS_HOURLY_SQL,
    WEB_STATS_INSERT_SQL,
)


@snapshot_clickhouse_queries
class TestTimezonePreAggregatedIntegration(WebAnalyticsPreAggregatedTestBase, FloatAwareTestCase):
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
        # Create comprehensive hourly events across multiple days to showcase timezone shifts
        events = [
            # Day 1: Jan 14 - Events that will cross timezone boundaries
            ("2024-01-14T15:00:00Z", "Chrome", "user_0", "day1_afternoon"),  # JST midnight boundary
            ("2024-01-14T20:00:00Z", "Safari", "user_1", "day1_evening"),  # Creates PT/JST differences
            ("2024-01-14T23:59:00Z", "Firefox", "user_2", "day1_midnight"),  # Near UTC midnight
            # Day 2: Jan 15 - Main test day with hourly progression
            ("2024-01-15T00:00:00Z", "Chrome", "user_3", "day2_utc_midnight"),  # UTC midnight exactly
            ("2024-01-15T06:00:00Z", "Edge", "user_4", "day2_early"),  # PT prev day, JST afternoon
            ("2024-01-15T08:00:00Z", "Safari", "user_5", "day2_pt_midnight"),  # PT midnight exactly
            ("2024-01-15T12:00:00Z", "Firefox", "user_6", "day2_noon"),  # Universal midday
            ("2024-01-15T15:00:00Z", "Chrome", "user_7", "day2_jst_midnight"),  # JST next day midnight
            ("2024-01-15T18:00:00Z", "Edge", "user_8", "day2_evening"),  # PT morning, JST next day
            ("2024-01-15T20:00:00Z", "Safari", "user_9", "day2_pt_noon"),  # PT midday
            ("2024-01-15T23:30:00Z", "Firefox", "user_10", "day2_late"),  # End of UTC day
            # Day 3: Jan 16 - Events to test boundary crossover
            ("2024-01-16T01:00:00Z", "Chrome", "user_11", "day3_early"),  # Next day in all timezones
        ]

        sessions = [str(uuid7("2024-01-15")) for _ in range(len(events))]

        # Create users
        for i in range(len(events)):
            _create_person(team_id=team.pk, distinct_ids=[f"user_{i}"])

        # Create events with detailed properties for timezone analysis
        for i, (timestamp, browser, user_id, label) in enumerate(events):
            _create_event(
                team=team,
                event="$pageview",
                distinct_id=user_id,
                timestamp=timestamp,
                properties={
                    "$session_id": sessions[i],
                    "$current_url": f"https://example.com/{label}",
                    "$pathname": f"/{label}",
                    "$device_type": "Desktop" if i % 2 == 0 else "Mobile",
                    "$browser": browser,
                    "$os": "Windows" if browser == "Chrome" else "macOS" if browser == "Safari" else "Linux",
                    "test_label": label,
                    "utc_hour": timestamp.split("T")[1][:2],
                    "utc_date": timestamp.split("T")[0],
                },
            )

        flush_persons_and_events()

    def _populate_preaggregated_tables(self, team):
        stats_insert = WEB_STATS_INSERT_SQL(
            date_start="2024-01-14",  # Start earlier to catch cross-day timezone buckets
            date_end="2024-01-17",  # End later to catch cross-day timezone buckets
            team_ids=[team.pk],
            table_name="web_pre_aggregated_stats",
            granularity="hourly",
        )
        bounces_insert = WEB_BOUNCES_INSERT_SQL(
            date_start="2024-01-14",
            date_end="2024-01-17",
            team_ids=[team.pk],
            table_name="web_pre_aggregated_bounces",
            granularity="hourly",
        )

        sync_execute(stats_insert)
        sync_execute(bounces_insert)

    def _calculate_browser_breakdown(self, team):
        query = WebStatsTableQuery(
            dateRange=DateRange(date_from="2024-01-15", date_to="2024-01-16"),
            properties=[],
            breakdownBy=WebStatsBreakdown.BROWSER,
            limit=100,
        )

        # Run both pre-aggregated and raw queries for comparison
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

    # x[0] in the test context is the browser name as we're only dealing with browser breakdowns
    def _sort_results(self, results, key=lambda x: x[0] if x and len(x) > 0 else ""):
        return sorted(results, key=key)

    @parameterized.expand(
        [
            (
                "Pacific (UTC-08:00)",
                "America/Los_Angeles",
                # UTC-8: Large negative offset excludes some UTC events that fall on Jan 14 PT
                [
                    ["Chrome", (2.0, None), (2.0, None), 2 / 7, ""],
                    ["Edge", (1.0, None), (1.0, None), 1 / 7, ""],
                    ["Firefox", (2.0, None), (2.0, None), 2 / 7, ""],
                    ["Safari", (2.0, None), (2.0, None), 2 / 7, ""],
                ],
            ),
            (
                "New York (UTC-05:00)",
                "America/New_York",
                # UTC-5: Moderate negative offset still excludes some early UTC events
                [
                    ["Chrome", (2.0, None), (2.0, None), 0.25, ""],
                    ["Edge", (2.0, None), (2.0, None), 0.25, ""],
                    ["Firefox", (2.0, None), (2.0, None), 0.25, ""],
                    ["Safari", (2.0, None), (2.0, None), 0.25, ""],
                ],
            ),
            (
                "Sao Paulo (UTC-03:00)",
                "America/Sao_Paulo",
                # UTC-3: Similar to NYC, excludes 1 early UTC event that falls on Jan 14 local time
                [
                    ["Chrome", (2.0, None), (2.0, None), 0.25, ""],
                    ["Edge", (2.0, None), (2.0, None), 0.25, ""],
                    ["Firefox", (2.0, None), (2.0, None), 0.25, ""],
                    ["Safari", (2.0, None), (2.0, None), 0.25, ""],
                ],
            ),
            (
                "UTC (UTC+00:00)",
                "UTC",
                # UTC baseline: Jan 15 00:00-23:59 includes most events except those crossing to Jan 16
                [
                    ["Chrome", (3.0, None), (3.0, None), 1 / 3, ""],
                    ["Edge", (2.0, None), (2.0, None), 2 / 9, ""],
                    ["Firefox", (2.0, None), (2.0, None), 2 / 9, ""],
                    ["Safari", (2.0, None), (2.0, None), 2 / 9, ""],
                ],
            ),
            (
                "Berlin (UTC+01:00)",
                "Europe/Berlin",
                # UTC+1: Picks up 1 additional Firefox event compared to UTC due to shift
                [
                    ["Chrome", (3.0, None), (3.0, None), 0.3, ""],
                    ["Edge", (2.0, None), (2.0, None), 0.2, ""],
                    ["Firefox", (3.0, None), (3.0, None), 0.3, ""],
                    ["Safari", (2.0, None), (2.0, None), 0.2, ""],
                ],
            ),
            (
                "Cairo (UTC+02:00)",
                "Africa/Cairo",
                # UTC+2: Similar shift pattern to Berlin
                [
                    ["Chrome", (3.0, None), (3.0, None), 0.3, ""],
                    ["Edge", (2.0, None), (2.0, None), 0.2, ""],
                    ["Firefox", (3.0, None), (3.0, None), 0.3, ""],
                    ["Safari", (2.0, None), (2.0, None), 0.2, ""],
                ],
            ),
            (
                "Moscow (UTC+03:00)",
                "Europe/Moscow",
                # UTC+3: Similar shift pattern to Berlin/Cairo
                [
                    ["Chrome", (3.0, None), (3.0, None), 0.3, ""],
                    ["Edge", (2.0, None), (2.0, None), 0.2, ""],
                    ["Firefox", (3.0, None), (3.0, None), 0.3, ""],
                    ["Safari", (2.0, None), (2.0, None), 0.2, ""],
                ],
            ),
            (
                "Pakistan (UTC+05:00)",
                "Asia/Karachi",
                # UTC+5: Picks up 1 more event than Berlin/Cairo/Moscow (11 total vs 10)
                [
                    ["Chrome", (3.0, None), (3.0, None), 3 / 11, ""],
                    ["Edge", (2.0, None), (2.0, None), 2 / 11, ""],
                    ["Firefox", (3.0, None), (3.0, None), 3 / 11, ""],
                    ["Safari", (3.0, None), (3.0, None), 3 / 11, ""],
                ],
            ),
            (
                "Tokyo (UTC+09:00)",
                "Asia/Tokyo",
                # UTC+9: Large positive offset captures many events from Jan 14 UTC as Jan 15 JST
                [
                    ["Chrome", (4.0, None), (4.0, None), 1 / 3, ""],
                    ["Edge", (2.0, None), (2.0, None), 1 / 6, ""],
                    ["Firefox", (3.0, None), (3.0, None), 0.25, ""],
                    ["Safari", (3.0, None), (3.0, None), 0.25, ""],
                ],
            ),
            (
                "Sydney (UTC+11:00)",
                "Australia/Sydney",
                # UTC+11: Even larger offset, similar pattern to Tokyo
                [
                    ["Chrome", (4.0, None), (4.0, None), 1 / 3, ""],
                    ["Edge", (2.0, None), (2.0, None), 1 / 6, ""],
                    ["Firefox", (3.0, None), (3.0, None), 0.25, ""],
                    ["Safari", (3.0, None), (3.0, None), 0.25, ""],
                ],
            ),
            (
                "Auckland (UTC+12:00)",
                "Pacific/Auckland",
                # UTC+12: Maximum positive offset, captures most events from previous UTC day
                [
                    ["Chrome", (4.0, None), (4.0, None), 1 / 3, ""],
                    ["Edge", (2.0, None), (2.0, None), 1 / 6, ""],
                    ["Firefox", (3.0, None), (3.0, None), 0.25, ""],
                    ["Safari", (3.0, None), (3.0, None), 0.25, ""],
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
            comparison = self._calculate_browser_breakdown(team)

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

    def test_timezone_boundary_behavior_explicit(self):
        utc_team = self._create_timezone_team("UTC")
        pt_team = self._create_timezone_team("America/Los_Angeles")  # UTC-8
        jst_team = self._create_timezone_team("Asia/Tokyo")  # UTC+9

        try:
            # Create precise boundary events
            boundary_events = [
                # UTC Midnight boundary - Jan 15 00:00:00 UTC
                ("boundary_utc_midnight", "2024-01-15T00:00:00Z", "Chrome", "utc_midnight"),
                # PT Midnight boundary - Jan 15 00:00:00 PT = Jan 15 08:00:00 UTC
                ("boundary_pt_midnight", "2024-01-15T08:00:00Z", "Safari", "pt_midnight"),
                # JST Midnight boundary - Jan 15 00:00:00 JST = Jan 14 15:00:00 UTC
                ("boundary_jst_midnight", "2024-01-14T15:00:00Z", "Firefox", "jst_midnight"),
                # Cross-day event: 23:59 UTC Jan 14 (still Jan 14 in PT, but Jan 15 in JST)
                ("cross_day_edge", "2024-01-14T23:59:00Z", "Edge", "cross_day"),
            ]

            sessions = [str(uuid7("2024-01-15")) for _ in range(len(boundary_events))]

            # Create users and events for all teams
            for team in [utc_team, pt_team, jst_team]:
                for i in range(len(boundary_events)):
                    _create_person(team_id=team.pk, distinct_ids=[f"boundary_user_{i}"])

                for i, (_, timestamp, browser, label) in enumerate(boundary_events):
                    _create_event(
                        team=team,
                        event="$pageview",
                        distinct_id=f"boundary_user_{i}",
                        timestamp=timestamp,
                        properties={
                            "$session_id": sessions[i],
                            "$current_url": f"https://example.com/{label}",
                            "$pathname": f"/{label}",
                            "$browser": browser,
                            "boundary_test": label,  # Label for debugging
                            "utc_hour": timestamp.split("T")[1][:2],  # Extract hour for validation
                        },
                    )

            flush_persons_and_events()

            # Populate pre-aggregated tables for all teams
            for team in [utc_team, pt_team, jst_team]:
                self._populate_preaggregated_tables(team)

            # Test each team's results with explicit boundary expectations
            utc_comparison = self._calculate_browser_breakdown(utc_team)
            pt_comparison = self._calculate_browser_breakdown(pt_team)
            jst_comparison = self._calculate_browser_breakdown(jst_team)

            # UTC Team results for Jan 15 UTC (00:00 to 23:59 UTC)
            utc_expected = [
                ["Chrome", (1.0, None), (1.0, None), 0.5, ""],  # utc_midnight event
                ["Safari", (1.0, None), (1.0, None), 0.5, ""],  # pt_midnight event
            ]
            utc_actual = self._sort_results(utc_comparison["preagg_response"].results)
            assert utc_actual == self._sort_results(utc_expected), f"UTC boundary mismatch: {utc_actual}"

            # PT Team results for Jan 15 PT (08:00 UTC to 07:59+1 UTC)
            pt_expected = [
                ["Safari", (1.0, None), (1.0, None), 1.0, ""],  # pt_midnight event only
            ]
            pt_actual = self._sort_results(pt_comparison["preagg_response"].results)
            assert pt_actual == self._sort_results(pt_expected), f"PT boundary mismatch: {pt_actual}"

            # JST Team results for Jan 15 JST (15:00 UTC prev day to 14:59 UTC)
            jst_expected = [
                ["Chrome", (1.0, None), (1.0, None), 0.25, ""],  # utc_midnight event
                ["Edge", (1.0, None), (1.0, None), 0.25, ""],  # cross_day event
                ["Firefox", (1.0, None), (1.0, None), 0.25, ""],  # jst_midnight event
                ["Safari", (1.0, None), (1.0, None), 0.25, ""],  # pt_midnight event
            ]
            jst_actual = self._sort_results(jst_comparison["preagg_response"].results)
            assert jst_actual == self._sort_results(jst_expected), f"JST boundary mismatch: {jst_actual}"

            # Verify pre-aggregated and raw results match for boundary cases
            for team_name, comparison in [("UTC", utc_comparison), ("PT", pt_comparison), ("JST", jst_comparison)]:
                preagg_results = self._sort_results(comparison["preagg_response"].results)
                raw_results = self._sort_results(comparison["raw_response"].results)
                assert (
                    preagg_results == raw_results
                ), f"Boundary behavior mismatch in {team_name}: preagg={preagg_results} vs raw={raw_results}"

        finally:
            utc_team.delete()
            pt_team.delete()
            jst_team.delete()

    def test_india_half_hour_timezone_edge_case(self):
        """Test India's UTC+05:30 timezone to document half-hour offset data gaps.

        This test demonstrates a known limitation: half-hour timezones create data gaps
        in hourly pre-aggregated tables. Events occurring within the "missing" half-hour
        periods may be incorrectly bucketed when users expect IST-aligned hourly reports.
        """
        india_team = self._create_timezone_team("Asia/Kolkata")  # UTC+05:30

        try:
            # Create events strategically placed to demonstrate half-hour data gaps
            half_hour_events = [
                # IST Midnight: 2024-01-15 00:00:00 IST = 2024-01-14 18:30:00 UTC
                ("2024-01-14T18:30:00Z", "Chrome", "user_0", "ist_midnight"),
                # IST 12:30 PM: Falls on the half-hour, demonstrating potential bucketing issues
                ("2024-01-15T07:00:00Z", "Safari", "user_1", "ist_1230pm"),
                # IST 6:00 PM: On the hour in IST, should bucket correctly
                ("2024-01-15T12:30:00Z", "Firefox", "user_2", "ist_6pm"),
                # IST 11:30 PM: Another half-hour boundary case
                ("2024-01-15T18:00:00Z", "Edge", "user_3", "ist_1130pm"),
                # Edge case: 23:45 IST (almost midnight next day)
                ("2024-01-15T18:15:00Z", "Chrome", "user_4", "ist_2345"),
            ]

            sessions = [str(uuid7("2024-01-15")) for _ in range(len(half_hour_events))]

            for i in range(len(half_hour_events)):
                _create_person(team_id=india_team.pk, distinct_ids=[f"user_{i}"])

            for i, (timestamp, browser, user_id, label) in enumerate(half_hour_events):
                _create_event(
                    team=india_team,
                    event="$pageview",
                    distinct_id=user_id,
                    timestamp=timestamp,
                    properties={
                        "$session_id": sessions[i],
                        "$current_url": f"https://example.com/{label}",
                        "$pathname": f"/{label}",
                        "$browser": browser,
                        "half_hour_test": label,
                        "ist_offset": "+05:30",
                        "utc_time": timestamp,
                        "ist_equivalent": f"IST business hour for {label}",
                    },
                )

            flush_persons_and_events()
            self._populate_preaggregated_tables(india_team)

            comparison = self._calculate_browser_breakdown(india_team)
            results = self._sort_results(comparison["preagg_response"].results)

            # We created 5 events but expect only 4 in the Jan 15 IST query results
            # The missing event demonstrates half-hour timezone bucketing limitations
            #
            # The issue is: If a user in India queries for "9 AM to 10 AM IST" data,
            # they won't get intuitive results because the system buckets by UTC hours.
            # For India (UTC+05:30), this creates a 30-minute offset in all hourly reports
            # and is more visible in trends when the period_bucket is used to group by.
            #
            # Example: IST 9:00 AM = 03:30 UTC, so "9 AM IST hour" data is split across
            # two UTC hours: some in the 03:00 UTC bucket, some in the 04:00 UTC bucket.

            # For this test, we focus on documenting that aggregates work correctly
            # but the underlying hourly bucketing limitation exists

            # Document the discrepancy: pre-aggregated vs raw results may differ for half-hour timezones
            preagg_results = self._sort_results(comparison["preagg_response"].results)
            raw_results = self._sort_results(comparison["raw_response"].results)

            total_events_created = len(half_hour_events)
            assert total_events_created == 5, f"Should have created 5 events, got {total_events_created}"

            # One event falls outside the Jan 15 IST date range due to UTC bucketing
            # IST Midnight (18:30 UTC Jan 14) gets bucketed to Jan 14 in the query range
            expected_results = [
                ["Chrome", (1.0, None), (1.0, None), 0.25, ""],  # Only 1 Chrome event in range
                ["Edge", (1.0, None), (1.0, None), 0.25, ""],  # 1 Edge event in range
                ["Firefox", (1.0, None), (1.0, None), 0.25, ""],  # 1 Firefox event in range
                ["Safari", (1.0, None), (1.0, None), 0.25, ""],  # 1 Safari event in range
            ]

            total_events_in_results = sum(row[1][0] for row in expected_results)  # type: ignore[index]

            assert results == self._sort_results(expected_results)

            # Assert we're missing exactly 1 event due to half-hour timezone bucketing
            assert total_events_in_results == 4
            assert total_events_created - total_events_in_results == 1

            # Chrome should have 2 events in raw (both Chrome events) but only 1 in pre-aggregated
            chrome_preagg = next((row for row in preagg_results if row[0] == "Chrome"), None)
            chrome_raw = next((row for row in raw_results if row[0] == "Chrome"), None)

            assert chrome_preagg and chrome_raw
            assert chrome_preagg[1][0] == 1.0
            assert chrome_raw[1][0] == 2.0

        finally:
            india_team.delete()
