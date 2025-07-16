from datetime import date
from unittest.mock import patch, MagicMock
import pytest
from typing import Any

from posthog.api.external_web_analytics.query_adapter import ExternalWebAnalyticsQueryAdapter
from posthog.api.external_web_analytics.serializers import WebAnalyticsOverviewRequestSerializer
from posthog.schema import WebOverviewItem, WebOverviewItemKind
from posthog.test.base import APIBaseTest


class TestExternalWebAnalyticsQueryAdapter(APIBaseTest):
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

    def test_transforms_all_metrics_correctly(self):
        with patch("posthog.api.external_web_analytics.query_adapter.WebOverviewQueryRunner") as mock_runner_class:
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

    def test_handles_edge_cases_gracefully(self):
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

        with patch("posthog.api.external_web_analytics.query_adapter.WebOverviewQueryRunner") as mock_runner_class:
            for case in test_cases:
                mock_runner = MagicMock()
                mock_runner.calculate.return_value = self._create_mock_overview_response(case["items"])
                mock_runner_class.return_value = mock_runner

                serializer = self._create_mock_overview_request_serializer()
                adapter = ExternalWebAnalyticsQueryAdapter(team=self.team)
                result = adapter.get_overview_data(serializer)

                assert result == case["expected"], f"Failed for case: {case}"

    def test_query_configuration_with_domain(self):
        with patch("posthog.api.external_web_analytics.query_adapter.WebOverviewQueryRunner") as mock_runner_class:
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

    def test_query_configuration_without_domain(self):
        with patch("posthog.api.external_web_analytics.query_adapter.WebOverviewQueryRunner") as mock_runner_class:
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

    def test_date_range_formatting(self):
        with patch("posthog.api.external_web_analytics.query_adapter.WebOverviewQueryRunner") as mock_runner_class:
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

    def test_modifiers_configuration(self):
        with patch("posthog.api.external_web_analytics.query_adapter.WebOverviewQueryRunner") as mock_runner_class:
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

    def test_filter_configuration_variations(self):
        test_cases = [
            {"filter_test_accounts": False, "do_path_cleaning": False},
            {"filter_test_accounts": True, "do_path_cleaning": False},
            {"filter_test_accounts": False, "do_path_cleaning": True},
            {"filter_test_accounts": True, "do_path_cleaning": True},
        ]

        with patch("posthog.api.external_web_analytics.query_adapter.WebOverviewQueryRunner") as mock_runner_class:
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

    def test_ignores_unknown_metrics(self):
        items = [
            WebOverviewItem(key="visitors", kind=WebOverviewItemKind.UNIT, value=100.0),
            WebOverviewItem(key="unknown_metric", kind=WebOverviewItemKind.UNIT, value=999.0),
            WebOverviewItem(key="another_unknown", kind=WebOverviewItemKind.PERCENTAGE, value=50.0),
        ]

        with patch("posthog.api.external_web_analytics.query_adapter.WebOverviewQueryRunner") as mock_runner_class:
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

    def test_percentage_conversion_boundary_cases(self):
        test_cases = [
            (0.0, 0.0),  # 0%
            (100.0, 1.0),  # 100%
            (50.5, 0.505),  # 50.5%
            (0.1, 0.001),  # 0.1%
        ]

        with patch("posthog.api.external_web_analytics.query_adapter.WebOverviewQueryRunner") as mock_runner_class:
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
