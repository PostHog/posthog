from freezegun import freeze_time
from posthog.test.base import _create_event, _create_person, flush_persons_and_events

from posthog.schema import DateRange, HogQLQueryModifiers, SessionPropertyFilter, WebStatsBreakdown, WebStatsTableQuery

from posthog.hogql.database.schema.channel_type import DEFAULT_CHANNEL_TYPES

from posthog.clickhouse.client.execute import sync_execute
from posthog.hogql_queries.web_analytics.stats_table import WebStatsTableQueryRunner
from posthog.hogql_queries.web_analytics.test.web_preaggregated_test_base import WebAnalyticsPreAggregatedTestBase
from posthog.models.utils import uuid7
from posthog.models.web_preaggregated.sql import WEB_STATS_INSERT_SQL


class TestWebStatsPreAggregatedChannelTypes(WebAnalyticsPreAggregatedTestBase):
    def _setup_test_data(self):
        with freeze_time("2024-01-01T09:00:00Z"):
            sessions = [str(uuid7("2024-01-01")) for _ in range(20)]

            for i in range(20):
                _create_person(team_id=self.team.pk, distinct_ids=[f"user_{i}"])

            # 1. Cross Network (requires utm_campaign="cross-network")
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id="user_0",
                timestamp="2024-01-01T09:00:00Z",
                properties={
                    "$session_id": sessions[0],
                    "$current_url": "https://example.com/?utm_campaign=cross-network",
                    "utm_campaign": "cross-network",
                    **self.STANDARD_EVENT_PROPERTIES,
                },
            )

            # 2. Paid Search (gclid)
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id="user_1",
                timestamp="2024-01-01T09:05:00Z",
                properties={
                    "$session_id": sessions[1],
                    "$current_url": "https://example.com/?gclid=123",
                    "gclid": "123",
                    **self.STANDARD_EVENT_PROPERTIES,
                },
            )

            # 3. Paid Search (gad_source=1 - Google Ads)
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id="user_2",
                timestamp="2024-01-01T09:10:00Z",
                properties={
                    "$session_id": sessions[2],
                    "$current_url": "https://example.com/?gad_source=1",
                    "gad_source": "1",
                    **self.STANDARD_EVENT_PROPERTIES,
                },
            )

            # 4. Paid Shopping (shopping source)
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id="user_3",
                timestamp="2024-01-01T09:15:00Z",
                properties={
                    "$session_id": sessions[3],
                    "$current_url": "https://example.com/?utm_source=shopping&utm_medium=cpc&utm_campaign=product_ads",
                    "utm_source": "shopping",
                    "utm_medium": "cpc",
                    "utm_campaign": "product_ads",
                    **self.STANDARD_EVENT_PROPERTIES,
                },
            )

            # 5. Paid Video
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id="user_4",
                timestamp="2024-01-01T09:20:00Z",
                properties={
                    "$session_id": sessions[4],
                    "$current_url": "https://example.com/?utm_source=youtube&utm_medium=cpc&utm_campaign=video_ads",
                    "utm_source": "youtube",
                    "utm_medium": "cpc",
                    "utm_campaign": "video_ads",
                    "$referring_domain": "youtube.com",
                    **self.STANDARD_EVENT_PROPERTIES,
                },
            )

            # 6. Paid Social (facebook cpc)
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id="user_5",
                timestamp="2024-01-01T09:25:00Z",
                properties={
                    "$session_id": sessions[5],
                    "$current_url": "https://example.com/?utm_source=facebook&utm_medium=cpc",
                    "utm_source": "facebook",
                    "utm_medium": "cpc",
                    "$referring_domain": "facebook.com",
                    **self.STANDARD_EVENT_PROPERTIES,
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
                    **self.STANDARD_EVENT_PROPERTIES,
                },
            )

            # 8. Direct - THIS IS THE ONE WE'LL FILTER FOR
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id="user_7",
                timestamp="2024-01-01T10:35:00Z",
                properties={
                    "$session_id": sessions[7],
                    "$current_url": "https://example.com/",
                    "$referring_domain": "$direct",
                    **self.STANDARD_EVENT_PROPERTIES,
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
                    **self.STANDARD_EVENT_PROPERTIES,
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
                    **self.STANDARD_EVENT_PROPERTIES,
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
                    **self.STANDARD_EVENT_PROPERTIES,
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
                    **self.STANDARD_EVENT_PROPERTIES,
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
                    **self.STANDARD_EVENT_PROPERTIES,
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
                    **self.STANDARD_EVENT_PROPERTIES,
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
                    **self.STANDARD_EVENT_PROPERTIES,
                },
            )

            # 16. Email
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id="user_15",
                timestamp="2024-01-01T11:15:00Z",
                properties={
                    "$session_id": sessions[15],
                    "$current_url": "https://example.com/?utm_medium=email&utm_campaign=newsletter",
                    "utm_medium": "email",
                    "utm_campaign": "newsletter",
                    "utm_source": "mailchimp",
                    **self.STANDARD_EVENT_PROPERTIES,
                },
            )

            # 17. SMS (sms source)
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id="user_16",
                timestamp="2024-01-01T11:20:00Z",
                properties={
                    "$session_id": sessions[16],
                    "$current_url": "https://example.com/?utm_source=sms&utm_campaign=promo",
                    "utm_source": "sms",
                    "utm_campaign": "promo",
                    **self.STANDARD_EVENT_PROPERTIES,
                },
            )

            # 18. Audio
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id="user_17",
                timestamp="2024-01-01T11:25:00Z",
                properties={
                    "$session_id": sessions[17],
                    "$current_url": "https://example.com/?utm_medium=audio&utm_campaign=podcast",
                    "utm_medium": "audio",
                    "utm_campaign": "podcast",
                    "utm_source": "spotify",
                    **self.STANDARD_EVENT_PROPERTIES,
                },
            )

            # 19. Affiliate
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id="user_18",
                timestamp="2024-01-01T11:30:00Z",
                properties={
                    "$session_id": sessions[18],
                    "$current_url": "https://example.com/?utm_medium=affiliate&utm_campaign=partner",
                    "utm_medium": "affiliate",
                    "utm_campaign": "partner",
                    "utm_source": "partner_site",
                    "$referring_domain": "partner.com",
                    **self.STANDARD_EVENT_PROPERTIES,
                },
            )

            # 20. Another Direct session for filtering test
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id="user_19",
                timestamp="2024-01-01T11:35:00Z",
                properties={
                    "$session_id": sessions[19],
                    "$current_url": "https://example.com/",
                    "$referring_domain": "$direct",
                    **self.STANDARD_EVENT_PROPERTIES,
                },
            )

        flush_persons_and_events()
        self._populate_web_stats_tables()

    def _populate_web_stats_tables(self):
        select_sql = WEB_STATS_INSERT_SQL(
            date_start="2024-01-01",
            date_end="2024-01-02",
            team_ids=[self.team.pk],
            table_name="web_pre_aggregated_stats",
            granularity="hourly",
            select_only=True,
        )
        insert_sql = f"INSERT INTO web_pre_aggregated_stats\n{select_sql}"
        sync_execute(insert_sql)

    def _calculate_channel_type_query(
        self,
        use_preagg: bool,
        properties: list[SessionPropertyFilter] | None = None,
        breakdown_by: WebStatsBreakdown = WebStatsBreakdown.INITIAL_CHANNEL_TYPE,
    ):
        query = WebStatsTableQuery(
            dateRange=DateRange(date_from="2024-01-01", date_to="2024-01-02"),
            properties=properties or [],
            breakdownBy=breakdown_by,
            limit=100,
        )

        modifiers = HogQLQueryModifiers(
            useWebAnalyticsPreAggregatedTables=use_preagg,
        )
        runner = WebStatsTableQueryRunner(query=query, team=self.team, modifiers=modifiers)
        return runner.calculate()

    def test_channel_type_breakdown_with_stats_table_runner(self):
        response = self._calculate_channel_type_query(use_preagg=True)

        # Assert direct expected results - format: [channel_name, (sessions, persons), (pageviews, views), '']
        expected_results = [
            ["Affiliate", (1.0, None), (1.0, None), 1 / 20, ""],
            ["Audio", (1.0, None), (1.0, None), 1 / 20, ""],
            ["Cross Network", (1.0, None), (1.0, None), 1 / 20, ""],
            ["Direct", (2.0, None), (2.0, None), 2 / 20, ""],  # Now 2 Direct sessions
            ["Email", (1.0, None), (1.0, None), 1 / 20, ""],
            ["Organic Search", (1.0, None), (1.0, None), 1 / 20, ""],
            ["Organic Shopping", (1.0, None), (1.0, None), 1 / 20, ""],
            ["Organic Social", (1.0, None), (1.0, None), 1 / 20, ""],
            ["Organic Video", (1.0, None), (1.0, None), 1 / 20, ""],
            ["Paid Search", (1.0, None), (1.0, None), 1 / 20, ""],  # gad_source=1
            ["Paid Shopping", (1.0, None), (1.0, None), 1 / 20, ""],  # shopping source with cpc medium
            ["Paid Social", (1.0, None), (1.0, None), 1 / 20, ""],  # facebook cpc
            ["Paid Unknown", (2.0, None), (2.0, None), 2 / 20, ""],  # gclid + unknown_source cpc
            ["Paid Video", (1.0, None), (1.0, None), 1 / 20, ""],
            ["Push", (1.0, None), (1.0, None), 1 / 20, ""],
            ["Referral", (1.0, None), (1.0, None), 1 / 20, ""],
            ["SMS", (1.0, None), (1.0, None), 1 / 20, ""],
            ["Unknown", (1.0, None), (1.0, None), 1 / 20, ""],
        ]

        actual_sorted = sorted(response.results, key=lambda x: str(x[0]))
        expected_sorted = sorted(expected_results, key=lambda x: str(x[0]))

        assert actual_sorted == expected_sorted

    def test_channel_type_consistency_preagg_vs_regular(self):
        preagg_response = self._calculate_channel_type_query(use_preagg=True)
        regular_response = self._calculate_channel_type_query(use_preagg=False)

        # Verify both queries used their respective query engines
        assert preagg_response.usedPreAggregatedTables
        assert not regular_response.usedPreAggregatedTables

        actual_sorted = sorted(preagg_response.results, key=lambda x: x[0])
        expected_sorted = sorted(regular_response.results, key=lambda x: x[0])

        assert actual_sorted == expected_sorted

    def test_covers_all_default_channel_types(self):
        """Smoke test just to make sure we're covering all the default channel types"""
        response = self._calculate_channel_type_query(use_preagg=True)

        actual_channels = {result[0] for result in response.results}
        expected_channels = set(DEFAULT_CHANNEL_TYPES)

        assert expected_channels.issubset(actual_channels)

    def test_channel_type_filtering_with_preaggregated_tables(self):
        preagg_response = self._calculate_channel_type_query(
            use_preagg=True,
            properties=[SessionPropertyFilter(key="$channel_type", value="Direct", operator="exact", type="session")],
        )
        regular_response = self._calculate_channel_type_query(
            use_preagg=False,
            properties=[SessionPropertyFilter(key="$channel_type", value="Direct", operator="exact", type="session")],
        )

        # Verify that pre-aggregated tables were used
        assert preagg_response.usedPreAggregatedTables
        assert not regular_response.usedPreAggregatedTables

        preagg_result = preagg_response.results[0]
        regular_result = regular_response.results[0]

        assert preagg_result[1] == (2.0, None)  # 2 visitors
        assert preagg_result[2] == (2.0, None)  # 2 views
        assert regular_result[1] == (2.0, None)  # 2 visitors
        assert regular_result[2] == (2.0, None)  # 2 views

        # Results should be identical between pre-agg and regular
        assert preagg_response.results == regular_response.results

    def test_channel_type_filtering_with_different_channel_types(self):
        # Test "Paid Unknown" - should get 2 sessions (gclid + unknown_source cpc)
        preagg_response = self._calculate_channel_type_query(
            use_preagg=True,
            properties=[
                SessionPropertyFilter(key="$channel_type", value="Paid Unknown", operator="exact", type="session")
            ],
        )
        assert len(preagg_response.results) == 1
        assert preagg_response.results[0][1] == (2.0, None)  # 2 visitors
        assert preagg_response.usedPreAggregatedTables

        # Test "Organic Search" - should get 1 session
        preagg_response = self._calculate_channel_type_query(
            use_preagg=True,
            properties=[
                SessionPropertyFilter(key="$channel_type", value="Organic Search", operator="exact", type="session")
            ],
        )
        assert len(preagg_response.results) == 1
        assert preagg_response.results[0][1] == (1.0, None)  # 1 visitor
        assert preagg_response.usedPreAggregatedTables

        # Test non-existent channel type - should get no results
        preagg_response = self._calculate_channel_type_query(
            use_preagg=True,
            properties=[
                SessionPropertyFilter(
                    key="$channel_type", value="Non-existent Channel", operator="exact", type="session"
                )
            ],
        )
        assert len(preagg_response.results) == 0
        assert preagg_response.usedPreAggregatedTables
