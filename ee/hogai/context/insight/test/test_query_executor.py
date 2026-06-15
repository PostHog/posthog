from datetime import date, datetime
from decimal import Decimal
from typing import Any

from freezegun import freeze_time
from posthog.test.base import NonAtomicBaseTest
from unittest.mock import Mock, patch

from django.test import override_settings

from rest_framework.exceptions import APIException

from posthog.schema import (
    AssistantFunnelsQuery,
    AssistantHogQLQuery,
    AssistantRetentionEventsNode,
    AssistantRetentionFilter,
    AssistantRetentionQuery,
    AssistantStickinessQuery,
    AssistantTrendsEventsNode,
    AssistantTrendsQuery,
    ChartDisplayType,
    DataVisualizationNode,
    DateRange,
    EventsNode,
    FunnelsQuery,
    HogQLQuery,
    IntervalType,
    LifecycleQuery,
    PathsFilter,
    PathsQuery,
    RetentionFilter,
    RetentionQuery,
    RevenueAnalyticsBreakdown,
    RevenueAnalyticsGrossRevenueQuery,
    RevenueAnalyticsMetricsQuery,
    RevenueAnalyticsMRRQuery,
    RevenueAnalyticsMRRQueryResultItem,
    RevenueAnalyticsTopCustomersGroupBy,
    RevenueAnalyticsTopCustomersQuery,
    StickinessQuery,
    TrendsFilter,
    TrendsQuery,
)

from posthog.hogql.constants import DEFAULT_POSTHOG_AI_RETURNED_ROWS
from posthog.hogql.errors import ExposedHogQLError

from posthog.clickhouse.query_tagging import Feature, Product, get_query_tags, tags_context
from posthog.errors import ExposedCHQueryError

from ee.hogai.context.insight.query_executor import (
    AssistantQueryExecutor,
    execute_and_format_query,
    get_example_prompt,
    is_supported_query,
)
from ee.hogai.tool_errors import MaxToolRetryableError
from ee.hogai.utils.query import validate_assistant_query


class TestAssistantQueryExecutor(NonAtomicBaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def setUp(self):
        super().setUp()
        with freeze_time("2025-01-20T12:00:00Z"):
            self.query_runner = AssistantQueryExecutor(self.team, datetime.now())

    @patch("ee.hogai.context.insight.query_executor.process_query_dict")
    async def test_run_and_format_query_trends(self, mock_process_query):
        """Test successful execution and formatting of trends query"""
        mock_process_query.return_value = {
            "results": [{"data": [1, 2, 3], "label": "test", "days": ["2025-01-01", "2025-01-02", "2025-01-03"]}]
        }

        query = AssistantTrendsQuery(series=[])
        result, used_fallback = await self.query_runner.arun_and_format_query(query)

        self.assertIsInstance(result, str)
        self.assertFalse(used_fallback)
        self.assertIn("Date|test", result)
        mock_process_query.assert_called_once()

    @patch("ee.hogai.context.insight.query_executor.process_query_dict")
    async def test_run_and_format_query_funnels(self, mock_process_query):
        """Test successful execution and formatting of funnels query"""
        mock_process_query.return_value = {
            "results": [
                {
                    "action_id": "test",
                    "name": "test",
                    "order": 0,
                    "count": 100,
                    "average_conversion_time": None,
                    "median_conversion_time": None,
                }
            ]
        }

        query = AssistantFunnelsQuery(series=[])
        result, used_fallback = await self.query_runner.arun_and_format_query(query)

        self.assertIsInstance(result, str)
        self.assertFalse(used_fallback)
        self.assertIn("Metric|test", result)
        mock_process_query.assert_called_once()

    @patch("ee.hogai.context.insight.query_executor.process_query_dict")
    async def test_run_and_format_query_retention(self, mock_process_query):
        """Test successful execution and formatting of retention query"""
        mock_process_query.return_value = {
            "results": [{"date": "2025-01-01", "label": "Day 0", "values": [{"count": 100}]}]
        }

        query = AssistantRetentionQuery(
            retentionFilter=AssistantRetentionFilter(
                targetEntity=AssistantRetentionEventsNode(id="event"),
                returningEntity=AssistantRetentionEventsNode(id="event"),
            )
        )
        result, used_fallback = await self.query_runner.arun_and_format_query(query)

        self.assertIsInstance(result, str)
        self.assertFalse(used_fallback)
        self.assertIn("Date|Number of persons on date", result)
        mock_process_query.assert_called_once()

    @patch("ee.hogai.context.insight.query_executor.process_query_dict")
    async def test_run_and_format_query_sql(self, mock_process_query):
        """Test successful execution and formatting of SQL query"""
        mock_process_query.return_value = {"results": [{"count": 100}, {"count": 200}], "columns": ["count"]}

        query = AssistantHogQLQuery(query="SELECT count() FROM events")
        result, used_fallback = await self.query_runner.arun_and_format_query(query)

        self.assertIsInstance(result, str)
        self.assertFalse(used_fallback)
        self.assertIn("count\n100\n200", result)
        mock_process_query.assert_called_once()

    @patch("ee.hogai.context.insight.query_executor.process_query_dict")
    async def test_run_and_format_query_data_visualization_sql(self, mock_process_query):
        mock_process_query.return_value = {"results": [{"count": 100}, {"count": 200}], "columns": ["count"]}

        query = DataVisualizationNode(source=HogQLQuery(query="SELECT count() FROM events"))
        result, used_fallback = await self.query_runner.arun_and_format_query(query)

        self.assertIsInstance(result, str)
        self.assertFalse(used_fallback)
        self.assertIn("count\n100\n200", result)
        mock_process_query.assert_called_once()

    @patch("ee.hogai.context.insight.query_executor.process_query_dict")
    async def test_run_and_format_query_with_fallback_info_no_fallback(self, mock_process_query):
        """Test run_and_format_query_with_fallback_info returns fallback info"""
        mock_process_query.return_value = {
            "results": [{"data": [1, 2, 3], "label": "test", "days": ["2025-01-01", "2025-01-02", "2025-01-03"]}]
        }

        query = AssistantTrendsQuery(series=[])
        result, used_fallback = await self.query_runner.arun_and_format_query(query)

        self.assertIsInstance(result, str)
        self.assertFalse(used_fallback)
        self.assertIn("Date|test", result)

    @patch("ee.hogai.context.insight.query_executor.capture_exception")
    @patch("ee.hogai.context.insight.query_executor.process_query_dict")
    async def test_run_and_format_query_with_fallback_on_compression_error(self, mock_process_query, mock_capture):
        """Test fallback to JSON when compression fails and capture_exception is called"""
        mock_process_query.return_value = {"results": [{"invalid": "data"}]}

        # Use a query that will cause compression to fail
        query = AssistantTrendsQuery(series=[])

        with patch(
            "ee.hogai.context.insight.format.TrendsResultsFormatter.format",
            side_effect=Exception("Compression failed"),
        ):
            result, used_fallback = await self.query_runner.arun_and_format_query(query)

        self.assertIsInstance(result, str)
        self.assertTrue(used_fallback)
        # Should be JSON formatted
        self.assertIn('{"invalid":"data"}', result)
        # Should capture the exception for non-NotImplementedError
        mock_capture.assert_called_once()

    @patch("ee.hogai.context.insight.query_executor.capture_exception")
    @patch("ee.hogai.context.insight.query_executor.process_query_dict")
    async def test_run_and_format_query_with_fallback_on_not_implemented_error_no_capture(
        self, mock_process_query, mock_capture
    ):
        """Test fallback to JSON when NotImplementedError is raised - should NOT capture exception"""
        mock_process_query.return_value = {"results": [{"path": "data"}]}

        query = AssistantTrendsQuery(series=[])

        with patch.object(
            self.query_runner,
            "_compress_results",
            side_effect=NotImplementedError("Unsupported query type"),
        ):
            result, used_fallback = await self.query_runner.arun_and_format_query(query)

        self.assertIsInstance(result, str)
        self.assertTrue(used_fallback)
        # Should NOT capture NotImplementedError
        mock_capture.assert_not_called()

    @patch("ee.hogai.context.insight.query_executor.process_query_dict")
    async def test_run_and_format_query_handles_api_exception(self, mock_process_query):
        """Test handling of APIException"""

        mock_process_query.side_effect = APIException("API error message")

        query = AssistantTrendsQuery(series=[])

        with self.assertRaises(MaxToolRetryableError) as context:
            await self.query_runner.arun_and_format_query(query)

        self.assertIn("API error message", str(context.exception))

    @patch("ee.hogai.context.insight.query_executor.process_query_dict")
    async def test_run_and_format_query_handles_exposed_hogql_error(self, mock_process_query):
        """Test handling of ExposedHogQLError"""

        mock_process_query.side_effect = ExposedHogQLError("HogQL error")

        query = AssistantHogQLQuery(query="SELECT invalid")

        with self.assertRaises(MaxToolRetryableError) as context:
            await self.query_runner.arun_and_format_query(query)

        self.assertIn("HogQL error", str(context.exception))

    @patch("ee.hogai.context.insight.query_executor.process_query_dict")
    async def test_run_and_format_query_handles_exposed_ch_query_error(self, mock_process_query):
        """Test handling of ExposedCHQueryError"""

        mock_process_query.side_effect = ExposedCHQueryError("ClickHouse error")

        query = AssistantTrendsQuery(series=[])

        with self.assertRaises(MaxToolRetryableError) as context:
            await self.query_runner.arun_and_format_query(query)

        self.assertIn("ClickHouse error", str(context.exception))

    @patch("ee.hogai.context.insight.query_executor.process_query_dict")
    async def test_run_and_format_query_handles_generic_exception(self, mock_process_query):
        """Test handling of generic exceptions"""
        mock_process_query.side_effect = ValueError("Some other error")

        query = AssistantTrendsQuery(series=[])

        with self.assertRaises(Exception) as context:
            await self.query_runner.arun_and_format_query(query)

        self.assertIn("There was an unknown error running this query.", str(context.exception))

    @patch("ee.hogai.context.insight.query_executor.process_query_dict")
    @patch("ee.hogai.context.insight.query_executor.get_query_status")
    async def test_async_query_polling_success(self, mock_get_query_status, mock_process_query):
        """Test successful async query polling"""
        # Initial response with incomplete query
        mock_process_query.return_value = {"query_status": {"id": "test-query-id", "complete": False}}

        # Mock polling responses
        mock_get_query_status.side_effect = [
            Mock(model_dump=lambda mode: {"id": "test-query-id", "complete": False}),  # Still running
            Mock(
                model_dump=lambda mode: {
                    "id": "test-query-id",
                    "complete": True,
                    "results": {"results": [{"data": [1], "label": "test", "days": ["2025-01-01"]}]},
                }
            ),  # Complete
        ]

        query = AssistantTrendsQuery(series=[])

        with patch("ee.hogai.context.insight.query_executor.asyncio.sleep") as mock_sleep:
            result, used_fallback = await self.query_runner.arun_and_format_query(query)

        self.assertIsInstance(result, str)
        self.assertFalse(used_fallback)
        self.assertIn("Date|test", result)
        self.assertEqual(mock_get_query_status.call_count, 2)
        self.assertEqual(mock_sleep.call_count, 2)

    @patch("ee.hogai.context.insight.query_executor.process_query_dict")
    @patch("ee.hogai.context.insight.query_executor.get_query_status")
    async def test_async_query_polling_timeout(self, mock_get_query_status, mock_process_query):
        """Test async query polling timeout"""
        # Initial response with incomplete query
        mock_process_query.return_value = {"query_status": {"id": "test-query-id", "complete": False}}

        # Mock polling to always return incomplete
        mock_get_query_status.return_value = Mock(model_dump=lambda mode: {"id": "test-query-id", "complete": False})

        query = AssistantTrendsQuery(series=[])

        with patch("ee.hogai.context.insight.query_executor.asyncio.sleep"):
            with self.assertRaises(Exception) as context:
                await self.query_runner.arun_and_format_query(query)

        self.assertIn("Query hasn't completed in time", str(context.exception))

    @patch("ee.hogai.context.insight.query_executor.process_query_dict")
    @patch("ee.hogai.context.insight.query_executor.get_query_status")
    async def test_async_query_polling_with_error(self, mock_get_query_status, mock_process_query):
        """Test async query polling that returns an error"""
        # Initial response with incomplete query
        mock_process_query.return_value = {"query_status": {"id": "test-query-id", "complete": False}}

        # Mock polling to return error
        mock_get_query_status.return_value = Mock(
            model_dump=lambda mode: {
                "id": "test-query-id",
                "complete": True,
                "error": True,
                "error_message": "Query failed with error",
            }
        )

        query = AssistantTrendsQuery(series=[])

        with patch("ee.hogai.context.insight.query_executor.asyncio.sleep"):
            with self.assertRaises(Exception) as context:
                await self.query_runner.arun_and_format_query(query)

        self.assertIn("Query failed with error", str(context.exception))

    @override_settings(TEST=False)
    @patch("ee.hogai.context.insight.query_executor.process_query_dict")
    async def test_execution_mode_in_production(self, mock_process_query):
        """Test that production uses correct execution mode"""
        mock_process_query.return_value = {"results": [{"data": [1], "label": "test", "days": ["2025-01-01"]}]}

        query = AssistantTrendsQuery(series=[])
        result, used_fallback = await self.query_runner.arun_and_format_query(query)

        # Check that the execution mode was set correctly (not CALCULATE_BLOCKING_ALWAYS which is test mode)
        call_args = mock_process_query.call_args
        self.assertIn("execution_mode", call_args.kwargs)
        # In production it should be RECENT_CACHE_CALCULATE_ASYNC_IF_STALE
        from posthog.hogql_queries.query_runner import ExecutionMode

        self.assertEqual(call_args.kwargs["execution_mode"], ExecutionMode.RECENT_CACHE_CALCULATE_ASYNC_IF_STALE)

    async def test_compress_results_full_ui_queries(self):
        """Test _compress_results works with full UI query types by casting to assistant types"""
        # Test TrendsQuery -> AssistantTrendsQuery casting
        trends_query = TrendsQuery(series=[])
        response = {"results": [{"data": [1], "label": "test", "days": ["2025-01-01"]}]}
        result = await self.query_runner._compress_results(trends_query, response)
        self.assertIn("Date|test", result)

        # Test FunnelsQuery -> AssistantFunnelsQuery casting
        funnels_query = FunnelsQuery(series=[])
        funnels_response: dict[str, Any] = {
            "results": [
                {
                    "action_id": "test",
                    "name": "test",
                    "order": 0,
                    "count": 100,
                    "average_conversion_time": None,
                    "median_conversion_time": None,
                }
            ]
        }
        result = await self.query_runner._compress_results(funnels_query, funnels_response)
        self.assertIn("Metric|test", result)

        # Test RetentionQuery -> AssistantRetentionQuery casting
        retention_query = RetentionQuery(retentionFilter=RetentionFilter())
        response = {"results": [{"date": "2025-01-01", "label": "Day 0", "values": [{"count": 100}]}]}
        result = await self.query_runner._compress_results(retention_query, response)
        self.assertIn("Date|Number of persons on date", result)

        # Test HogQLQuery -> AssistantHogQLQuery casting
        hogql_query = HogQLQuery(query="SELECT 1")
        hogql_response: dict[str, Any] = {"results": [{"count": 100}], "columns": ["count"]}
        result = await self.query_runner._compress_results(hogql_query, hogql_response)
        self.assertIn("count\n100", result)

    async def test_compress_results_stickiness_query(self):
        query = StickinessQuery(series=[EventsNode(event="$pageview")])
        response: dict[str, Any] = {
            "results": [
                {
                    "count": 500,
                    "data": [200, 150, 100],
                    "days": [1, 2, 3],
                    "labels": ["1 day", "2 days", "3 days"],
                    "label": "$pageview",
                    "action": {
                        "order": 0,
                        "type": "events",
                        "name": "$pageview",
                        "id": "$pageview",
                        "custom_name": None,
                    },
                }
            ]
        }
        result = await self.query_runner._compress_results(query, response)
        self.assertIn("Interval|$pageview", result)
        self.assertIn("1 day|200", result)

    async def test_compress_results_lifecycle_query(self):
        query = LifecycleQuery(series=[EventsNode(event="$pageview")])
        response: dict[str, Any] = {
            "results": [
                {
                    "data": [46.0, 38.0],
                    "days": ["2025-01-20", "2025-01-21"],
                    "labels": ["20-Jan", "21-Jan"],
                    "label": "$pageview - new",
                    "status": "new",
                    "action": {},
                },
                {
                    "data": [120.0, 105.0],
                    "days": ["2025-01-20", "2025-01-21"],
                    "labels": ["20-Jan", "21-Jan"],
                    "label": "$pageview - returning",
                    "status": "returning",
                    "action": {},
                },
                {
                    "data": [15.0, 22.0],
                    "days": ["2025-01-20", "2025-01-21"],
                    "labels": ["20-Jan", "21-Jan"],
                    "label": "$pageview - resurrecting",
                    "status": "resurrecting",
                    "action": {},
                },
                {
                    "data": [-30.0, -45.0],
                    "days": ["2025-01-20", "2025-01-21"],
                    "labels": ["20-Jan", "21-Jan"],
                    "label": "$pageview - dormant",
                    "status": "dormant",
                    "action": {},
                },
            ]
        }
        result = await self.query_runner._compress_results(query, response)
        self.assertIn("Date|New|Returning|Resurrecting|Dormant", result)
        self.assertIn("2025-01-20|46|120|15|-30", result)

    async def test_compress_results_boxplot_data(self):
        query = TrendsQuery(
            series=[EventsNode(event="$pageview")],
            trendsFilter=TrendsFilter(display=ChartDisplayType.BOX_PLOT),
        )
        response: dict[str, Any] = {
            "results": [
                {
                    "day": "2025-01-20",
                    "label": "Day 1",
                    "min": 1.2,
                    "p25": 5.5,
                    "median": 12.3,
                    "p75": 25.8,
                    "max": 100.4,
                    "mean": 18.7,
                    "series_label": "$pageview",
                    "series_index": 0,
                },
            ],
        }
        result = await self.query_runner._compress_results(query, response)
        self.assertIn("Date|Min|P25|Median|P75|Max|Mean", result)
        self.assertIn("2025-01-20|1.2|5.5|12.3|25.8|100.4|18.7", result)
        self.assertNotIn("No data recorded", result)

    async def test_compress_results_boxplot_data_none_falls_back_to_trends(self):
        query = TrendsQuery(series=[EventsNode(event="$pageview")])
        response: dict[str, Any] = {
            "results": [{"data": [1], "label": "test", "days": ["2025-01-01"]}],
        }
        result = await self.query_runner._compress_results(query, response)
        self.assertIn("Date|test", result)

    def test_is_supported_query_includes_new_types(self):
        self.assertTrue(is_supported_query(StickinessQuery(series=[])))
        self.assertTrue(is_supported_query(AssistantStickinessQuery(series=[])))
        self.assertTrue(is_supported_query(LifecycleQuery(series=[EventsNode(event="$pageview")])))

    def test_get_example_prompt_stickiness(self):
        from ee.hogai.context.insight.prompts import STICKINESS_EXAMPLE_PROMPT

        self.assertEqual(get_example_prompt(StickinessQuery(series=[])), STICKINESS_EXAMPLE_PROMPT)
        self.assertEqual(get_example_prompt(AssistantStickinessQuery(series=[])), STICKINESS_EXAMPLE_PROMPT)

    def test_get_example_prompt_lifecycle(self):
        from ee.hogai.context.insight.prompts import LIFECYCLE_EXAMPLE_PROMPT

        self.assertEqual(
            get_example_prompt(LifecycleQuery(series=[EventsNode(event="$pageview")])), LIFECYCLE_EXAMPLE_PROMPT
        )

    def test_get_example_prompt_boxplot(self):
        from ee.hogai.context.insight.prompts import BOX_PLOT_EXAMPLE_PROMPT

        query = TrendsQuery(series=[], trendsFilter=TrendsFilter(display=ChartDisplayType.BOX_PLOT))
        self.assertEqual(get_example_prompt(query), BOX_PLOT_EXAMPLE_PROMPT)

    def test_get_example_prompt_regular_trends_not_boxplot(self):
        from ee.hogai.context.insight.prompts import TRENDS_EXAMPLE_PROMPT

        query = TrendsQuery(series=[])
        self.assertEqual(get_example_prompt(query), TRENDS_EXAMPLE_PROMPT)

    async def test_compress_results_revenue_analytics_gross_revenue_query(self):
        revenue_analytics_gross_revenue_query = RevenueAnalyticsGrossRevenueQuery(
            dateRange=DateRange(date_from="2024-11-01", date_to="2025-02-01"),
            interval=IntervalType.MONTH,
            properties=[],
            breakdown=[RevenueAnalyticsBreakdown(property="revenue_analytics_product.name")],
        )
        response = {
            "results": [
                {
                    "label": "stripe.posthog_test - Product F",
                    "days": ["2024-11-01", "2024-12-01", "2025-01-01", "2025-02-01"],
                    "data": [Decimal("647.24355"), Decimal("2507.21839"), Decimal("2110.27254"), Decimal("2415.34023")],
                },
                {
                    "label": "stripe.posthog_test - Product E",
                    "days": ["2024-11-01", "2024-12-01", "2025-01-01", "2025-02-01"],
                    "data": [Decimal("64.243532"), Decimal("207.2432"), Decimal("210.272"), Decimal("415.3402")],
                },
            ]
        }
        result = await self.query_runner._compress_results(revenue_analytics_gross_revenue_query, response)
        self.assertIn("Breakdown by revenue_analytics_product.name", result)
        self.assertIn("Date|stripe", result)

    async def test_compress_results_revenue_analytics_metrics_query(self):
        revenue_analytics_metrics_query = RevenueAnalyticsMetricsQuery(
            dateRange=DateRange(date_from="2025-01-01", date_to="2025-01-02"),
            interval=IntervalType.MONTH,
            properties=[],
            breakdown=[RevenueAnalyticsBreakdown(property="revenue_analytics_product.name")],
        )
        response: dict[str, Any] = {
            "results": [
                {
                    "days": ["2024-11-01", "2024-12-01", "2025-01-01", "2025-02-01"],
                    "data": [1, 2, 3, 4],
                    "breakdown": {"property": "stripe.posthog_test - Product F", "kind": "Subscription Count"},
                },
                {
                    "days": ["2024-11-01", "2024-12-01", "2025-01-01", "2025-02-01"],
                    "data": [0, 1, 1, 2],
                    "breakdown": {"property": "stripe.posthog_test - Product F", "kind": "New Subscription Count"},
                },
                {
                    "days": ["2024-11-01", "2024-12-01", "2025-01-01", "2025-02-01"],
                    "data": [0, 0, 0, 1],
                    "breakdown": {"property": "stripe.posthog_test - Product F", "kind": "Churned Subscription Count"},
                },
                {
                    "days": ["2024-11-01", "2024-12-01", "2025-01-01", "2025-02-01"],
                    "data": [1, 2, 3, 3],
                    "breakdown": {"property": "stripe.posthog_test - Product F", "kind": "Customer Count"},
                },
                {
                    "days": ["2024-11-01", "2024-12-01", "2025-01-01", "2025-02-01"],
                    "data": [0, 1, 1, 1],
                    "breakdown": {"property": "stripe.posthog_test - Product F", "kind": "New Customer Count"},
                },
                {
                    "days": ["2024-11-01", "2024-12-01", "2025-01-01", "2025-02-01"],
                    "data": [0, 0, 0, 1],
                    "breakdown": {
                        "property": "stripe.posthog_test - Product F",
                        "kind": "Churned Customer Count",
                    },
                },
                {
                    "days": ["2024-11-01", "2024-12-01", "2025-01-01", "2025-02-01"],
                    "data": [0, 0, Decimal("152.235"), Decimal("215.3234")],
                    "breakdown": {"property": "stripe.posthog_test - Product F", "kind": "ARPU"},
                },
                {
                    "days": ["2024-11-01", "2024-12-01", "2025-01-01", "2025-02-01"],
                    "data": [0, 0, None, None],
                    "breakdown": {"property": "stripe.posthog_test - Product F", "kind": "LTV"},
                },
            ]
        }
        result = await self.query_runner._compress_results(revenue_analytics_metrics_query, response)
        self.assertIn("Breakdown by revenue_analytics_product.name", result)
        self.assertIn("Date|stripe", result)
        self.assertIn("Subscription Count", result)
        self.assertIn("New Subscription Count", result)
        self.assertIn("Churned Subscription Count", result)
        self.assertIn("Customer Count", result)
        self.assertIn("New Customer Count", result)
        self.assertIn("Churned Customer Count", result)
        self.assertIn("ARPU", result)
        self.assertIn("LTV", result)

    async def test_compress_results_revenue_analytics_mrr_query(self):
        revenue_analytics_mrr_query = RevenueAnalyticsMRRQuery(
            dateRange=DateRange(date_from="2025-01-01", date_to="2025-01-02"),
            interval=IntervalType.MONTH,
            properties=[],
            breakdown=[RevenueAnalyticsBreakdown(property="revenue_analytics_product.name")],
        )
        response: dict[str, Any] = {
            "results": [
                RevenueAnalyticsMRRQueryResultItem(
                    churn={
                        "breakdown": {"property": "stripe.posthog_test - Product D", "kind": "Churn"},
                        "data": [Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0")],
                        "days": ["2024-11-30", "2024-12-31", "2025-01-31", "2025-02-28"],
                    },
                    contraction={
                        "breakdown": {"property": "stripe.posthog_test - Product D", "kind": "Contraction"},
                        "data": [Decimal("0"), Decimal("-45.391"), Decimal("-1.497"), Decimal("0")],
                        "days": ["2024-11-30", "2024-12-31", "2025-01-31", "2025-02-28"],
                    },
                    expansion={
                        "breakdown": {"property": "stripe.posthog_test - Product D", "kind": "Expansion"},
                        "data": [Decimal("0"), Decimal("0"), Decimal("8.380455"), Decimal("25.12")],
                        "days": ["2024-11-30", "2024-12-31", "2025-01-31", "2025-02-28"],
                    },
                    new={
                        "breakdown": {"property": "stripe.posthog_test - Product D", "kind": "New"},
                        "data": [Decimal("0"), Decimal("5.7325"), Decimal("18.01"), Decimal("0")],
                        "days": ["2024-11-30", "2024-12-31", "2025-01-31", "2025-02-28"],
                    },
                    total={
                        "breakdown": {"property": "stripe.posthog_test - Product D", "kind": None},
                        "data": [Decimal("5.325"), Decimal("4.335"), Decimal("19.865"), Decimal("19.845")],
                        "days": ["2024-11-30", "2024-12-31", "2025-01-31", "2025-02-28"],
                    },
                ),
            ]
        }
        result = await self.query_runner._compress_results(revenue_analytics_mrr_query, response)
        self.assertIn("Breakdown by revenue_analytics_product.name", result)
        self.assertIn("Date|stripe", result)
        self.assertIn("Total MRR", result)
        self.assertIn("New MRR", result)
        self.assertIn("Expansion MRR", result)
        self.assertIn("Contraction MRR", result)
        self.assertIn("Churned MRR", result)

    async def test_compress_results_revenue_analytics_top_customers_query(self):
        revenue_analytics_top_customers_query = RevenueAnalyticsTopCustomersQuery(
            dateRange=DateRange(date_from="2025-01-01", date_to="2025-01-02"),
            groupBy=RevenueAnalyticsTopCustomersGroupBy.MONTH,
            properties=[],
        )
        month_response: dict[str, Any] = {
            "results": [
                ("cus_3", "John Smith", Decimal("615.997315"), date(2025, 2, 1)),
                ("cus_2", "Jane Doe", Decimal("26.0100949999"), date(2025, 2, 1)),
                ("cus_1", "John Doe", Decimal("5.2361453433"), date(2025, 2, 1)),
            ]
        }
        result = await self.query_runner._compress_results(revenue_analytics_top_customers_query, month_response)
        self.assertIn("Grouped by month", result)
        self.assertIn("John Smith", result)
        self.assertIn("Jane Doe", result)
        self.assertIn("John Doe", result)

        revenue_analytics_top_customers_query_all = RevenueAnalyticsTopCustomersQuery(
            dateRange=DateRange(date_from="2025-01-01", date_to="2025-01-02"),
            groupBy=RevenueAnalyticsTopCustomersGroupBy.ALL,
            properties=[],
        )
        all_response: dict[str, Any] = {
            "results": [
                ("cus_3", "John Smith", Decimal("615.997315"), "all"),
                ("cus_2", "Jane Doe", Decimal("26.0100949999"), "all"),
                ("cus_1", "John Doe", Decimal("5.2361453433"), "all"),
            ]
        }
        result = await self.query_runner._compress_results(revenue_analytics_top_customers_query_all, all_response)
        self.assertNotIn("Grouped by month", result)
        self.assertIn("John Smith", result)
        self.assertIn("Jane Doe", result)
        self.assertIn("John Doe", result)

    @patch("ee.hogai.context.insight.query_executor.process_query_dict")
    async def test_response_dict_handling(self, mock_process_query):
        """Test that response is handled correctly whether it's a dict or model"""
        # Test with dict response
        mock_process_query.return_value = {"results": [{"data": [1], "label": "test", "days": ["2025-01-01"]}]}

        query = AssistantTrendsQuery(series=[])
        result, used_fallback = await self.query_runner.arun_and_format_query(query)
        self.assertIn("Date|test", result)

        # Test with model response that has model_dump method
        mock_response = Mock()
        mock_response.model_dump.return_value = {"results": [{"data": [2], "label": "test2", "days": ["2025-01-02"]}]}
        mock_process_query.return_value = mock_response

        result, used_fallback = await self.query_runner.arun_and_format_query(query)
        self.assertIn("Date|test2", result)

    @patch("ee.hogai.context.insight.query_executor.process_query_dict")
    async def test_outer_tags_propagate_across_sync_boundary(self, mock_process_query):
        """Outer-context query tags must survive the database_sync_to_async thread switch."""
        captured_tags: dict[str, Any] = {}

        def fake_process_query_dict(*args, **kwargs):
            # Captured from inside the threaded sync function — i.e. across the async-to-sync boundary
            captured_tags.update(get_query_tags().model_dump(exclude_none=True))
            return {"results": []}

        mock_process_query.side_effect = fake_process_query_dict

        query = AssistantTrendsQuery(series=[])

        # Tags set in the outer async context — these would be lost without the snapshot/replay logic
        with tags_context(feature=Feature.MCP, scene="my-scene"):
            await self.query_runner.arun_and_format_query(query, insight_id=42)

        # Outer-context tags propagated through the sync boundary
        self.assertEqual(captured_tags.get("scene"), "my-scene")
        # Outer feature wins over the default POSTHOG_AI fallback in arun_and_format_query
        self.assertEqual(captured_tags.get("feature"), Feature.MCP.value)
        # Tags applied by arun_and_format_query also propagate
        self.assertEqual(captured_tags.get("product"), Product.MAX_AI.value)
        self.assertEqual(captured_tags.get("team_id"), self.team.pk)
        self.assertEqual(captured_tags.get("insight_id"), 42)

    @patch("ee.hogai.context.insight.query_executor.process_query_dict")
    async def test_default_feature_when_no_outer_feature(self, mock_process_query):
        """When no outer feature is set, arun_and_format_query falls back to POSTHOG_AI."""
        captured_tags: dict[str, Any] = {}

        def fake_process_query_dict(*args, **kwargs):
            captured_tags.update(get_query_tags().model_dump(exclude_none=True))
            return {"results": []}

        mock_process_query.side_effect = fake_process_query_dict

        query = AssistantTrendsQuery(series=[])
        await self.query_runner.arun_and_format_query(query)

        self.assertEqual(captured_tags.get("feature"), Feature.POSTHOG_AI.value)
        self.assertEqual(captured_tags.get("product"), Product.MAX_AI.value)


class TestAssistantQueryExecutorAsync(NonAtomicBaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def setUp(self):
        super().setUp()
        with freeze_time("2025-01-20T12:00:00Z"):
            self.query_runner = AssistantQueryExecutor(self.team, datetime.now())

    async def test_runs_in_async_context(self):
        """Test successful execution and formatting of funnels query"""
        query = AssistantTrendsQuery(series=[AssistantTrendsEventsNode(name="event")])
        result, used_fallback = await self.query_runner.arun_and_format_query(query)
        self.assertIsInstance(result, str)
        self.assertFalse(used_fallback)

    async def test_sql_query_default_limit_is_applied(self):
        query = AssistantHogQLQuery(query="SELECT arrayJoin(range(1, 100001))")
        result, used_fallback = await self.query_runner.arun_and_format_query(query)
        self.assertFalse(used_fallback)
        lines = result.strip().split("\n")
        data_rows = len(lines) - 1  # subtract header
        self.assertEqual(data_rows, DEFAULT_POSTHOG_AI_RETURNED_ROWS)


class TestExecuteAndFormatQuery(NonAtomicBaseTest):
    """Tests for the execute_and_format_query function"""

    CLASS_DATA_LEVEL_SETUP = False

    def setUp(self):
        super().setUp()
        with freeze_time("2025-01-20T12:00:00Z"):
            self.query_runner = AssistantQueryExecutor(self.team, datetime.now())

    @patch("ee.hogai.context.insight.query_executor.process_query_dict")
    async def test_includes_insight_schema_for_trends_query(self, mock_process_query):
        """Verify insight schema is included for TrendsQuery"""
        mock_process_query.return_value = {
            "results": [{"data": [1, 2, 3], "label": "test", "days": ["2025-01-01", "2025-01-02", "2025-01-03"]}]
        }

        query = AssistantTrendsQuery(series=[AssistantTrendsEventsNode(name="$pageview")])
        result = await execute_and_format_query(self.team, query)

        # Verify schema section is present
        self.assertIn("```json", result)
        # Verify it contains query configuration
        self.assertIn("kind", result)

    @patch("ee.hogai.context.insight.query_executor.process_query_dict")
    async def test_insight_schema_excludes_unset_fields(self, mock_process_query):
        """Verify that unset fields are excluded from the schema (exclude_unset=True)"""
        mock_process_query.return_value = {"results": [{"data": [1], "label": "test", "days": ["2025-01-01"]}]}

        query = AssistantTrendsQuery(series=[AssistantTrendsEventsNode(name="$pageview")])
        result = await execute_and_format_query(self.team, query)

        self.assertIn("kind", result)
        self.assertNotIn("breakdownFilter", result)

    @patch("ee.hogai.context.insight.query_executor.process_query_dict")
    async def test_insight_schema_excludes_none_values(self, mock_process_query):
        """Verify that None values are excluded from the schema (exclude_none=True)"""
        mock_process_query.return_value = {"results": [{"data": [1], "label": "test", "days": ["2025-01-01"]}]}

        # Create query with dateRange (which might have None values for date_from/date_to if not set)
        query = AssistantTrendsQuery(series=[AssistantTrendsEventsNode(name="$pageview")], breakdownFilter=None)
        result = await execute_and_format_query(self.team, query)

        # The schema should not contain null values
        self.assertNotIn("null", result)
        self.assertNotIn("breakdownFilter", result)

    @patch("ee.hogai.context.insight.query_executor.process_query_dict")
    async def test_excludes_sql_schema(self, mock_process_query):
        """Verify that None values are excluded from the schema (exclude_none=True)"""
        mock_process_query.return_value = {"results": []}

        # Create query with dateRange (which might have None values for date_from/date_to if not set)
        query = AssistantHogQLQuery(query="SELECT 1")
        result = await execute_and_format_query(self.team, query)

        # The schema should not be present
        self.assertNotIn("SELECT 1", result)

    async def test_compress_results_formats_paths_query(self):
        paths_query = PathsQuery(pathsFilter=PathsFilter(includeEventTypes=["$pageview"]))
        response = {
            "results": [
                {"source": "1_/home", "target": "2_/pricing", "value": 150, "average_conversion_time": 150.0},
                {"source": "1_/home", "target": "2_/docs", "value": 80, "average_conversion_time": 75.5},
            ]
        }

        result = await self.query_runner._compress_results(paths_query, response)
        self.assertIn("Source|Target|Users|Avg. conversion time", result)
        self.assertIn("1_/home|2_/pricing|150|2m 30s", result)


class TestValidateAssistantQuery(NonAtomicBaseTest):
    """Tests for the validate_assistant_query function"""

    CLASS_DATA_LEVEL_SETUP = False

    def test_validates_assistant_trends_query(self):
        """Test that assistant-specific queries are validated via AssistantSupportedQueryRoot."""
        query_dict = {"kind": "TrendsQuery", "series": []}
        result = validate_assistant_query(query_dict)
        self.assertIsInstance(result, AssistantTrendsQuery)

    def test_validates_paths_query_via_fallback(self):
        """Test that PathsQuery is validated via QuerySchemaRoot fallback."""
        query_dict = {
            "kind": "PathsQuery",
            "pathsFilter": {"includeEventTypes": ["$pageview"]},
        }
        result = validate_assistant_query(query_dict)
        self.assertIsInstance(result, PathsQuery)

    def test_validates_funnels_query(self):
        """Test that FunnelsQuery can be validated."""
        query_dict = {"kind": "FunnelsQuery", "series": []}
        result = validate_assistant_query(query_dict)
        self.assertIsInstance(result, AssistantFunnelsQuery)
