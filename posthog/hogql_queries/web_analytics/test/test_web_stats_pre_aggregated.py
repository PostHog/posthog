from datetime import UTC, datetime, timedelta

from freezegun import freeze_time
from posthog.test.base import _create_event, _create_person, flush_persons_and_events, snapshot_clickhouse_queries
from unittest.mock import MagicMock

from parameterized import parameterized

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
                    "$host": "example.com",
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
                    "$host": "example.com",
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
                    "$host": "example.com",
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
                    "$host": "example.com",
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
                    "$host": "example.com",
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
                    "$host": "example.com",
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
                    "$host": "example.com",
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

    def _truncate_preaggregated_tables(self):
        sync_execute(f"ALTER TABLE web_pre_aggregated_stats DELETE WHERE team_id = {self.team.pk}")
        sync_execute(f"ALTER TABLE web_pre_aggregated_bounces DELETE WHERE team_id = {self.team.pk}")
        sync_execute("OPTIMIZE TABLE web_pre_aggregated_stats FINAL")
        sync_execute("OPTIMIZE TABLE web_pre_aggregated_bounces FINAL")

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

    def _calculate_breakdown_query(
        self,
        breakdown: WebStatsBreakdown,
        use_preagg: bool,
        properties=None,
        include_host: bool = False,
        date_from: str = "2024-01-01",
        date_to: str = "2024-01-02",
    ):
        query = WebStatsTableQuery(
            dateRange=DateRange(date_from=date_from, date_to=date_to),
            properties=properties or [],
            breakdownBy=breakdown,
            limit=100,
            includeHost=include_host,
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

    @parameterized.expand(
        [
            # (name, hours_delta, explicit_date_to, expected_is_recent)
            ("1_hour_no_explicit_date_to", 1, False, True),
            ("6_hours_no_explicit_date_to", 6, False, True),
            ("7_hours_no_explicit_date_to", 7, False, False),
            ("24_hours_no_explicit_date_to", 24, False, False),
            ("1_hour_with_explicit_date_to", 1, True, False),
            ("6_hours_with_explicit_date_to", 6, True, False),
        ]
    )
    def test_is_recent_relative_date_range(self, _name, hours_delta, explicit_date_to, expected_is_recent):
        now = datetime(2025, 1, 31, 12, 0, 0, tzinfo=UTC)
        date_from = now - timedelta(hours=hours_delta)

        query = WebStatsTableQuery(
            dateRange=DateRange(date_to=now.isoformat() if explicit_date_to else None),
            properties=[],
            breakdownBy=WebStatsBreakdown.DEVICE_TYPE,
        )

        runner = MagicMock()
        runner.query = query
        runner.team = self.team
        runner.modifiers = HogQLQueryModifiers(useWebAnalyticsPreAggregatedTables=True, convertToProjectTimezone=False)

        mock_date_range = MagicMock()
        mock_date_range.date_from.return_value = date_from
        mock_date_range.date_to.return_value = now
        runner.query_date_range = mock_date_range
        runner.query_compare_to_date_range = None

        builder = StatsTablePreAggregatedQueryBuilder(runner)
        self.assertEqual(builder._is_recent_relative_date_range(), expected_is_recent)

    def test_can_use_preaggregated_tables_rejects_recent_relative_date_range(self):
        now = datetime(2025, 1, 31, 12, 0, 0, tzinfo=UTC)
        date_from = now - timedelta(hours=3)

        query = WebStatsTableQuery(
            dateRange=DateRange(),  # No explicit date_to means query ends at "now"
            properties=[],
            breakdownBy=WebStatsBreakdown.DEVICE_TYPE,
        )

        runner = MagicMock()
        runner.query = query
        runner.team = self.team
        runner.modifiers = HogQLQueryModifiers(useWebAnalyticsPreAggregatedTables=True, convertToProjectTimezone=False)

        mock_date_range = MagicMock()
        mock_date_range.date_from.return_value = date_from
        mock_date_range.date_to.return_value = now
        runner.query_date_range = mock_date_range
        runner.query_compare_to_date_range = None

        builder = StatsTablePreAggregatedQueryBuilder(runner)
        self.assertFalse(builder.can_use_preaggregated_tables())

    # NOTE: PAGE breakdown is not tested here because pre-aggregated tables have a known limitation
    # where they don't correctly return all mid-session pages for PAGE breakdown (only entry pages).
    # The non-pre-aggregated tests for PAGE with includeHost work correctly in test_web_stats_table.py.
    @parameterized.expand(
        [
            (WebStatsBreakdown.INITIAL_PAGE,),
            (WebStatsBreakdown.EXIT_PAGE,),
        ]
    )
    def test_include_host_concatenates_host_and_path(self, breakdown):
        self._truncate_preaggregated_tables()
        with freeze_time("2024-01-02T09:00:00Z"):
            sessions = [str(uuid7("2024-01-02")) for _ in range(3)]

            for i in range(3):
                _create_person(team_id=self.team.pk, distinct_ids=[f"host_user_{i}"])

            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id="host_user_0",
                timestamp="2024-01-02T10:00:00Z",
                properties={
                    "$session_id": sessions[0],
                    "$current_url": "https://example.com/landing",
                    "$pathname": "/landing",
                    "$host": "example.com",
                    "$device_type": "Desktop",
                    "$browser": "Chrome",
                    "$os": "Windows",
                    "$viewport_width": 1920,
                    "$viewport_height": 1080,
                },
            )

            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id="host_user_0",
                timestamp="2024-01-02T10:01:00Z",
                properties={
                    "$session_id": sessions[0],
                    "$current_url": "https://example.com/features",
                    "$pathname": "/features",
                    "$host": "example.com",
                    "$device_type": "Desktop",
                    "$browser": "Chrome",
                    "$os": "Windows",
                    "$viewport_width": 1920,
                    "$viewport_height": 1080,
                },
            )

            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id="host_user_1",
                timestamp="2024-01-02T11:00:00Z",
                properties={
                    "$session_id": sessions[1],
                    "$current_url": "https://subdomain.example.com/landing",
                    "$pathname": "/landing",
                    "$host": "subdomain.example.com",
                    "$device_type": "Desktop",
                    "$browser": "Chrome",
                    "$os": "Windows",
                    "$viewport_width": 1920,
                    "$viewport_height": 1080,
                },
            )

            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id="host_user_1",
                timestamp="2024-01-02T11:01:00Z",
                properties={
                    "$session_id": sessions[1],
                    "$current_url": "https://subdomain.example.com/pricing",
                    "$pathname": "/pricing",
                    "$host": "subdomain.example.com",
                    "$device_type": "Desktop",
                    "$browser": "Chrome",
                    "$os": "Windows",
                    "$viewport_width": 1920,
                    "$viewport_height": 1080,
                },
            )

            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id="host_user_2",
                timestamp="2024-01-02T12:00:00Z",
                properties={
                    "$session_id": sessions[2],
                    "$current_url": "https://example.com/pricing",
                    "$pathname": "/pricing",
                    "$host": "example.com",
                    "$device_type": "Desktop",
                    "$browser": "Chrome",
                    "$os": "Windows",
                    "$viewport_width": 1920,
                    "$viewport_height": 1080,
                },
            )

            flush_persons_and_events()
            self._populate_preaggregated_tables(date_start="2024-01-02", date_end="2024-01-03")

        response = self._calculate_breakdown_query(
            breakdown, use_preagg=True, include_host=True, date_from="2024-01-02", date_to="2024-01-03"
        )

        breakdown_values = [r[0] for r in response.results]

        if breakdown == WebStatsBreakdown.INITIAL_PAGE:
            assert "example.com/landing" in breakdown_values
            assert "subdomain.example.com/landing" in breakdown_values
            assert "example.com/pricing" in breakdown_values
        elif breakdown == WebStatsBreakdown.EXIT_PAGE:
            assert "example.com/features" in breakdown_values
            assert "subdomain.example.com/pricing" in breakdown_values
            assert "example.com/pricing" in breakdown_values

        assert response.usedPreAggregatedTables

    @parameterized.expand(
        [
            (WebStatsBreakdown.PAGE,),
            (WebStatsBreakdown.INITIAL_PAGE,),
            (WebStatsBreakdown.EXIT_PAGE,),
        ]
    )
    def test_include_host_false_returns_path_only(self, breakdown):
        self._truncate_preaggregated_tables()
        with freeze_time("2024-01-02T09:00:00Z"):
            sessions = [str(uuid7("2024-01-02")) for _ in range(2)]

            for i in range(2):
                _create_person(team_id=self.team.pk, distinct_ids=[f"path_user_{i}"])

            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id="path_user_0",
                timestamp="2024-01-02T10:00:00Z",
                properties={
                    "$session_id": sessions[0],
                    "$current_url": "https://example.com/landing",
                    "$pathname": "/landing",
                    "$host": "example.com",
                    "$device_type": "Desktop",
                    "$browser": "Chrome",
                    "$os": "Windows",
                    "$viewport_width": 1920,
                    "$viewport_height": 1080,
                },
            )

            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id="path_user_1",
                timestamp="2024-01-02T11:00:00Z",
                properties={
                    "$session_id": sessions[1],
                    "$current_url": "https://subdomain.example.com/landing",
                    "$pathname": "/landing",
                    "$host": "subdomain.example.com",
                    "$device_type": "Desktop",
                    "$browser": "Chrome",
                    "$os": "Windows",
                    "$viewport_width": 1920,
                    "$viewport_height": 1080,
                },
            )

            flush_persons_and_events()
            self._populate_preaggregated_tables(date_start="2024-01-02", date_end="2024-01-03")

        response = self._calculate_breakdown_query(
            breakdown, use_preagg=True, include_host=False, date_from="2024-01-02", date_to="2024-01-03"
        )

        breakdown_values = [r[0] for r in response.results]

        assert "/landing" in breakdown_values
        assert "example.com/landing" not in breakdown_values
        assert "subdomain.example.com/landing" not in breakdown_values
        assert response.usedPreAggregatedTables

    def test_include_host_page_breakdown_groups_same_paths_separately(self):
        self._truncate_preaggregated_tables()
        with freeze_time("2024-01-02T09:00:00Z"):
            sessions = [str(uuid7("2024-01-02")) for _ in range(3)]

            for i in range(3):
                _create_person(team_id=self.team.pk, distinct_ids=[f"group_user_{i}"])

            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id="group_user_0",
                timestamp="2024-01-02T10:00:00Z",
                properties={
                    "$session_id": sessions[0],
                    "$current_url": "https://example.com/landing",
                    "$pathname": "/landing",
                    "$host": "example.com",
                    "$device_type": "Desktop",
                    "$browser": "Chrome",
                    "$os": "Windows",
                    "$viewport_width": 1920,
                    "$viewport_height": 1080,
                },
            )

            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id="group_user_1",
                timestamp="2024-01-02T11:00:00Z",
                properties={
                    "$session_id": sessions[1],
                    "$current_url": "https://subdomain.example.com/landing",
                    "$pathname": "/landing",
                    "$host": "subdomain.example.com",
                    "$device_type": "Desktop",
                    "$browser": "Chrome",
                    "$os": "Windows",
                    "$viewport_width": 1920,
                    "$viewport_height": 1080,
                },
            )

            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id="group_user_2",
                timestamp="2024-01-02T12:00:00Z",
                properties={
                    "$session_id": sessions[2],
                    "$current_url": "https://example.com/landing",
                    "$pathname": "/landing",
                    "$host": "example.com",
                    "$device_type": "Desktop",
                    "$browser": "Chrome",
                    "$os": "Windows",
                    "$viewport_width": 1920,
                    "$viewport_height": 1080,
                },
            )

            flush_persons_and_events()
            self._populate_preaggregated_tables(date_start="2024-01-02", date_end="2024-01-03")

        with_host = self._calculate_breakdown_query(
            WebStatsBreakdown.PAGE, use_preagg=True, include_host=True, date_from="2024-01-02", date_to="2024-01-03"
        )
        without_host = self._calculate_breakdown_query(
            WebStatsBreakdown.PAGE, use_preagg=True, include_host=False, date_from="2024-01-02", date_to="2024-01-03"
        )

        with_host_dict = {r[0]: r[1] for r in with_host.results}
        without_host_dict = {r[0]: r[1] for r in without_host.results}

        assert with_host_dict["example.com/landing"][0] == 2
        assert with_host_dict["subdomain.example.com/landing"][0] == 1
        assert without_host_dict["/landing"][0] == 3
        assert with_host.usedPreAggregatedTables
        assert without_host.usedPreAggregatedTables

    # NOTE: test_include_host_consistency_between_preagg_and_regular is not included because
    # pre-aggregated tables have a known limitation where PAGE breakdown doesn't return mid-session pages.
    # The non-pre-aggregated version works correctly - see test_web_stats_table.py for full coverage.
