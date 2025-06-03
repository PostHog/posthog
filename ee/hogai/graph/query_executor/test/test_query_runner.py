from datetime import datetime
from unittest.mock import Mock, patch

from django.test import override_settings
from freezegun import freeze_time
from rest_framework.exceptions import APIException

from ee.hogai.graph.query_executor.query_runner import QueryRunner
from posthog.errors import ExposedCHQueryError
from posthog.hogql.errors import ExposedHogQLError
from posthog.schema import (
    AssistantFunnelsQuery,
    AssistantHogQLQuery,
    AssistantRetentionEventsNode,
    AssistantRetentionFilter,
    AssistantRetentionQuery,
    AssistantTrendsQuery,
    FunnelsQuery,
    HogQLQuery,
    RetentionFilter,
    RetentionQuery,
    TrendsQuery,
)
from posthog.test.base import BaseTest


class TestQueryRunner(BaseTest):
    def setUp(self):
        super().setUp()
        with freeze_time("2025-01-20T12:00:00Z"):
            self.query_runner = QueryRunner(self.team, datetime.now())

    @patch("ee.hogai.graph.query_executor.query_runner.process_query_dict")
    def test_run_and_format_query_trends(self, mock_process_query):
        """Test successful execution and formatting of trends query"""
        mock_process_query.return_value = {
            "results": [{"data": [1, 2, 3], "label": "test", "days": ["2025-01-01", "2025-01-02", "2025-01-03"]}]
        }

        query = AssistantTrendsQuery(series=[])
        result = self.query_runner.run_and_format_query(query)

        self.assertIsInstance(result, str)
        self.assertIn("Date|test", result)
        mock_process_query.assert_called_once()

    @patch("ee.hogai.graph.query_executor.query_runner.process_query_dict")
    def test_run_and_format_query_funnels(self, mock_process_query):
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
        result = self.query_runner.run_and_format_query(query)

        self.assertIsInstance(result, str)
        self.assertIn("Metric|test", result)
        mock_process_query.assert_called_once()

    @patch("ee.hogai.graph.query_executor.query_runner.process_query_dict")
    def test_run_and_format_query_retention(self, mock_process_query):
        """Test successful execution and formatting of retention query"""
        mock_process_query.return_value = {
            "results": [{"date": "2025-01-01", "label": "Day 0", "values": [{"count": 100}]}]
        }

        query = AssistantRetentionQuery(
            retentionFilter=AssistantRetentionFilter(
                targetEntity=AssistantRetentionEventsNode(name="event"),
                returningEntity=AssistantRetentionEventsNode(name="event"),
            )
        )
        result = self.query_runner.run_and_format_query(query)

        self.assertIsInstance(result, str)
        self.assertIn("Date|Number of persons on date", result)
        mock_process_query.assert_called_once()

    @patch("ee.hogai.graph.query_executor.query_runner.process_query_dict")
    def test_run_and_format_query_sql(self, mock_process_query):
        """Test successful execution and formatting of SQL query"""
        mock_process_query.return_value = {"results": [{"count": 100}, {"count": 200}], "columns": ["count"]}

        query = AssistantHogQLQuery(query="SELECT count() FROM events")
        result = self.query_runner.run_and_format_query(query)

        self.assertIsInstance(result, str)
        self.assertIn("count\n100\n200", result)
        mock_process_query.assert_called_once()

    @patch("ee.hogai.graph.query_executor.query_runner.process_query_dict")
    def test_run_and_format_query_with_fallback_info_no_fallback(self, mock_process_query):
        """Test run_and_format_query_with_fallback_info returns fallback info"""
        mock_process_query.return_value = {
            "results": [{"data": [1, 2, 3], "label": "test", "days": ["2025-01-01", "2025-01-02", "2025-01-03"]}]
        }

        query = AssistantTrendsQuery(series=[])
        result, used_fallback = self.query_runner.run_and_format_query_with_fallback_info(query)

        self.assertIsInstance(result, str)
        self.assertFalse(used_fallback)
        self.assertIn("Date|test", result)

    @patch("ee.hogai.graph.query_executor.query_runner.process_query_dict")
    def test_run_and_format_query_with_fallback_on_compression_error(self, mock_process_query):
        """Test fallback to JSON when compression fails"""
        mock_process_query.return_value = {"results": [{"invalid": "data"}]}

        # Use a query that will cause compression to fail
        query = AssistantTrendsQuery(series=[])

        with patch(
            "ee.hogai.graph.query_executor.format.TrendsResultsFormatter.format",
            side_effect=Exception("Compression failed"),
        ):
            result, used_fallback = self.query_runner.run_and_format_query_with_fallback_info(query)

        self.assertIsInstance(result, str)
        self.assertTrue(used_fallback)
        # Should be JSON formatted
        self.assertIn('{"invalid":"data"}', result)

    @patch("ee.hogai.graph.query_executor.query_runner.process_query_dict")
    def test_run_and_format_query_handles_api_exception(self, mock_process_query):
        """Test handling of APIException"""
        mock_process_query.side_effect = APIException("API error message")

        query = AssistantTrendsQuery(series=[])

        with self.assertRaises(Exception) as context:
            self.query_runner.run_and_format_query(query)

        self.assertIn("There was an error running this query: API error message", str(context.exception))

    @patch("ee.hogai.graph.query_executor.query_runner.process_query_dict")
    def test_run_and_format_query_handles_exposed_hogql_error(self, mock_process_query):
        """Test handling of ExposedHogQLError"""
        mock_process_query.side_effect = ExposedHogQLError("HogQL error")

        query = AssistantHogQLQuery(query="SELECT invalid")

        with self.assertRaises(Exception) as context:
            self.query_runner.run_and_format_query(query)

        self.assertIn("There was an error running this query: HogQL error", str(context.exception))

    @patch("ee.hogai.graph.query_executor.query_runner.process_query_dict")
    def test_run_and_format_query_handles_exposed_ch_query_error(self, mock_process_query):
        """Test handling of ExposedCHQueryError"""
        mock_process_query.side_effect = ExposedCHQueryError("ClickHouse error")

        query = AssistantTrendsQuery(series=[])

        with self.assertRaises(Exception) as context:
            self.query_runner.run_and_format_query(query)

        self.assertIn("There was an error running this query: ClickHouse error", str(context.exception))

    @patch("ee.hogai.graph.query_executor.query_runner.process_query_dict")
    def test_run_and_format_query_handles_generic_exception(self, mock_process_query):
        """Test handling of generic exceptions"""
        mock_process_query.side_effect = ValueError("Some other error")

        query = AssistantTrendsQuery(series=[])

        with self.assertRaises(Exception) as context:
            self.query_runner.run_and_format_query(query)

        self.assertIn("There was an unknown error running this query.", str(context.exception))

    @patch("ee.hogai.graph.query_executor.query_runner.process_query_dict")
    @patch("ee.hogai.graph.query_executor.query_runner.get_query_status")
    def test_async_query_polling_success(self, mock_get_query_status, mock_process_query):
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

        with patch("ee.hogai.graph.query_executor.query_runner.sleep") as mock_sleep:
            result = self.query_runner.run_and_format_query(query)

        self.assertIsInstance(result, str)
        self.assertIn("Date|test", result)
        self.assertEqual(mock_get_query_status.call_count, 2)
        self.assertEqual(mock_sleep.call_count, 2)

    @patch("ee.hogai.graph.query_executor.query_runner.process_query_dict")
    @patch("ee.hogai.graph.query_executor.query_runner.get_query_status")
    def test_async_query_polling_timeout(self, mock_get_query_status, mock_process_query):
        """Test async query polling timeout"""
        # Initial response with incomplete query
        mock_process_query.return_value = {"query_status": {"id": "test-query-id", "complete": False}}

        # Mock polling to always return incomplete
        mock_get_query_status.return_value = Mock(model_dump=lambda mode: {"id": "test-query-id", "complete": False})

        query = AssistantTrendsQuery(series=[])

        with patch("ee.hogai.graph.query_executor.query_runner.sleep"):
            with self.assertRaises(Exception) as context:
                self.query_runner.run_and_format_query(query)

        self.assertIn("Query hasn't completed in time", str(context.exception))

    @patch("ee.hogai.graph.query_executor.query_runner.process_query_dict")
    @patch("ee.hogai.graph.query_executor.query_runner.get_query_status")
    def test_async_query_polling_with_error(self, mock_get_query_status, mock_process_query):
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

        with patch("ee.hogai.graph.query_executor.query_runner.sleep"):
            with self.assertRaises(Exception) as context:
                self.query_runner.run_and_format_query(query)

        self.assertIn("Query failed with error", str(context.exception))

    @override_settings(TEST=False)
    @patch("ee.hogai.graph.query_executor.query_runner.process_query_dict")
    def test_execution_mode_in_production(self, mock_process_query):
        """Test that production uses correct execution mode"""
        mock_process_query.return_value = {"results": [{"data": [1], "label": "test", "days": ["2025-01-01"]}]}

        query = AssistantTrendsQuery(series=[])
        self.query_runner.run_and_format_query(query)

        # Check that the execution mode was set correctly (not CALCULATE_BLOCKING_ALWAYS which is test mode)
        call_args = mock_process_query.call_args
        self.assertIn("execution_mode", call_args.kwargs)
        # In production it should be RECENT_CACHE_CALCULATE_ASYNC_IF_STALE
        from posthog.hogql_queries.query_runner import ExecutionMode

        self.assertEqual(call_args.kwargs["execution_mode"], ExecutionMode.RECENT_CACHE_CALCULATE_ASYNC_IF_STALE)

    def test_compress_results_full_ui_queries(self):
        """Test _compress_results works with full UI query types by casting to assistant types"""
        # Test TrendsQuery -> AssistantTrendsQuery casting
        trends_query = TrendsQuery(series=[])
        response = {"results": [{"data": [1], "label": "test", "days": ["2025-01-01"]}]}
        result = self.query_runner._compress_results(trends_query, response)
        self.assertIn("Date|test", result)

        # Test FunnelsQuery -> AssistantFunnelsQuery casting
        funnels_query = FunnelsQuery(series=[])
        response = {
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
        result = self.query_runner._compress_results(funnels_query, response)
        self.assertIn("Metric|test", result)

        # Test RetentionQuery -> AssistantRetentionQuery casting
        retention_query = RetentionQuery(retentionFilter=RetentionFilter())
        response = {"results": [{"date": "2025-01-01", "label": "Day 0", "values": [{"count": 100}]}]}
        result = self.query_runner._compress_results(retention_query, response)
        self.assertIn("Date|Number of persons on date", result)

        # Test HogQLQuery -> AssistantHogQLQuery casting
        hogql_query = HogQLQuery(query="SELECT 1")
        response = {"results": [{"count": 100}], "columns": ["count"]}
        result = self.query_runner._compress_results(hogql_query, response)
        self.assertIn("count\n100", result)

    def test_compress_results_unsupported_query_type(self):
        """Test _compress_results raises NotImplementedError for unsupported query types"""

        class UnsupportedQuery:
            pass

        unsupported_query = UnsupportedQuery()
        response = {"results": []}

        with self.assertRaises(NotImplementedError) as context:
            self.query_runner._compress_results(unsupported_query, response)

        self.assertIn("Unsupported query type", str(context.exception))

    @patch("ee.hogai.graph.query_executor.query_runner.process_query_dict")
    def test_response_dict_handling(self, mock_process_query):
        """Test that response is handled correctly whether it's a dict or model"""
        # Test with dict response
        mock_process_query.return_value = {"results": [{"data": [1], "label": "test", "days": ["2025-01-01"]}]}

        query = AssistantTrendsQuery(series=[])
        result = self.query_runner.run_and_format_query(query)
        self.assertIn("Date|test", result)

        # Test with model response that has model_dump method
        mock_response = Mock()
        mock_response.model_dump.return_value = {"results": [{"data": [2], "label": "test2", "days": ["2025-01-02"]}]}
        mock_process_query.return_value = mock_response

        result = self.query_runner.run_and_format_query(query)
        self.assertIn("Date|test2", result)
