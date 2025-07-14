from freezegun import freeze_time

from posthog.clickhouse.client.execute import sync_execute
from posthog.models.utils import uuid7
from posthog.models.web_preaggregated.sql import WEB_STATS_INSERT_SQL
from posthog.hogql_queries.web_analytics.test.web_preaggregated_test_base import WebAnalyticsPreAggregatedTestBase
from posthog.test.base import _create_event, _create_person, flush_persons_and_events
from posthog.hogql_queries.web_analytics.stats_table import WebStatsTableQueryRunner
from posthog.schema import WebStatsTableQuery, DateRange, HogQLQueryModifiers, WebStatsBreakdown


class TestWebStatsPreAggregatedChannelTypes(WebAnalyticsPreAggregatedTestBase):
    def _setup_test_data(self):
        with freeze_time("2024-01-01T09:00:00Z"):
            # Create persons for each channel type test
            for i in range(15):  # Increased for more test cases
                _create_person(team_id=self.team.pk, distinct_ids=[f"user_{i}"])

        # Generate unique session IDs
        sessions = [str(uuid7("2024-01-01")) for _ in range(15)]

        # 1. Cross Network
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="user_0",
            timestamp="2024-01-01T10:00:00Z",
            properties={
                "$session_id": sessions[0],
                "$current_url": "https://example.com/?utm_campaign=cross-network",
                "utm_campaign": "cross-network",
                "utm_source": "google",
                "utm_medium": "cpc",
            },
        )

        # 2. Paid Search (gclid)
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="user_1",
            timestamp="2024-01-01T10:05:00Z",
            properties={
                "$session_id": sessions[1],
                "$current_url": "https://example.com/?gclid=abc123",
                "gclid": "abc123",
                "$referring_domain": "google.com",
            },
        )

        # 3. Paid Search (gad_source=1)
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="user_2",
            timestamp="2024-01-01T10:10:00Z",
            properties={
                "$session_id": sessions[2],
                "$current_url": "https://example.com/?gad_source=1",
                "gad_source": "1",
                "$referring_domain": "google.com",
            },
        )

        # 4. Paid Shopping
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="user_3",
            timestamp="2024-01-01T10:15:00Z",
            properties={
                "$session_id": sessions[3],
                "$current_url": "https://example.com/?utm_source=shopping.google.com&utm_medium=cpc",
                "utm_source": "shopping.google.com",
                "utm_medium": "cpc",
            },
        )

        # 5. Paid Video
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="user_4",
            timestamp="2024-01-01T10:20:00Z",
            properties={
                "$session_id": sessions[4],
                "$current_url": "https://example.com/?utm_source=youtube&utm_medium=cpc",
                "utm_source": "youtube",
                "utm_medium": "cpc",
            },
        )

        # 6. Paid Social (fbclid + paid medium)
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="user_5",
            timestamp="2024-01-01T10:25:00Z",
            properties={
                "$session_id": sessions[5],
                "$current_url": "https://example.com/?fbclid=xyz789&utm_medium=paid",
                "fbclid": "xyz789",
                "utm_medium": "paid",
                "$referring_domain": "facebook.com",
            },
        )

        # 7. Paid Unknown (paid medium but no specific classification)
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="user_6",
            timestamp="2024-01-01T10:30:00Z",
            properties={
                "$session_id": sessions[6],
                "$current_url": "https://example.com/?utm_source=unknown_source&utm_medium=cpc",
                "utm_source": "unknown_source",
                "utm_medium": "cpc",
            },
        )

        # 8. Direct
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="user_7",
            timestamp="2024-01-01T10:35:00Z",
            properties={
                "$session_id": sessions[7],
                "$current_url": "https://example.com/",
                "$referring_domain": "$direct",
            },
        )

        # 9. Organic Search
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="user_8",
            timestamp="2024-01-01T10:40:00Z",
            properties={
                "$session_id": sessions[8],
                "$current_url": "https://example.com/",
                "$referring_domain": "google.com",
            },
        )

        # 10. Organic Shopping
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="user_9",
            timestamp="2024-01-01T10:45:00Z",
            properties={
                "$session_id": sessions[9],
                "$current_url": "https://example.com/?utm_campaign=shopping_campaign",
                "utm_campaign": "shopping_campaign",
                "$referring_domain": "shopping.google.com",
            },
        )

        # 11. Organic Video
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="user_10",
            timestamp="2024-01-01T10:50:00Z",
            properties={
                "$session_id": sessions[10],
                "$current_url": "https://example.com/?utm_campaign=video_content",
                "utm_campaign": "video_content",
                "$referring_domain": "youtube.com",
            },
        )

        # 12. Organic Social (fbclid without paid medium)
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="user_11",
            timestamp="2024-01-01T10:55:00Z",
            properties={
                "$session_id": sessions[11],
                "$current_url": "https://example.com/?fbclid=organic123",
                "fbclid": "organic123",
                "$referring_domain": "facebook.com",
            },
        )

        # 13. Push
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="user_12",
            timestamp="2024-01-01T11:00:00Z",
            properties={
                "$session_id": sessions[12],
                "$current_url": "https://example.com/?utm_medium=push",
                "utm_medium": "push",
                "utm_source": "notification_service",
            },
        )

        # 14. Referral
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="user_13",
            timestamp="2024-01-01T11:05:00Z",
            properties={
                "$session_id": sessions[13],
                "$current_url": "https://example.com/",
                "$referring_domain": "techcrunch.com",
            },
        )

        # 15. Unknown (no attribution data)
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="user_14",
            timestamp="2024-01-01T11:10:00Z",
            properties={
                "$session_id": sessions[14],
                "$current_url": "https://example.com/",
            },
        )

        flush_persons_and_events()
        self._populate_web_stats_tables()

    def _populate_web_stats_tables(self):
        select_sql = WEB_STATS_INSERT_SQL(
            date_start="2024-01-01",
            date_end="2024-01-02",
            team_ids=[self.team.pk],
            table_name="web_stats_daily",
            select_only=True,
        )
        insert_sql = f"INSERT INTO web_stats_daily\n{select_sql}"
        sync_execute(insert_sql)

    def test_channel_type_breakdown_with_stats_table_runner(self):
        query = WebStatsTableQuery(
            dateRange=DateRange(date_from="2024-01-01", date_to="2024-01-02"),
            properties=[],
            breakdownBy=WebStatsBreakdown.INITIAL_CHANNEL_TYPE,
            limit=100,
        )

        modifiers = HogQLQueryModifiers(
            useWebAnalyticsPreAggregatedTables=True,
        )
        runner = WebStatsTableQueryRunner(query=query, team=self.team, modifiers=modifiers)
        response = runner.calculate()

        expected_results = [
            ["Cross Network", (1.0, 1.0), (1.0, 1.0), ""],
            ["Direct", (1.0, 1.0), (1.0, 1.0), ""],
            ["Organic Search", (1.0, 1.0), (1.0, 1.0), ""],
            ["Organic Shopping", (1.0, 1.0), (1.0, 1.0), ""],
            ["Organic Social", (1.0, 1.0), (1.0, 1.0), ""],
            ["Organic Video", (1.0, 1.0), (1.0, 1.0), ""],
            ["Paid Search", (3.0, 3.0), (3.0, 3.0), ""],  # gclid + gad_source=1 + shopping.google.com
            ["Paid Social", (1.0, 1.0), (1.0, 1.0), ""],
            ["Paid Unknown", (1.0, 1.0), (1.0, 1.0), ""],
            ["Paid Video", (1.0, 1.0), (1.0, 1.0), ""],
            ["Push", (1.0, 1.0), (1.0, 1.0), ""],
            ["Referral", (1.0, 1.0), (1.0, 1.0), ""],
            ["Unknown", (1.0, 1.0), (1.0, 1.0), ""],
        ]

        actual_sorted = sorted(response.results, key=lambda x: x[0])
        expected_sorted = sorted(expected_results, key=lambda x: x[0])

        assert actual_sorted == expected_sorted

    def test_channel_type_consistency_preagg_vs_regular(self):
        query = WebStatsTableQuery(
            dateRange=DateRange(date_from="2024-01-01", date_to="2024-01-02"),
            properties=[],
            breakdownBy=WebStatsBreakdown.INITIAL_CHANNEL_TYPE,
            limit=100,
        )

        preagg_modifiers = HogQLQueryModifiers(
            useWebAnalyticsPreAggregatedTables=True,
        )
        preagg_runner = WebStatsTableQueryRunner(query=query, team=self.team, modifiers=preagg_modifiers)
        preagg_response = preagg_runner.calculate()

        regular_modifiers = HogQLQueryModifiers(
            useWebAnalyticsPreAggregatedTables=False,
        )
        regular_runner = WebStatsTableQueryRunner(query=query, team=self.team, modifiers=regular_modifiers)
        regular_response = regular_runner.calculate()

        # Verify both queries used their respective table types
        assert preagg_response.usedPreAggregatedTables
        assert not regular_response.usedPreAggregatedTables

        preagg_sorted = sorted(preagg_response.results, key=lambda x: x[0])
        regular_sorted = sorted(regular_response.results, key=lambda x: x[0])
        assert preagg_sorted == regular_sorted
