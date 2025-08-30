from freezegun import freeze_time
from posthog.test.base import _create_event, _create_person, flush_persons_and_events, snapshot_clickhouse_queries

from posthog.schema import (
    DateRange,
    EventPropertyFilter,
    HogQLQueryModifiers,
    PropertyOperator,
    WebStatsBreakdown,
    WebStatsTableQuery,
)

from posthog.clickhouse.client.execute import sync_execute
from posthog.hogql_queries.web_analytics.stats_table import WebStatsTableQueryRunner
from posthog.hogql_queries.web_analytics.stats_table_pre_aggregated import (
    WEB_ANALYTICS_STATS_TABLE_PRE_AGGREGATED_SUPPORTED_BREAKDOWNS,
    StatsTablePreAggregatedQueryBuilder,
)
from posthog.hogql_queries.web_analytics.test.web_preaggregated_test_base import WebAnalyticsPreAggregatedTestBase
from posthog.models.utils import uuid7
from posthog.models.web_preaggregated.sql import WEB_BOUNCES_INSERT_SQL, WEB_STATS_INSERT_SQL


@snapshot_clickhouse_queries
class TestWebStatsPreAggregated(WebAnalyticsPreAggregatedTestBase):
    def _setup_test_data(self):
        with freeze_time("2024-01-01T09:00:00Z"):
            sessions = [str(uuid7("2024-01-01")) for _ in range(20)]

            for i in range(20):
                _create_person(team_id=self.team.pk, distinct_ids=[f"user_{i}"])

            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id="user_0",
                timestamp="2024-01-01T10:00:00Z",
                properties={
                    "$session_id": sessions[0],
                    "$current_url": "https://example.com/landing",
                    "$pathname": "/landing",
                    "$device_type": "Desktop",
                    "$browser": "Chrome",
                    "$os": "Windows",
                    "$viewport_width": 1920,
                    "$viewport_height": 1080,
                    "$geoip_country_code": "US",
                    "$geoip_city_name": "New York",
                    "$geoip_subdivision_1_code": "NY",
                    "utm_source": "google",
                    "utm_medium": "cpc",
                    "utm_campaign": "summer_sale",
                    "$referring_domain": "google.com",
                },
            )

            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id="user_1",
                timestamp="2024-01-01T10:05:00Z",
                properties={
                    "$session_id": sessions[1],
                    "$current_url": "https://example.com/features",
                    "$pathname": "/features",
                    "$device_type": "Desktop",
                    "$browser": "Chrome",
                    "$os": "Windows",
                    "$viewport_width": 1920,
                    "$viewport_height": 1080,
                    "$geoip_country_code": "US",
                    "$geoip_city_name": "New York",
                    "$geoip_subdivision_1_code": "NY",
                },
            )

            # Desktop user - Firefox, macOS, UK
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id="user_2",
                timestamp="2024-01-01T11:00:00Z",
                properties={
                    "$session_id": sessions[2],
                    "$current_url": "https://example.com/landing",
                    "$pathname": "/landing",
                    "$device_type": "Desktop",
                    "$browser": "Firefox",
                    "$os": "macOS",
                    "$viewport_width": 1440,
                    "$viewport_height": 900,
                    "$geoip_country_code": "GB",
                    "$geoip_city_name": "London",
                    "$geoip_subdivision_1_code": "EN",
                    "utm_source": "facebook",
                    "utm_medium": "social",
                    "$referring_domain": "facebook.com",
                },
            )

            # Mobile user - Safari, iOS, Canada
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id="user_3",
                timestamp="2024-01-01T12:00:00Z",
                properties={
                    "$session_id": sessions[3],
                    "$current_url": "https://example.com/pricing",
                    "$pathname": "/pricing",
                    "$device_type": "Mobile",
                    "$browser": "Safari",
                    "$os": "iOS",
                    "$viewport_width": 375,
                    "$viewport_height": 812,
                    "$geoip_country_code": "CA",
                    "$geoip_city_name": "Toronto",
                    "$geoip_subdivision_1_code": "ON",
                    "$referring_domain": "search.yahoo.com",
                },
            )

            # Mobile user - Chrome, Android, Australia (bounce session)
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id="user_4",
                timestamp="2024-01-01T13:00:00Z",
                properties={
                    "$session_id": sessions[4],
                    "$current_url": "https://example.com/pricing",
                    "$pathname": "/pricing",
                    "$device_type": "Mobile",
                    "$browser": "Chrome",
                    "$os": "Android",
                    "$viewport_width": 414,
                    "$viewport_height": 896,
                    "$geoip_country_code": "AU",
                    "$geoip_city_name": "Sydney",
                    "$geoip_subdivision_1_code": "NSW",
                    "utm_source": "twitter",
                    "utm_medium": "social",
                    "utm_campaign": "launch_week",
                    "$referring_domain": "twitter.com",
                },
            )

            # Another desktop user - Chrome, Windows, US (exit page different)
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id="user_5",
                timestamp="2024-01-01T14:00:00Z",
                properties={
                    "$session_id": sessions[5],
                    "$current_url": "https://example.com/contact",
                    "$pathname": "/contact",
                    "$device_type": "Desktop",
                    "$browser": "Chrome",
                    "$os": "Windows",
                    "$viewport_width": 1920,
                    "$viewport_height": 1080,
                    "$geoip_country_code": "US",
                    "$geoip_city_name": "San Francisco",
                    "$geoip_subdivision_1_code": "CA",
                    "utm_source": "google",
                    "utm_medium": "organic",
                    "$referring_domain": "google.com",
                },
            )
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id="user_5",
                timestamp="2024-01-01T14:02:00Z",
                properties={
                    "$session_id": sessions[5],
                    "$current_url": "https://example.com/about",
                    "$pathname": "/about",
                    "$device_type": "Desktop",
                    "$browser": "Chrome",
                    "$os": "Windows",
                    "$viewport_width": 1920,
                    "$viewport_height": 1080,
                    "$geoip_country_code": "US",
                    "$geoip_city_name": "San Francisco",
                    "$geoip_subdivision_1_code": "CA",
                },
            )

            flush_persons_and_events()
            self._populate_preaggregated_tables()

    def _populate_preaggregated_tables(self, date_start: str = "2024-01-01", date_end: str = "2024-01-02"):
        bounces_insert = WEB_BOUNCES_INSERT_SQL(
            date_start=date_start,
            date_end=date_end,
            team_ids=[self.team.pk],
            table_name="web_pre_aggregated_bounces",
            granularity="hourly",
        )
        stats_insert = WEB_STATS_INSERT_SQL(
            date_start=date_start,
            date_end=date_end,
            team_ids=[self.team.pk],
            table_name="web_pre_aggregated_stats",
            granularity="hourly",
        )
        sync_execute(stats_insert)
        sync_execute(bounces_insert)

    def test_can_use_preaggregated_tables_with_supported_breakdowns(self):
        for breakdown in WEB_ANALYTICS_STATS_TABLE_PRE_AGGREGATED_SUPPORTED_BREAKDOWNS:
            with self.subTest(breakdown=breakdown):
                query = WebStatsTableQuery(
                    dateRange=DateRange(date_from="2023-11-01", date_to="2023-11-30"),
                    properties=[],
                    breakdownBy=breakdown,
                )
                runner = WebStatsTableQueryRunner(team=self.team, query=query)
                builder = StatsTablePreAggregatedQueryBuilder(runner)

                assert builder.can_use_preaggregated_tables()

    def test_cannot_use_preaggregated_tables_with_unsupported_breakdown(self):
        query = WebStatsTableQuery(
            dateRange=DateRange(date_from="2023-11-01", date_to="2023-11-30"),
            properties=[],
            breakdownBy=WebStatsBreakdown.LANGUAGE,
        )
        runner = WebStatsTableQueryRunner(team=self.team, query=query)
        builder = StatsTablePreAggregatedQueryBuilder(runner)

        assert not builder.can_use_preaggregated_tables()

    def test_cannot_use_preaggregated_tables_with_unsupported_properties(self):
        query = WebStatsTableQuery(
            dateRange=DateRange(date_from="2023-11-01", date_to="2023-11-30"),
            properties=[
                EventPropertyFilter(key="unsupported_property", value="value", operator=PropertyOperator.EXACT)
            ],
            breakdownBy=WebStatsBreakdown.DEVICE_TYPE,
        )
        runner = WebStatsTableQueryRunner(team=self.team, query=query)
        builder = StatsTablePreAggregatedQueryBuilder(runner)

        assert not builder.can_use_preaggregated_tables()

    def test_query_with_supported_properties(self):
        query = WebStatsTableQuery(
            dateRange=DateRange(date_from="2023-11-01", date_to="2023-11-30"),
            properties=[EventPropertyFilter(key="$pathname", value="/test", operator=PropertyOperator.EXACT)],
            breakdownBy=WebStatsBreakdown.DEVICE_TYPE,
        )
        runner = WebStatsTableQueryRunner(team=self.team, query=query)
        runner.modifiers = HogQLQueryModifiers(useWebAnalyticsPreAggregatedTables=True)

        builder = StatsTablePreAggregatedQueryBuilder(runner)
        assert builder.can_use_preaggregated_tables()

        runner.to_query()
        assert runner.used_preaggregated_tables

    def test_query_includes_order_by(self):
        query = WebStatsTableQuery(
            dateRange=DateRange(date_from="2023-11-01", date_to="2023-11-30"),
            properties=[],
            breakdownBy=WebStatsBreakdown.DEVICE_TYPE,
        )
        runner = WebStatsTableQueryRunner(team=self.team, query=query)
        runner.modifiers = HogQLQueryModifiers(useWebAnalyticsPreAggregatedTables=True)

        hogql_query = runner.to_query()

        assert hogql_query.order_by
        assert len(hogql_query.order_by) > 0

    def _calculate_breakdown_query(self, breakdown: WebStatsBreakdown, use_preagg: bool, properties=None):
        query = WebStatsTableQuery(
            dateRange=DateRange(date_from="2024-01-01", date_to="2024-01-02"),
            properties=properties or [],
            breakdownBy=breakdown,
            limit=100,
        )

        modifiers = HogQLQueryModifiers(
            useWebAnalyticsPreAggregatedTables=use_preagg,
        )
        runner = WebStatsTableQueryRunner(query=query, team=self.team, modifiers=modifiers)
        return runner.calculate()

    def test_device_type_breakdown(self):
        response = self._calculate_breakdown_query(WebStatsBreakdown.DEVICE_TYPE, use_preagg=True)

        # Assert direct expected results - format: [breakdown_value, (visitors, prev_visitors), (views, prev_views), '']
        expected_results = [
            ["Desktop", (4.0, None), (5.0, None), 4 / 6, ""],  # user_0, user_1, user_2, user_5 (4 users)
            ["Mobile", (2.0, None), (2.0, None), 2 / 6, ""],  # user_3, user_4 (2 users)
        ]

        assert self._sort_results(response.results) == self._sort_results(expected_results)

    def test_browser_breakdown(self):
        response = self._calculate_breakdown_query(WebStatsBreakdown.BROWSER, use_preagg=True)

        expected_results = [
            ["Chrome", (4.0, None), (5.0, None), 4 / 6, ""],  # user_0, user_1, user_4, user_5 (4 users, 5 views)
            ["Firefox", (1.0, None), (1.0, None), 1 / 6, ""],  # user_2
            ["Safari", (1.0, None), (1.0, None), 1 / 6, ""],  # user_3
        ]

        assert self._sort_results(response.results) == self._sort_results(expected_results)

    def test_country_breakdown(self):
        response = self._calculate_breakdown_query(WebStatsBreakdown.COUNTRY, use_preagg=True)

        expected_results = [
            ["AU", (1.0, None), (1.0, None), 1 / 6, ""],  # user_4
            ["CA", (1.0, None), (1.0, None), 1 / 6, ""],  # user_3
            ["GB", (1.0, None), (1.0, None), 1 / 6, ""],  # user_2
            ["US", (3.0, None), (4.0, None), 3 / 6, ""],  # user_0, user_1, user_5 (3 users, 4 views)
        ]

        assert self._sort_results(response.results) == self._sort_results(expected_results)

    def test_utm_source_breakdown(self):
        response = self._calculate_breakdown_query(WebStatsBreakdown.INITIAL_UTM_SOURCE, use_preagg=True)

        expected_results = [
            [None, (2.0, None), (2.0, None), 2 / 6, ""],  # user_1, user_3 (no utm_source)
            ["facebook", (1.0, None), (1.0, None), 1 / 6, ""],  # user_2
            ["google", (2.0, None), (3.0, None), 2 / 6, ""],  # user_0 (1 view), user_5 (2 views)
            ["twitter", (1.0, None), (1.0, None), 1 / 6, ""],  # user_4
        ]

        assert self._sort_results(response.results) == self._sort_results(expected_results)

    def test_page_breakdown(self):
        response = self._calculate_breakdown_query(WebStatsBreakdown.PAGE, use_preagg=True)

        # Pre-aggregated PAGE breakdown includes bounce rate data
        expected_results = [
            ["/contact", (1.0, None), (2.0, None), (0.0, None), 1 / 6, ""],  # user_5 (2 views: /contact + /about)
            ["/features", (1.0, None), (1.0, None), (1.0, None), 1 / 6, ""],  # user_1
            ["/landing", (2.0, None), (2.0, None), (1.0, None), 2 / 6, ""],  # user_0, user_2
            ["/pricing", (2.0, None), (2.0, None), (1.0, None), 2 / 6, ""],  # user_3, user_4
        ]

        assert self._sort_results(response.results) == self._sort_results(expected_results)

    def test_viewport_breakdown(self):
        response = self._calculate_breakdown_query(WebStatsBreakdown.VIEWPORT, use_preagg=True)

        expected_results = [
            ["1440x900", (1.0, None), (1.0, None), 1 / 6, ""],  # user_2
            ["1920x1080", (3.0, None), (4.0, None), 3 / 6, ""],  # user_0, user_1, user_5 (4 views total)
            ["375x812", (1.0, None), (1.0, None), 1 / 6, ""],  # user_3
            ["414x896", (1.0, None), (1.0, None), 1 / 6, ""],  # user_4
        ]

        assert self._sort_results(response.results) == self._sort_results(expected_results)

    def test_property_filtering(self):
        properties = [EventPropertyFilter(key="$pathname", value="/landing", operator=PropertyOperator.EXACT)]
        response = self._calculate_breakdown_query(
            WebStatsBreakdown.DEVICE_TYPE, use_preagg=True, properties=properties
        )

        # Only Desktop users (user_0, user_2) viewed /landing
        expected_results = [
            ["Desktop", (2.0, None), (2.0, None), 1, ""],
        ]

        assert response.results == expected_results

    def test_page_breakdown_with_pathname_filter(self):
        properties = [EventPropertyFilter(key="$pathname", value="/landing", operator=PropertyOperator.EXACT)]
        response = self._calculate_breakdown_query(WebStatsBreakdown.PAGE, use_preagg=True, properties=properties)

        # Only /landing should be returned since we're filtering by pathname
        expected_results = [
            ["/landing", (2.0, None), (2.0, None), (1.0, None), 1, ""],  # user_0, user_2
        ]

        assert response.results == expected_results
        assert response.usedPreAggregatedTables

    def test_breakdown_consistency_preagg_vs_regular(self):
        # Note: PAGE and VIEWPORT breakdowns are excluded. I will add them back in later.
        breakdowns_to_test = [
            WebStatsBreakdown.DEVICE_TYPE,
            WebStatsBreakdown.BROWSER,
            WebStatsBreakdown.COUNTRY,
            WebStatsBreakdown.INITIAL_UTM_SOURCE,
        ]

        for breakdown in breakdowns_to_test:
            with self.subTest(breakdown=breakdown):
                preagg_response = self._calculate_breakdown_query(breakdown, use_preagg=True)
                regular_response = self._calculate_breakdown_query(breakdown, use_preagg=False)

                # Verify both queries used their respective query engines
                assert preagg_response.usedPreAggregatedTables
                assert not regular_response.usedPreAggregatedTables

                assert self._sort_results(preagg_response.results) == self._sort_results(regular_response.results)
