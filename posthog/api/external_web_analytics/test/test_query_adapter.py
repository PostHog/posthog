from datetime import date
from typing import Any

import pytest
from freezegun import freeze_time
from posthog.test.base import APIBaseTest, _create_event, _create_person, flush_persons_and_events
from unittest.mock import MagicMock, patch

from posthog.schema import WebAnalyticsItemKind, WebOverviewItem, WebStatsBreakdown

from posthog.api.external_web_analytics.query_adapter import ExternalWebAnalyticsQueryAdapter
from posthog.api.external_web_analytics.serializers import (
    EXTERNAL_WEB_ANALYTICS_NONE_BREAKDOWN_VALUE,
    WebAnalyticsBreakdownRequestSerializer,
    WebAnalyticsOverviewRequestSerializer,
)
from posthog.clickhouse.client.execute import sync_execute
from posthog.hogql_queries.web_analytics.test.web_preaggregated_test_base import WebAnalyticsPreAggregatedTestBase
from posthog.models.utils import uuid7
from posthog.models.web_preaggregated.sql import WEB_BOUNCES_INSERT_SQL, WEB_STATS_INSERT_SQL


class TestExternalWebAnalyticsQueryAdapterOverview(APIBaseTest):
    @pytest.fixture(autouse=True)
    def setup_fixtures(self):
        self.serializer_data = {
            "date_from": date(2025, 1, 1),
            "date_to": date(2025, 1, 31),
            "host": "example.com",
            "filter_test_accounts": True,
            "apply_path_cleaning": True,
        }

        self.sample_overview_items = [
            WebOverviewItem(
                key="visitors",
                kind=WebAnalyticsItemKind.UNIT,
                value=1500.0,
                previous=1200.0,
                changeFromPreviousPct=25.0,
                isIncreaseBad=False,
            ),
            WebOverviewItem(
                key="views",
                kind=WebAnalyticsItemKind.UNIT,
                value=5678.0,
                previous=4500.0,
                changeFromPreviousPct=26.2,
                isIncreaseBad=False,
            ),
            WebOverviewItem(
                key="sessions",
                kind=WebAnalyticsItemKind.UNIT,
                value=987.0,
                previous=850.0,
                changeFromPreviousPct=16.1,
                isIncreaseBad=False,
            ),
            WebOverviewItem(
                key="bounce rate",
                kind=WebAnalyticsItemKind.PERCENTAGE,
                value=45.0,  # 45%
                previous=50.0,
                changeFromPreviousPct=-10.0,
                isIncreaseBad=True,
            ),
            WebOverviewItem(
                key="session duration",
                kind=WebAnalyticsItemKind.DURATION_S,
                value=123.4,
                previous=115.2,
                changeFromPreviousPct=7.1,
                isIncreaseBad=False,
            ),
        ]

    def _create_mock_overview_request_serializer(self, **overrides):
        serializer = MagicMock(spec=WebAnalyticsOverviewRequestSerializer)
        data = {**self.serializer_data, **overrides}

        # Remove None values
        serializer.validated_data = {k: v for k, v in data.items() if v is not None}
        return serializer

    def _create_mock_overview_response(self, items):
        response = MagicMock()
        response.results = items
        response.samplingRate = MagicMock(numerator=1, denominator=1)
        response.dateFrom = "2025-01-01"
        response.dateTo = "2025-01-31"
        response.usedPreAggregatedTables = True
        return response

    @patch("posthog.api.external_web_analytics.query_adapter.WebOverviewQueryRunner")
    def test_transforms_all_metrics_correctly(self, mock_runner_class):
        mock_runner = MagicMock()
        mock_runner.calculate.return_value = self._create_mock_overview_response(self.sample_overview_items)
        mock_runner_class.return_value = mock_runner

        serializer = self._create_mock_overview_request_serializer()
        adapter = ExternalWebAnalyticsQueryAdapter(team=self.team)
        result = adapter.get_overview_data(serializer)

        assert result["visitors"] == 1500  # int conversion
        assert result["views"] == 5678
        assert result["sessions"] == 987
        assert result["bounce_rate"] == 0.45  # percentage to decimal
        assert result["session_duration"] == 123.4  # float preserved

    @patch("posthog.api.external_web_analytics.query_adapter.WebOverviewQueryRunner")
    def test_handles_edge_cases_gracefully(self, mock_runner_class):
        test_cases: list[dict[str, Any]] = [
            # Case 1: Null values
            {
                "items": [
                    WebOverviewItem(key="visitors", kind=WebAnalyticsItemKind.UNIT, value=None),
                    WebOverviewItem(key="bounce rate", kind=WebAnalyticsItemKind.PERCENTAGE, value=None),
                ],
                "expected": {
                    "visitors": 0,
                    "views": 0,
                    "sessions": 0,
                    "bounce_rate": 0.0,
                    "session_duration": 0.0,
                },
            },
            # Case 2: Empty results
            {
                "items": [],
                "expected": {
                    "visitors": 0,
                    "views": 0,
                    "sessions": 0,
                    "bounce_rate": 0.0,
                    "session_duration": 0.0,
                },
            },
            # Case 3: Only some metrics present
            {
                "items": [
                    WebOverviewItem(key="visitors", kind=WebAnalyticsItemKind.UNIT, value=100.0),
                    WebOverviewItem(key="sessions", kind=WebAnalyticsItemKind.UNIT, value=80.0),
                ],
                "expected": {
                    "visitors": 100,
                    "views": 0,
                    "sessions": 80,
                    "bounce_rate": 0.0,
                    "session_duration": 0.0,
                },
            },
        ]

        for case in test_cases:
            mock_runner = MagicMock()
            mock_runner.calculate.return_value = self._create_mock_overview_response(case["items"])
            mock_runner_class.return_value = mock_runner

            serializer = self._create_mock_overview_request_serializer()
            adapter = ExternalWebAnalyticsQueryAdapter(team=self.team)
            result = adapter.get_overview_data(serializer)

            assert result == case["expected"], f"Failed for case: {case}"

    @patch("posthog.api.external_web_analytics.query_adapter.WebOverviewQueryRunner")
    def test_query_configuration_with_host(self, mock_runner_class):
        mock_runner = MagicMock()
        mock_runner.calculate.return_value = self._create_mock_overview_response([])
        mock_runner_class.return_value = mock_runner

        serializer = self._create_mock_overview_request_serializer(host="app.example.com")
        adapter = ExternalWebAnalyticsQueryAdapter(team=self.team)
        adapter.get_overview_data(serializer)

        _, kwargs = mock_runner_class.call_args
        query = kwargs["query"]

        # Check host filter
        assert len(query.properties) == 1
        assert query.properties[0].key == "$host"
        assert query.properties[0].value == ["app.example.com"]

        # Check other configurations
        assert query.filterTestAccounts is True
        assert query.doPathCleaning is True
        assert query.includeRevenue is False
        assert query.compareFilter is None
        assert query.conversionGoal is None

    @patch("posthog.api.external_web_analytics.query_adapter.WebOverviewQueryRunner")
    def test_query_configuration_without_host(self, mock_runner_class):
        mock_runner = MagicMock()
        mock_runner.calculate.return_value = self._create_mock_overview_response([])
        mock_runner_class.return_value = mock_runner

        serializer = self._create_mock_overview_request_serializer(host=None)
        adapter = ExternalWebAnalyticsQueryAdapter(team=self.team)
        adapter.get_overview_data(serializer)

        _, kwargs = mock_runner_class.call_args
        query = kwargs["query"]

        # Should have no properties when the host is not provided
        assert len(query.properties) == 0

    @patch("posthog.api.external_web_analytics.query_adapter.WebOverviewQueryRunner")
    def test_date_range_formatting(self, mock_runner_class):
        mock_runner = MagicMock()
        mock_runner.calculate.return_value = self._create_mock_overview_response([])
        mock_runner_class.return_value = mock_runner

        serializer = self._create_mock_overview_request_serializer(
            date_from=date(2024, 12, 1), date_to=date(2024, 12, 31)
        )
        adapter = ExternalWebAnalyticsQueryAdapter(team=self.team)
        adapter.get_overview_data(serializer)

        _, kwargs = mock_runner_class.call_args
        query = kwargs["query"]

        assert query.dateRange.date_from == "2024-12-01"
        assert query.dateRange.date_to == "2024-12-31"

    @patch("posthog.api.external_web_analytics.query_adapter.WebOverviewQueryRunner")
    def test_modifiers_configuration(self, mock_runner_class):
        mock_runner = MagicMock()
        mock_runner.calculate.return_value = self._create_mock_overview_response([])
        mock_runner_class.return_value = mock_runner

        serializer = self._create_mock_overview_request_serializer()
        adapter = ExternalWebAnalyticsQueryAdapter(team=self.team)
        adapter.get_overview_data(serializer)

        _, kwargs = mock_runner_class.call_args
        modifiers = kwargs["modifiers"]

        # Should use preaggregated tables and convert timezone
        assert modifiers.useWebAnalyticsPreAggregatedTables is True
        assert modifiers.convertToProjectTimezone is True

    @patch("posthog.api.external_web_analytics.query_adapter.WebOverviewQueryRunner")
    def test_filter_configuration_variations(self, mock_runner_class):
        test_cases = [
            {"filter_test_accounts": False, "apply_path_cleaning": False},
            {"filter_test_accounts": True, "apply_path_cleaning": False},
            {"filter_test_accounts": False, "apply_path_cleaning": True},
            {"filter_test_accounts": True, "apply_path_cleaning": True},
        ]

        for filters in test_cases:
            mock_runner = MagicMock()
            mock_runner.calculate.return_value = self._create_mock_overview_response([])
            mock_runner_class.return_value = mock_runner

            serializer = self._create_mock_overview_request_serializer(**filters)
            adapter = ExternalWebAnalyticsQueryAdapter(team=self.team)
            adapter.get_overview_data(serializer)

            _, kwargs = mock_runner_class.call_args
            query = kwargs["query"]

            assert query.filterTestAccounts == filters["filter_test_accounts"]
            assert query.doPathCleaning == filters["apply_path_cleaning"]

    @patch("posthog.api.external_web_analytics.query_adapter.WebOverviewQueryRunner")
    def test_ignores_unknown_metrics(self, mock_runner_class):
        items = [
            WebOverviewItem(key="visitors", kind=WebAnalyticsItemKind.UNIT, value=100.0),
            WebOverviewItem(key="unknown_metric", kind=WebAnalyticsItemKind.UNIT, value=999.0),
            WebOverviewItem(key="another_unknown", kind=WebAnalyticsItemKind.PERCENTAGE, value=50.0),
        ]

        mock_runner = MagicMock()
        mock_runner.calculate.return_value = self._create_mock_overview_response(items)
        mock_runner_class.return_value = mock_runner

        serializer = self._create_mock_overview_request_serializer()
        adapter = ExternalWebAnalyticsQueryAdapter(team=self.team)
        result = adapter.get_overview_data(serializer)

        # Should only have the known metrics
        assert result["visitors"] == 100
        assert "unknown_metric" not in result
        assert "another_unknown" not in result

    @patch("posthog.api.external_web_analytics.query_adapter.WebOverviewQueryRunner")
    def test_percentage_conversion_boundary_cases(self, mock_runner_class):
        test_cases = [
            (0.0, 0.0),  # 0%
            (100.0, 1.0),  # 100%
            (50.5, 0.505),  # 50.5%
            (0.1, 0.001),  # 0.1%
        ]

        for internal_value, expected_external in test_cases:
            mock_runner = MagicMock()
            mock_runner.calculate.return_value = self._create_mock_overview_response(
                [WebOverviewItem(key="bounce rate", kind=WebAnalyticsItemKind.PERCENTAGE, value=internal_value)]
            )
            mock_runner_class.return_value = mock_runner

            serializer = self._create_mock_overview_request_serializer()
            adapter = ExternalWebAnalyticsQueryAdapter(team=self.team)
            result = adapter.get_overview_data(serializer)

            assert result["bounce_rate"] == expected_external


class TestExternalWebAnalyticsQueryAdapterBreakdown(APIBaseTest):
    @pytest.fixture(autouse=True)
    def setup_breakdown_fixtures(self):
        self.breakdown_serializer_data = {
            "date_from": date(2025, 1, 1),
            "date_to": date(2025, 1, 31),
            "breakdown_by": "Browser",
            "host": "example.com",
            "filter_test_accounts": True,
            "apply_path_cleaning": True,
            "limit": 100,
        }

    def _create_mock_breakdown_request_serializer(self, **overrides):
        serializer = MagicMock(spec=WebAnalyticsBreakdownRequestSerializer)
        data = {**self.breakdown_serializer_data, **overrides}
        serializer.validated_data = {k: v for k, v in data.items() if v is not None}
        return serializer

    def _create_mock_breakdown_response(self, columns, results):
        response = MagicMock()
        response.columns = columns
        response.results = results
        return response

    @patch("posthog.api.external_web_analytics.query_adapter.WebStatsTableQueryRunner")
    def test_breakdown_transforms_data_correctly(self, mock_runner_class):
        columns = ["context.columns.breakdown_value", "context.columns.visitors", "context.columns.views"]
        results = [
            ["Chrome", (150, 120), (500, 400)],
            ["Firefox", (100, 90), (300, 250)],
            ["Safari", (80, 70), (200, 180)],
        ]

        mock_runner = MagicMock()
        mock_runner.calculate.return_value = self._create_mock_breakdown_response(columns, results)
        mock_runner_class.return_value = mock_runner

        serializer = self._create_mock_breakdown_request_serializer()
        adapter = ExternalWebAnalyticsQueryAdapter(team=self.team)
        result = adapter.get_breakdown_data(serializer)

        assert len(result["results"]) == 3

        # Check first result
        first_result = result["results"][0]
        assert first_result["breakdown_value"] == "Chrome"
        assert first_result["visitors"] == 150
        assert first_result["views"] == 500

        # Check second result
        second_result = result["results"][1]
        assert second_result["breakdown_value"] == "Firefox"
        assert second_result["visitors"] == 100
        assert second_result["views"] == 300

    @patch("posthog.api.external_web_analytics.query_adapter.WebStatsTableQueryRunner")
    def test_breakdown_with_bounce_rate(self, mock_runner_class):
        columns = [
            "context.columns.breakdown_value",
            "context.columns.visitors",
            "context.columns.views",
            "context.columns.bounce_rate",
        ]
        results = [
            ["/home", (200, 180), (400, 350), (0.25, 0.30)],
            ["/about", (150, 130), (200, 180), (0.35, 0.40)],
        ]

        mock_runner = MagicMock()
        mock_runner.calculate.return_value = self._create_mock_breakdown_response(columns, results)
        mock_runner_class.return_value = mock_runner

        serializer = self._create_mock_breakdown_request_serializer(breakdown_by="Page")
        adapter = ExternalWebAnalyticsQueryAdapter(team=self.team)
        result = adapter.get_breakdown_data(serializer)

        assert len(result["results"]) == 2
        first_result = result["results"][0]
        assert first_result["breakdown_value"] == "/home"
        assert first_result["visitors"] == 200
        assert first_result["views"] == 400
        assert first_result["bounce_rate"] == 0.25

    @patch("posthog.api.external_web_analytics.query_adapter.WebStatsTableQueryRunner")
    def test_breakdown_handles_null_values(self, mock_runner_class):
        columns = ["context.columns.breakdown_value", "context.columns.visitors", "context.columns.views"]
        results = [
            ["Chrome", (150, 120), (500, 400)],
            [None, (50, 40), (100, 80)],
        ]

        mock_runner = MagicMock()
        mock_runner.calculate.return_value = self._create_mock_breakdown_response(columns, results)
        mock_runner_class.return_value = mock_runner

        serializer = self._create_mock_breakdown_request_serializer()
        adapter = ExternalWebAnalyticsQueryAdapter(team=self.team)
        result = adapter.get_breakdown_data(serializer)

        assert result["results"][0]["breakdown_value"] == "Chrome"
        assert result["results"][1]["breakdown_value"] == EXTERNAL_WEB_ANALYTICS_NONE_BREAKDOWN_VALUE

    @patch("posthog.api.external_web_analytics.query_adapter.WebStatsTableQueryRunner")
    def test_breakdown_empty_results(self, mock_runner_class):
        mock_runner = MagicMock()
        # Empty results but with valid columns structure
        columns = ["context.columns.breakdown_value", "context.columns.visitors"]
        mock_runner.calculate.return_value = self._create_mock_breakdown_response(columns, [])
        mock_runner_class.return_value = mock_runner

        serializer = self._create_mock_breakdown_request_serializer()
        adapter = ExternalWebAnalyticsQueryAdapter(team=self.team)
        result = adapter.get_breakdown_data(serializer)

        assert result["results"] == []
        assert result["next"] is None

    @patch("posthog.api.external_web_analytics.query_adapter.WebStatsTableQueryRunner")
    def test_breakdown_missing_columns_raises_error(self, mock_runner_class):
        mock_runner = MagicMock()
        # No columns indicates query execution error
        mock_runner.calculate.return_value = self._create_mock_breakdown_response([], [])
        mock_runner_class.return_value = mock_runner

        serializer = self._create_mock_breakdown_request_serializer()
        adapter = ExternalWebAnalyticsQueryAdapter(team=self.team)

        with pytest.raises(ValueError, match="Query response missing columns"):
            adapter.get_breakdown_data(serializer)

    @patch("posthog.api.external_web_analytics.query_adapter.WebStatsTableQueryRunner")
    def test_breakdown_query_configuration(self, mock_runner_class):
        mock_runner = MagicMock()
        columns = ["context.columns.breakdown_value", "context.columns.visitors"]
        mock_runner.calculate.return_value = self._create_mock_breakdown_response(columns, [])
        mock_runner_class.return_value = mock_runner

        serializer = self._create_mock_breakdown_request_serializer(
            breakdown_by="DeviceType", filter_test_accounts=False, apply_path_cleaning=False, limit=50
        )
        adapter = ExternalWebAnalyticsQueryAdapter(team=self.team)
        adapter.get_breakdown_data(serializer)

        _, kwargs = mock_runner_class.call_args
        query = kwargs["query"]

        assert query.breakdownBy == WebStatsBreakdown.DEVICE_TYPE
        assert query.filterTestAccounts is False
        assert query.doPathCleaning is False
        assert query.limit == 50
        assert query.includeBounceRate is False

    @patch("posthog.api.external_web_analytics.query_adapter.WebStatsTableQueryRunner")
    def test_breakdown_with_bounce_rate_breakdowns(self, mock_runner_class):
        bounce_rate_breakdowns = ["InitialPage", "Page"]

        for breakdown_by in bounce_rate_breakdowns:
            mock_runner = MagicMock()
            columns = ["context.columns.breakdown_value", "context.columns.visitors"]
            mock_runner.calculate.return_value = self._create_mock_breakdown_response(columns, [])
            mock_runner_class.return_value = mock_runner

            serializer = self._create_mock_breakdown_request_serializer(breakdown_by=breakdown_by)
            adapter = ExternalWebAnalyticsQueryAdapter(team=self.team)
            adapter.get_breakdown_data(serializer)

            _, kwargs = mock_runner_class.call_args
            query = kwargs["query"]

            assert query.includeBounceRate is True, f"Failed for breakdown_by: {breakdown_by}"

    @patch("posthog.api.external_web_analytics.query_adapter.WebStatsTableQueryRunner")
    def test_breakdown_enum_conversion(self, mock_runner_class):
        breakdown_mappings = {
            "Browser": WebStatsBreakdown.BROWSER,
            "DeviceType": WebStatsBreakdown.DEVICE_TYPE,
            "OS": WebStatsBreakdown.OS,
            "Country": WebStatsBreakdown.COUNTRY,
            "Page": WebStatsBreakdown.PAGE,
            "InitialPage": WebStatsBreakdown.INITIAL_PAGE,
        }

        for breakdown_str, expected_enum in breakdown_mappings.items():
            mock_runner = MagicMock()
            columns = ["context.columns.breakdown_value", "context.columns.visitors"]
            mock_runner.calculate.return_value = self._create_mock_breakdown_response(columns, [])
            mock_runner_class.return_value = mock_runner

            serializer = self._create_mock_breakdown_request_serializer(breakdown_by=breakdown_str)
            adapter = ExternalWebAnalyticsQueryAdapter(team=self.team)
            adapter.get_breakdown_data(serializer)

            _, kwargs = mock_runner_class.call_args
            query = kwargs["query"]

            assert query.breakdownBy == expected_enum, f"Failed for breakdown: {breakdown_str}"

    @patch("posthog.api.external_web_analytics.query_adapter.WebStatsTableQueryRunner")
    def test_breakdown_with_host_filter(self, mock_runner_class):
        mock_runner = MagicMock()
        columns = ["context.columns.breakdown_value", "context.columns.visitors"]
        mock_runner.calculate.return_value = self._create_mock_breakdown_response(columns, [])
        mock_runner_class.return_value = mock_runner

        serializer = self._create_mock_breakdown_request_serializer(host="app.example.com")
        adapter = ExternalWebAnalyticsQueryAdapter(team=self.team)
        adapter.get_breakdown_data(serializer)

        _, kwargs = mock_runner_class.call_args
        query = kwargs["query"]

        assert len(query.properties) == 1
        assert query.properties[0].key == "$host"
        assert query.properties[0].value == ["app.example.com"]

    @patch("posthog.api.external_web_analytics.query_adapter.WebStatsTableQueryRunner")
    def test_breakdown_type_conversions(self, mock_runner_class):
        columns = [
            "context.columns.breakdown_value",
            "context.columns.visitors",
            "context.columns.views",
            "context.columns.bounce_rate",
        ]
        results = [
            ["/home", (150.0, 120.0), (500.0, 400.0), (0.25, 0.30)],
        ]

        mock_runner = MagicMock()
        mock_runner.calculate.return_value = self._create_mock_breakdown_response(columns, results)
        mock_runner_class.return_value = mock_runner

        serializer = self._create_mock_breakdown_request_serializer(breakdown_by="Page")
        adapter = ExternalWebAnalyticsQueryAdapter(team=self.team)
        result = adapter.get_breakdown_data(serializer)

        first_result = result["results"][0]
        assert isinstance(first_result["visitors"], int)
        assert isinstance(first_result["views"], int)
        assert isinstance(first_result["bounce_rate"], float)

    @patch("posthog.api.external_web_analytics.query_adapter.WebStatsTableQueryRunner")
    def test_breakdown_modifiers_configuration(self, mock_runner_class):
        mock_runner = MagicMock()
        columns = ["context.columns.breakdown_value", "context.columns.visitors"]
        mock_runner.calculate.return_value = self._create_mock_breakdown_response(columns, [])
        mock_runner_class.return_value = mock_runner

        serializer = self._create_mock_breakdown_request_serializer()
        adapter = ExternalWebAnalyticsQueryAdapter(team=self.team)
        adapter.get_breakdown_data(serializer)

        _, kwargs = mock_runner_class.call_args
        modifiers = kwargs["modifiers"]

        assert modifiers.useWebAnalyticsPreAggregatedTables is True
        assert modifiers.convertToProjectTimezone is True


class TestExternalWebAnalyticsQueryAdapterIntegration(WebAnalyticsPreAggregatedTestBase):
    """Integration tests that hit actual pre-aggregated tables"""

    def _setup_test_data(self):
        with freeze_time("2024-01-01T09:00:00Z"):
            sessions = [str(uuid7("2024-01-01")) for _ in range(10)]

            for i in range(10):
                _create_person(team_id=self.team.pk, distinct_ids=[f"user_{i}"])

            # Desktop user - Chrome, Windows, US
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

            # Mobile user - Safari, iOS, Canada
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id="user_1",
                timestamp="2024-01-01T11:00:00Z",
                properties={
                    "$session_id": sessions[1],
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

            # Desktop user - Firefox, macOS, UK
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id="user_2",
                timestamp="2024-01-01T12:00:00Z",
                properties={
                    "$session_id": sessions[2],
                    "$current_url": "https://example.com/features",
                    "$pathname": "/features",
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

            flush_persons_and_events()
            self._populate_preaggregated_tables()

            # Clear events table to ensure tests only pass if using pre-aggregated tables
            sync_execute("TRUNCATE TABLE events")

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

    def test_overview_data_integration_smoke_test(self):
        adapter = ExternalWebAnalyticsQueryAdapter(self.team)

        serializer = WebAnalyticsOverviewRequestSerializer(
            data={
                "date_from": "2024-01-01",
                "date_to": "2024-01-02",
            }
        )
        serializer.is_valid(raise_exception=True)

        result = adapter.get_overview_data(serializer)

        # Verify the response structure
        assert "visitors" in result
        assert "views" in result
        assert "sessions" in result
        assert "bounce_rate" in result
        assert "session_duration" in result

        # Verify we actually got data from our test setup
        assert result["visitors"] == 3  # user_0, user_1, user_2
        assert result["views"] == 3  # 3 pageviews total
        assert result["sessions"] == 3  # 3 sessions total

    def test_breakdown_data_integration_smoke_test(self):
        adapter = ExternalWebAnalyticsQueryAdapter(self.team)

        serializer = WebAnalyticsBreakdownRequestSerializer(
            data={
                "breakdown_by": "DeviceType",
                "date_from": "2024-01-01",
                "date_to": "2024-01-02",
            }
        )
        serializer.is_valid(raise_exception=True)

        result = adapter.get_breakdown_data(serializer)

        # Verify the response structure
        assert "results" in result
        assert "next" in result

        # Verify we actually got data from our test setup
        assert len(result["results"]) == 2  # Desktop and Mobile

        # Sort results for consistent testing
        results = sorted(result["results"], key=lambda x: x["breakdown_value"])

        # Desktop: user_0, user_2 (2 visitors, 2 views)
        desktop_result = next(r for r in results if r["breakdown_value"] == "Desktop")
        assert desktop_result["visitors"] == 2
        assert desktop_result["views"] == 2

        # Mobile: user_1 (1 visitor, 1 view)
        mobile_result = next(r for r in results if r["breakdown_value"] == "Mobile")
        assert mobile_result["visitors"] == 1
        assert mobile_result["views"] == 1

    def test_breakdown_data_with_bounce_rate_integration(self):
        adapter = ExternalWebAnalyticsQueryAdapter(self.team)

        serializer = WebAnalyticsBreakdownRequestSerializer(
            data={
                "breakdown_by": "Page",
                "date_from": "2024-01-01",
                "date_to": "2024-01-02",
            }
        )
        serializer.is_valid(raise_exception=True)

        result = adapter.get_breakdown_data(serializer)

        # Verify we got results
        assert len(result["results"]) == 3  # /landing, /pricing, /features

        # Check that results have bounce_rate
        for row in result["results"]:
            assert "bounce_rate" in row
            assert isinstance(row["bounce_rate"], float)

    def test_breakdown_data_with_host_filter_integration(self):
        adapter = ExternalWebAnalyticsQueryAdapter(self.team)

        serializer = WebAnalyticsBreakdownRequestSerializer(
            data={
                "breakdown_by": "DeviceType",
                "date_from": "2024-01-01",
                "date_to": "2024-01-02",
                "host": "example.com",
            }
        )
        serializer.is_valid(raise_exception=True)

        result = adapter.get_breakdown_data(serializer)

        # Should still get results since all our test data is from example.com
        assert len(result["results"]) == 2

        # Test with different host - should get no results
        serializer = WebAnalyticsBreakdownRequestSerializer(
            data={
                "breakdown_by": "DeviceType",
                "date_from": "2024-01-01",
                "date_to": "2024-01-02",
                "host": "different.com",
            }
        )
        serializer.is_valid(raise_exception=True)

        result = adapter.get_breakdown_data(serializer)
        assert len(result["results"]) == 0

    def test_overview_data_with_host_filter_integration(self):
        adapter = ExternalWebAnalyticsQueryAdapter(self.team)

        serializer = WebAnalyticsOverviewRequestSerializer(
            data={
                "date_from": "2024-01-01",
                "date_to": "2024-01-02",
                "host": "example.com",
            }
        )
        serializer.is_valid(raise_exception=True)

        result = adapter.get_overview_data(serializer)

        # Should get results since all our test data is from example.com
        assert result["visitors"] == 3
        assert result["views"] == 3

        # Test with different host - should get no results
        serializer = WebAnalyticsOverviewRequestSerializer(
            data={
                "date_from": "2024-01-01",
                "date_to": "2024-01-02",
                "host": "different.com",
            }
        )
        serializer.is_valid(raise_exception=True)

        result = adapter.get_overview_data(serializer)
        assert result["visitors"] == 0
        assert result["views"] == 0

    def test_breakdown_pagination_integration(self):
        mock_request = MagicMock()
        mock_request.build_absolute_uri.return_value = "http://testserver/api/external/web-analytics/breakdown"
        adapter = ExternalWebAnalyticsQueryAdapter(self.team, request=mock_request)

        # Test first page with limit of 2
        serializer = WebAnalyticsBreakdownRequestSerializer(
            data={
                "breakdown_by": "Page",
                "date_from": "2024-01-01",
                "date_to": "2024-01-02",
                "limit": 2,
                "offset": 0,
            }
        )
        serializer.is_valid(raise_exception=True)

        result_page1 = adapter.get_breakdown_data(serializer)

        assert len(result_page1["results"]) == 2

        # Sort results by breakdown_value for consistent testing
        sorted_results_page1 = sorted(result_page1["results"], key=lambda x: x["breakdown_value"])

        assert result_page1["next"] is not None
        assert "limit=2" in result_page1["next"]
        assert "offset=2" in result_page1["next"]

        for result in sorted_results_page1:
            assert "breakdown_value" in result
            assert "visitors" in result
            assert "views" in result
            assert "bounce_rate" in result  # Page breakdown supports bounce_rate

        # Test second page
        serializer_page2 = WebAnalyticsBreakdownRequestSerializer(
            data={
                "breakdown_by": "Page",
                "date_from": "2024-01-01",
                "date_to": "2024-01-02",
                "limit": 2,
                "offset": 2,
            }
        )
        serializer_page2.is_valid(raise_exception=True)

        result_page2 = adapter.get_breakdown_data(serializer_page2)

        assert len(result_page2["results"]) == 1  # 3 total pages, we already showed 2

        sorted_results_page2 = sorted(result_page2["results"], key=lambda x: x["breakdown_value"])

        # Verify the results are different pages
        page1_values = {r["breakdown_value"] for r in sorted_results_page1}
        page2_values = {r["breakdown_value"] for r in sorted_results_page2}
        assert len(page1_values.intersection(page2_values)) == 0  # No overlap

        assert result_page2["next"] is None

        # Verify all pages together are the expected ones
        all_values = page1_values.union(page2_values)
        expected_pages = {"/features", "/landing", "/pricing"}
        assert all_values == expected_pages
