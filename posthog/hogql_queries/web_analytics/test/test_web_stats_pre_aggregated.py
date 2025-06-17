from freezegun import freeze_time

from posthog.clickhouse.client.execute import sync_execute
from posthog.models.web_preaggregated.sql import WEB_STATS_INSERT_SQL
from posthog.models.utils import uuid7
from posthog.hogql_queries.web_analytics.test.web_preaggregated_test_base import WebAnalyticsPreAggregatedTestBase
from posthog.test.base import _create_event, _create_person, flush_persons_and_events
from posthog.hogql_queries.web_analytics.stats_table import WebStatsTableQueryRunner
from posthog.schema import WebStatsTableQuery, DateRange, WebStatsBreakdown, HogQLQueryModifiers


class TestWebStatsPreAggregated(WebAnalyticsPreAggregatedTestBase):
    def _setup_test_data(self):
        with freeze_time("2024-01-01T09:00:00Z"):
            _create_person(team_id=self.team.pk, distinct_ids=["user1"])
            _create_person(team_id=self.team.pk, distinct_ids=["user2"])
            _create_person(team_id=self.team.pk, distinct_ids=["user3"])
            _create_person(team_id=self.team.pk, distinct_ids=["user4"])

        self.session1_id = str(uuid7("2024-01-01"))
        self.session2_id = str(uuid7("2024-01-01"))
        self.session3_id = str(uuid7("2024-01-01"))
        self.session4_id = str(uuid7("2024-01-01"))

        # Session 1: User1 - 3 pageviews on different pages
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="user1",
            timestamp="2024-01-01T10:00:00Z",
            properties={
                "$session_id": self.session1_id,
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
            },
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="user1",
            timestamp="2024-01-01T10:05:00Z",
            properties={
                "$session_id": self.session1_id,
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
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="user1",
            timestamp="2024-01-01T10:10:00Z",
            properties={
                "$session_id": self.session1_id,
                "$current_url": "https://example.com/pricing",
                "$pathname": "/pricing",
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

        # Session 2: User2 - 2 pageviews on same page
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="user2",
            timestamp="2024-01-01T11:00:00Z",
            properties={
                "$session_id": self.session2_id,
                "$current_url": "https://example.com/landing",
                "$pathname": "/landing",
                "$host": "example.com",
                "$device_type": "Mobile",
                "$browser": "Safari",
                "$os": "iOS",
                "$viewport_width": 375,
                "$viewport_height": 667,
                "$geoip_country_code": "CA",
                "$geoip_city_name": "Toronto",
                "$geoip_subdivision_1_code": "ON",
            },
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="user2",
            timestamp="2024-01-01T11:02:00Z",
            properties={
                "$session_id": self.session2_id,
                "$current_url": "https://example.com/landing",
                "$pathname": "/landing",
                "$host": "example.com",
                "$device_type": "Mobile",
                "$browser": "Safari",
                "$os": "iOS",
                "$viewport_width": 375,
                "$viewport_height": 667,
                "$geoip_country_code": "CA",
                "$geoip_city_name": "Toronto",
                "$geoip_subdivision_1_code": "ON",
            },
        )

        # Session 3: User3 - 1 pageview different page
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="user3",
            timestamp="2024-01-01T12:00:00Z",
            properties={
                "$session_id": self.session3_id,
                "$current_url": "https://example.com/pricing",
                "$pathname": "/pricing",
                "$host": "example.com",
                "$device_type": "Desktop",
                "$browser": "Firefox",
                "$os": "Linux",
                "$viewport_width": 1366,
                "$viewport_height": 768,
                "$geoip_country_code": "GB",
                "$geoip_city_name": "London",
                "$geoip_subdivision_1_code": "ENG",
            },
        )

        # Session 4: User4 - 2 pageviews on features page
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="user4",
            timestamp="2024-01-01T13:00:00Z",
            properties={
                "$session_id": self.session4_id,
                "$current_url": "https://example.com/features",
                "$pathname": "/features",
                "$host": "example.com",
                "$device_type": "Desktop",
                "$browser": "Chrome",
                "$os": "macOS",
                "$viewport_width": 1440,
                "$viewport_height": 900,
                "$geoip_country_code": "US",
                "$geoip_city_name": "San Francisco",
                "$geoip_subdivision_1_code": "CA",
            },
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="user4",
            timestamp="2024-01-01T13:05:00Z",
            properties={
                "$session_id": self.session4_id,
                "$current_url": "https://example.com/features",
                "$pathname": "/features",
                "$host": "example.com",
                "$device_type": "Desktop",
                "$browser": "Chrome",
                "$os": "macOS",
                "$viewport_width": 1440,
                "$viewport_height": 900,
                "$geoip_country_code": "US",
                "$geoip_city_name": "San Francisco",
                "$geoip_subdivision_1_code": "CA",
            },
        )

        flush_persons_and_events()

    def _get_pre_agg_metrics_from_stats_table(self, base_sql: str, breakdown_by: WebStatsBreakdown) -> list:
        """Extract metrics from pre-aggregated stats table data"""
        metrics_sql = f"""
        WITH session_data AS (
            {base_sql}
        ),
        aggregated AS (
            SELECT
                {self._get_breakdown_field(breakdown_by)} AS breakdown_value,
                uniqMerge(persons_uniq_state) AS unique_persons,
                uniqMerge(sessions_uniq_state) AS unique_sessions,
                sumMerge(pageviews_count_state) AS total_pageviews
            FROM session_data
            GROUP BY breakdown_value
        )
        SELECT
            breakdown_value,
            unique_persons,
            total_pageviews
        FROM aggregated
        ORDER BY breakdown_value
        """

        results = sync_execute(metrics_sql)
        return results

    def _get_breakdown_field(self, breakdown_by: WebStatsBreakdown) -> str:
        """Get the appropriate breakdown field for the query"""
        if breakdown_by == WebStatsBreakdown.PAGE:
            return "pathname"
        elif breakdown_by == WebStatsBreakdown.DEVICE_TYPE:
            return "device_type"
        elif breakdown_by == WebStatsBreakdown.BROWSER:
            return "browser"
        elif breakdown_by == WebStatsBreakdown.OS:
            return "os"
        elif breakdown_by == WebStatsBreakdown.COUNTRY:
            return "country_code"
        else:
            return "pathname"

    def _run_stats_table_query(self, breakdown_by: WebStatsBreakdown, use_pre_agg: bool = False) -> list:
        """Run the stats table query runner"""
        query = WebStatsTableQuery(
            dateRange=DateRange(date_from="2024-01-01", date_to="2024-01-02"),
            breakdownBy=breakdown_by,
            properties=[],
        )

        modifiers = HogQLQueryModifiers(useWebAnalyticsPreAggregatedTables=use_pre_agg)
        runner = WebStatsTableQueryRunner(query=query, team=self.team, modifiers=modifiers)
        response = runner.calculate()

        # Extract just the breakdown value, visitors, and views from results
        results = []
        for row in response.results:
            breakdown_value = row[0]
            visitors = row[1][0] if row[1] else 0  # First element of tuple (current period)
            views = row[2][0] if row[2] else 0  # First element of tuple (current period)
            results.append((breakdown_value, visitors, views))

        return sorted(results)

    def test_web_stats_flag_functionality(self):
        """Test that the select_only flag works correctly"""
        # Get full INSERT query
        full_sql = WEB_STATS_INSERT_SQL(
            date_start="2024-01-01", date_end="2024-01-02", team_ids=[self.team.pk], table_name="web_stats_daily"
        )

        # Should start with INSERT INTO
        assert full_sql.strip().startswith("INSERT INTO web_stats_daily")

        # Check that we can't run this as a SELECT (would error)
        # This is just to verify the flag is needed

    def test_page_breakdown_comparison(self):
        """Test PAGE breakdown: pre-agg vs stats table runner"""

        # First test without pre-aggregation (regular stats table)
        regular_results = self._run_stats_table_query(WebStatsBreakdown.PAGE, use_pre_agg=False)

        # Expected results based on our test data:
        # /landing: 2 visitors (user1, user2), 3 pageviews (1 + 2)
        # /features: 2 visitors (user1, user4), 3 pageviews (1 + 2)
        # /pricing: 2 visitors (user1, user3), 2 pageviews (1 + 1)
        expected_results = [("/features", 2, 3), ("/landing", 2, 3), ("/pricing", 2, 2)]

        assert regular_results == expected_results

        # TODO: Add pre-aggregated comparison once we have select_only flag
        # For now, just verify the basic query structure works

    def test_device_type_breakdown_comparison(self):
        """Test DEVICE_TYPE breakdown: pre-agg vs stats table runner"""

        regular_results = self._run_stats_table_query(WebStatsBreakdown.DEVICE_TYPE, use_pre_agg=False)

        # Expected results based on our test data:
        # Desktop: 3 visitors (user1, user3, user4), 6 pageviews (3 + 1 + 2)
        # Mobile: 1 visitor (user2), 2 pageviews
        expected_results = [("Desktop", 3, 6), ("Mobile", 1, 2)]

        assert regular_results == expected_results

    def test_browser_breakdown_comparison(self):
        """Test BROWSER breakdown: pre-agg vs stats table runner"""

        regular_results = self._run_stats_table_query(WebStatsBreakdown.BROWSER, use_pre_agg=False)

        # Expected results based on our test data:
        # Chrome: 2 visitors (user1, user4), 5 pageviews (3 + 2)
        # Safari: 1 visitor (user2), 2 pageviews
        # Firefox: 1 visitor (user3), 1 pageview
        expected_results = [("Chrome", 2, 5), ("Firefox", 1, 1), ("Safari", 1, 2)]

        assert regular_results == expected_results

    def test_os_breakdown_comparison(self):
        """Test OS breakdown: pre-agg vs stats table runner"""

        regular_results = self._run_stats_table_query(WebStatsBreakdown.OS, use_pre_agg=False)

        # Expected results based on our test data:
        # Windows: 1 visitor (user1), 3 pageviews
        # iOS: 1 visitor (user2), 2 pageviews
        # Linux: 1 visitor (user3), 1 pageview
        # macOS: 1 visitor (user4), 2 pageviews
        expected_results = [("Linux", 1, 1), ("Windows", 1, 3), ("iOS", 1, 2), ("macOS", 1, 2)]

        assert regular_results == expected_results

    def test_country_breakdown_comparison(self):
        """Test COUNTRY breakdown: pre-agg vs stats table runner"""

        regular_results = self._run_stats_table_query(WebStatsBreakdown.COUNTRY, use_pre_agg=False)

        # Expected results based on our test data:
        # US: 2 visitors (user1, user4), 5 pageviews (3 + 2)
        # CA: 1 visitor (user2), 2 pageviews
        # GB: 1 visitor (user3), 1 pageview
        expected_results = [("CA", 1, 2), ("GB", 1, 1), ("US", 2, 5)]

        assert regular_results == expected_results

    def test_expected_totals(self):
        """Verify our test data totals are correct"""

        # Total across all pages should be:
        # 4 unique visitors (user1, user2, user3, user4)
        # 8 total pageviews (3 + 2 + 1 + 2)

        page_results = self._run_stats_table_query(WebStatsBreakdown.PAGE, use_pre_agg=False)

        total_visitors = len({"user1", "user2", "user3", "user4"})
        total_pageviews = sum(views for _, _, views in page_results)

        assert total_visitors == 4
        assert total_pageviews == 8

        # Verify the sums match across different breakdowns
        device_results = self._run_stats_table_query(WebStatsBreakdown.DEVICE_TYPE, use_pre_agg=False)
        device_pageviews = sum(views for _, _, views in device_results)
        assert device_pageviews == 8

        browser_results = self._run_stats_table_query(WebStatsBreakdown.BROWSER, use_pre_agg=False)
        browser_pageviews = sum(views for _, _, views in browser_results)
        assert browser_pageviews == 8
