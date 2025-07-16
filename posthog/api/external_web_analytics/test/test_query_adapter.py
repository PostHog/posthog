from datetime import date
from unittest.mock import patch, MagicMock
import pytest
from typing import Any

from posthog.api.external_web_analytics.query_adapter import ExternalWebAnalyticsQueryAdapter
from posthog.api.external_web_analytics.serializers import (
    EXTERNAL_WEB_ANALYTICS_NONE_BREAKDOWN_VALUE,
    WebAnalyticsOverviewRequestSerializer,
    WebAnalyticsBreakdownRequestSerializer,
)
from posthog.schema import WebOverviewItem, WebOverviewItemKind, WebStatsBreakdown
from posthog.test.base import APIBaseTest


class TestExternalWebAnalyticsQueryAdapterOverview(APIBaseTest):
    @pytest.fixture(autouse=True)
    def setup_fixtures(self):
        self.serializer_data = {
            "date_from": date(2025, 1, 1),
            "date_to": date(2025, 1, 31),
            "domain": "example.com",
            "filter_test_accounts": True,
            "do_path_cleaning": True,
        }

        self.sample_overview_items = [
            WebOverviewItem(
                key="visitors",
                kind=WebOverviewItemKind.UNIT,
                value=1500.0,
                previous=1200.0,
                changeFromPreviousPct=25.0,
                isIncreaseBad=False,
            ),
            WebOverviewItem(
                key="views",
                kind=WebOverviewItemKind.UNIT,
                value=5678.0,
                previous=4500.0,
                changeFromPreviousPct=26.2,
                isIncreaseBad=False,
            ),
            WebOverviewItem(
                key="sessions",
                kind=WebOverviewItemKind.UNIT,
                value=987.0,
                previous=850.0,
                changeFromPreviousPct=16.1,
                isIncreaseBad=False,
            ),
            WebOverviewItem(
                key="bounce rate",
                kind=WebOverviewItemKind.PERCENTAGE,
                value=45.0,  # 45%
                previous=50.0,
                changeFromPreviousPct=-10.0,
                isIncreaseBad=True,
            ),
            WebOverviewItem(
                key="session duration",
                kind=WebOverviewItemKind.DURATION_S,
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
                    WebOverviewItem(key="visitors", kind=WebOverviewItemKind.UNIT, value=None),
                    WebOverviewItem(key="bounce rate", kind=WebOverviewItemKind.PERCENTAGE, value=None),
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
                    WebOverviewItem(key="visitors", kind=WebOverviewItemKind.UNIT, value=100.0),
                    WebOverviewItem(key="sessions", kind=WebOverviewItemKind.UNIT, value=80.0),
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
    def test_query_configuration_with_domain(self, mock_runner_class):
        mock_runner = MagicMock()
        mock_runner.calculate.return_value = self._create_mock_overview_response([])
        mock_runner_class.return_value = mock_runner

        serializer = self._create_mock_overview_request_serializer(domain="app.example.com")
        adapter = ExternalWebAnalyticsQueryAdapter(team=self.team)
        adapter.get_overview_data(serializer)

        _, kwargs = mock_runner_class.call_args
        query = kwargs["query"]

        # Check domain filter
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
    def test_query_configuration_without_domain(self, mock_runner_class):
        mock_runner = MagicMock()
        mock_runner.calculate.return_value = self._create_mock_overview_response([])
        mock_runner_class.return_value = mock_runner

        serializer = self._create_mock_overview_request_serializer(domain=None)
        adapter = ExternalWebAnalyticsQueryAdapter(team=self.team)
        adapter.get_overview_data(serializer)

        _, kwargs = mock_runner_class.call_args
        query = kwargs["query"]

        # Should have no properties when the domain is not provided
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
            {"filter_test_accounts": False, "do_path_cleaning": False},
            {"filter_test_accounts": True, "do_path_cleaning": False},
            {"filter_test_accounts": False, "do_path_cleaning": True},
            {"filter_test_accounts": True, "do_path_cleaning": True},
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
            assert query.doPathCleaning == filters["do_path_cleaning"]

    @patch("posthog.api.external_web_analytics.query_adapter.WebOverviewQueryRunner")
    def test_ignores_unknown_metrics(self, mock_runner_class):
        items = [
            WebOverviewItem(key="visitors", kind=WebOverviewItemKind.UNIT, value=100.0),
            WebOverviewItem(key="unknown_metric", kind=WebOverviewItemKind.UNIT, value=999.0),
            WebOverviewItem(key="another_unknown", kind=WebOverviewItemKind.PERCENTAGE, value=50.0),
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
                [WebOverviewItem(key="bounce rate", kind=WebOverviewItemKind.PERCENTAGE, value=internal_value)]
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
            "domain": "example.com",
            "filter_test_accounts": True,
            "do_path_cleaning": True,
            "limit": 100,
            "metrics": ["visitors", "views"],
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

        assert result["count"] == 3
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

        serializer = self._create_mock_breakdown_request_serializer(
            breakdown_by="Page", metrics=["visitors", "views", "bounce_rate"]
        )
        adapter = ExternalWebAnalyticsQueryAdapter(team=self.team)
        result = adapter.get_breakdown_data(serializer)

        assert result["count"] == 2
        first_result = result["results"][0]
        assert first_result["breakdown_value"] == "/home"
        assert first_result["visitors"] == 200
        assert first_result["views"] == 400
        assert first_result["bounce_rate"] == 0.25

    @patch("posthog.api.external_web_analytics.query_adapter.WebStatsTableQueryRunner")
    def test_breakdown_filters_metrics_correctly(self, mock_runner_class):
        columns = [
            "context.columns.breakdown_value",
            "context.columns.visitors",
            "context.columns.views",
            "context.columns.bounce_rate",
        ]
        results = [
            ["Chrome", (150, 120), (500, 400), (0.25, 0.30)],
        ]

        mock_runner = MagicMock()
        mock_runner.calculate.return_value = self._create_mock_breakdown_response(columns, results)
        mock_runner_class.return_value = mock_runner

        serializer = self._create_mock_breakdown_request_serializer(metrics=["visitors"])
        adapter = ExternalWebAnalyticsQueryAdapter(team=self.team)
        result = adapter.get_breakdown_data(serializer)

        first_result = result["results"][0]
        assert "breakdown_value" in first_result
        assert "visitors" in first_result
        assert "views" not in first_result
        assert "bounce_rate" not in first_result

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

        assert result["count"] == 2
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

        assert result["count"] == 0
        assert result["results"] == []
        assert result["next"] is None
        assert result["previous"] is None

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
            breakdown_by="DeviceType", filter_test_accounts=False, do_path_cleaning=False, limit=50
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
    def test_breakdown_with_domain_filter(self, mock_runner_class):
        mock_runner = MagicMock()
        columns = ["context.columns.breakdown_value", "context.columns.visitors"]
        mock_runner.calculate.return_value = self._create_mock_breakdown_response(columns, [])
        mock_runner_class.return_value = mock_runner

        serializer = self._create_mock_breakdown_request_serializer(domain="app.example.com")
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

        serializer = self._create_mock_breakdown_request_serializer(
            breakdown_by="Page", metrics=["visitors", "views", "bounce_rate"]
        )
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
