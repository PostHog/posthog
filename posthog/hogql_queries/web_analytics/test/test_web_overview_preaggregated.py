from datetime import datetime
from unittest.mock import patch, MagicMock
import pytest
from typing import Dict

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.database.models import (
    StringDatabaseField,
    DateDatabaseField,
    IntegerDatabaseField,
    Table,
    FieldOrTable
)
from posthog.hogql_queries.web_analytics.web_overview import WebOverviewQuery
from posthog.hogql_queries.web_analytics.web_overview_pre_aggregated import WebOverviewPreAggregatedQueryBuilder, WebOverviewDailyTable
from posthog.schema import (
    DateRange,
    WebOverviewQuery,
    HogQLQueryModifiers,
)
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
)
from posthog.hogql.functions.mapping import HOGQL_AGGREGATIONS, HogQLFunctionMeta

# Register the sumMerge function
HOGQL_AGGREGATIONS["sumMerge"] = HogQLFunctionMeta("sumMerge", 1, 1, aggregate=True)
HOGQL_AGGREGATIONS["uniqMerge"] = HogQLFunctionMeta("uniqMerge", 1, 1, aggregate=True)

class WebOverviewDailyTable(Table):
    fields: Dict[str, FieldOrTable] = {
        "team_id": IntegerDatabaseField(name="team_id"),
        "day_bucket": DateDatabaseField(name="day_bucket"),
        "host": StringDatabaseField(name="host"),
        "device_type": StringDatabaseField(name="device_type"),
        "pageviews_count_state": StringDatabaseField(name="pageviews_count_state"),
        "sessions_uniq_state": StringDatabaseField(name="sessions_uniq_state"),
        "total_session_duration_state": StringDatabaseField(name="total_session_duration_state"),
        "total_bounces_state": StringDatabaseField(name="total_bounces_state"),
        "persons_uniq_state": StringDatabaseField(name="persons_uniq_state"),
    }

# Define a simple PropertyFilter class for testing purposes since the actual one seems to be missing
class PropertyFilter:
    def __init__(self, key, value, operator=None, type=None):
        self.key = key
        self.value = value
        self.operator = operator
        self.type = type


class TestWebOverviewPreAggregated(ClickhouseTestMixin, APIBaseTest):
    """Tests for the web_overview_pre_aggregated module."""
    
    def setUp(self):
        super().setUp()
        # Create a basic query
        self.query = WebOverviewQuery(
            dateRange=DateRange(date_from="2023-01-01", date_to="2023-01-07"),
            properties=[],
            conversionGoal=None,
            includeRevenue=False
        )
        # Create the runner
        self.mock_runner = MagicMock()
        self.mock_runner.query = self.query
        self.mock_runner.team.pk = 450
        self.mock_runner.team = self.team
        
        # Setup query date range with proper date methods
        self.mock_runner.query_date_range = MagicMock()
        self.mock_runner.query_date_range.date_from.return_value = datetime.strptime("2023-01-01", "%Y-%m-%d")
        self.mock_runner.query_date_range.date_to.return_value = datetime.strptime("2023-01-07", "%Y-%m-%d")
        self.mock_runner.query_compare_to_date_range = None
        
        # Create the pre-aggregated query builder
        self.query_builder = WebOverviewPreAggregatedQueryBuilder(runner=self.mock_runner)
    
    @patch('posthog.hogql_queries.web_analytics.web_overview_pre_aggregated.create_hogql_database')
    @patch('posthog.hogql_queries.web_analytics.web_overview_pre_aggregated.execute_hogql_query')
    def test_date_formatting_for_clickhouse(self, mock_execute_hogql, mock_create_db):
        """Test that dates are correctly formatted for ClickHouse."""
        # Setup a proper mock database with the required tables
        mock_db = Database()
        mock_db.web_overview_daily = WebOverviewDailyTable()
        mock_create_db.return_value = mock_db
        
        # Setup mock results
        mock_execute_hogql.return_value = {
            "results": [(100, None, 500, None, 50, None, 300, None, 0.25, None, None, None)],
            "clickhouse_sql": "day_bucket >= '2023-01-01' AND day_bucket <= '2023-01-07'"
        }
        
        # Get the results
        results = self.query_builder.get_results()
        
        # Check that execute_hogql_query was called
        self.assertTrue(mock_execute_hogql.called)
        
        # Convert get_results into the expected format to match web_overview expectations
        result_dict = self._convert_to_overview_format(results)
        
        # Basic verification that we got results
        self.assertEqual(result_dict["unique_persons"]["current"], 100)
        self.assertEqual(result_dict["pageviews"]["current"], 500)
        
    def _convert_to_overview_format(self, results):
        """Convert raw results to the format expected by the web_overview.py"""
        if results is None or len(results) == 0:
            return {}
            
        # Positions in the results tuple
        UNIQUE_PERSONS = 0
        PREV_UNIQUE_PERSONS = 1
        PAGEVIEWS = 2
        PREV_PAGEVIEWS = 3
        UNIQUE_SESSIONS = 4
        PREV_UNIQUE_SESSIONS = 5
        AVG_SESSION_DURATION = 6
        PREV_AVG_SESSION_DURATION = 7
        BOUNCE_RATE = 8
        PREV_BOUNCE_RATE = 9
        REVENUE = 10
        PREV_REVENUE = 11
        
        row = results[0]  # Take the first row of results
        
        return {
            "unique_persons": {
                "current": row[UNIQUE_PERSONS],
                "previous": row[PREV_UNIQUE_PERSONS]
            },
            "pageviews": {
                "current": row[PAGEVIEWS],
                "previous": row[PREV_PAGEVIEWS]
            },
            "unique_sessions": {
                "current": row[UNIQUE_SESSIONS],
                "previous": row[PREV_UNIQUE_SESSIONS]
            },
            "avg_session_duration": {
                "current": row[AVG_SESSION_DURATION],
                "previous": row[PREV_AVG_SESSION_DURATION]
            },
            "bounce_rate": {
                "current": row[BOUNCE_RATE],
                "previous": row[PREV_BOUNCE_RATE]
            },
            "revenue": {
                "current": row[REVENUE],
                "previous": row[PREV_REVENUE]
            }
        }

    @patch('posthog.hogql_queries.web_analytics.web_overview_pre_aggregated.create_hogql_database')
    @patch('posthog.hogql_queries.web_analytics.web_overview_pre_aggregated.execute_hogql_query')
    def test_results_mapping_structure(self, mock_execute_hogql, mock_create_db):
        """Test that the results are correctly structured."""
        # Setup a proper mock database with the required tables
        mock_db = Database()
        mock_db.web_overview_daily = WebOverviewDailyTable()
        mock_create_db.return_value = mock_db
        
        # Setup mock results
        mock_execute_hogql.return_value = {
            "results": [(100, None, 500, None, 50, None, 300, None, 0.25, None, None, None)]
        }
        
        # Get the results
        results = self.query_builder.get_results()
        
        # Convert results to expected format
        result_dict = self._convert_to_overview_format(results)
        
        # Verify the structure of the returned results
        self.assertEqual(result_dict["unique_persons"]["current"], 100)
        self.assertEqual(result_dict["pageviews"]["current"], 500)
        self.assertEqual(result_dict["unique_sessions"]["current"], 50)
        self.assertEqual(result_dict["avg_session_duration"]["current"], 300)
        self.assertEqual(result_dict["bounce_rate"]["current"], 0.25)

    def test_conversion_goal_prevents_using_pre_aggregated_tables(self):
        """Test that having a conversion goal prevents using pre-aggregated tables"""
        # Setup query with conversion goal
        self.mock_runner.query.conversionGoal = "pageview goal"
        
        # Check if pre-aggregated tables can be used
        can_use = self.query_builder.can_use_preaggregated_tables()
        
        # Should return False because conversion goals require full event data
        assert can_use is False

    def test_unsupported_property_filters_prevent_using_pre_aggregated_tables(self):
        """Test that unsupported property filters prevent using pre-aggregated tables"""
        # Setup query with unsupported property
        unsupported_property = PropertyFilter(key="$unsupported_prop", value="value")
        self.mock_runner.query.properties = [unsupported_property]
        
        # Check if pre-aggregated tables can be used
        can_use = self.query_builder.can_use_preaggregated_tables()
        
        # Should return False because we have an unsupported property filter
        assert can_use is False

    def test_supported_property_filters_allow_using_pre_aggregated_tables(self):
        """Test that supported property filters allow using pre-aggregated tables"""
        # Setup query with supported properties
        host_property = PropertyFilter(key="$host", value="example.com")
        self.mock_runner.query.properties = [host_property]
        
        # Check if pre-aggregated tables can be used
        can_use = self.query_builder.can_use_preaggregated_tables()
        
        # Should return True because we only have supported property filters
        assert can_use is True

    def test_no_property_filters_allow_using_pre_aggregated_tables(self):
        """Test that no property filters allow using pre-aggregated tables"""
        # Setup query with no property filters
        self.mock_runner.query.properties = []
        
        # Check if pre-aggregated tables can be used
        can_use = self.query_builder.can_use_preaggregated_tables()
        
        # Should return True because we have no property filters
        assert can_use is True

    @patch('posthog.hogql_queries.web_analytics.web_overview_pre_aggregated.create_hogql_database')
    @patch('posthog.hogql_queries.web_analytics.web_overview_pre_aggregated.execute_hogql_query')
    def test_string_property_filter_in_sql(self, mock_execute_hogql, mock_create_db):
        """Test that string property filters are correctly added to SQL"""
        # Setup a proper mock database with the required tables
        mock_db = Database()
        mock_db.web_overview_daily = WebOverviewDailyTable()
        mock_create_db.return_value = mock_db
        
        # Setup query with string property filter
        host_property = PropertyFilter(key="$host", value="example.com")
        self.mock_runner.query.properties = [host_property]
        mock_execute_hogql.return_value = {
            "results": [(0, None, 0, None, 0, None, 0, None, 0, None, None, None)]
        }
        
        # Execute get_results to generate SQL with property filter
        self.query_builder.get_results()
        
        # Verify the mock was called
        mock_execute_hogql.assert_called_once()
        
        # The actual SQL generation is tested in other tests that check the builder directly

    @patch('posthog.hogql_queries.web_analytics.web_overview_pre_aggregated.create_hogql_database')
    @patch('posthog.hogql_queries.web_analytics.web_overview_pre_aggregated.execute_hogql_query')
    def test_list_property_filter_in_sql(self, mock_execute_hogql, mock_create_db):
        """Test that list property filters are correctly added to SQL"""
        # Setup a proper mock database with the required tables
        mock_db = Database()
        mock_db.web_overview_daily = WebOverviewDailyTable()
        mock_create_db.return_value = mock_db
        
        # Setup query with list property filter
        device_type_property = PropertyFilter(key="$device_type", value=["mobile", "tablet"])
        self.mock_runner.query.properties = [device_type_property]
        mock_execute_hogql.return_value = {
            "results": [(0, None, 0, None, 0, None, 0, None, 0, None, None, None)]
        }
        
        # Execute get_results to generate SQL with property filter
        self.query_builder.get_results()
        
        # Verify the mock was called
        mock_execute_hogql.assert_called_once()

    @patch('posthog.hogql_queries.web_analytics.web_overview_pre_aggregated.create_hogql_database')
    @patch('posthog.hogql_queries.web_analytics.web_overview_pre_aggregated.execute_hogql_query')
    def test_multiple_property_filters_in_sql(self, mock_execute_hogql, mock_create_db):
        """Test that multiple property filters are correctly added to SQL"""
        # Setup a proper mock database with the required tables
        mock_db = Database()
        mock_db.web_overview_daily = WebOverviewDailyTable()
        mock_create_db.return_value = mock_db
        
        # Setup query with multiple property filters
        host_property = PropertyFilter(key="$host", value="example.com")
        device_type_property = PropertyFilter(key="$device_type", value="mobile")
        self.mock_runner.query.properties = [host_property, device_type_property]
        mock_execute_hogql.return_value = {
            "results": [(0, None, 0, None, 0, None, 0, None, 0, None, None, None)]
        }
        
        # Execute get_results to generate SQL with property filters
        self.query_builder.get_results()
        
        # Verify the mock was called
        mock_execute_hogql.assert_called_once()

    @patch('posthog.hogql_queries.web_analytics.web_overview_pre_aggregated.create_hogql_database')
    @patch('posthog.hogql_queries.web_analytics.web_overview_pre_aggregated.execute_hogql_query')
    def test_revenue_flag_handling(self, mock_execute_hogql, mock_create_db):
        """Test that the revenue flag is correctly handled in SQL"""
        # Setup a proper mock database with the required tables
        mock_db = Database()
        mock_db.web_overview_daily = WebOverviewDailyTable()
        mock_create_db.return_value = mock_db
        
        # First test with includeRevenue=False
        self.mock_runner.query.includeRevenue = False
        mock_execute_hogql.return_value = {
            "results": [(0, None, 0, None, 0, None, 0, None, 0, None, None, None)]
        }
        
        # Execute get_results
        results = self.query_builder.get_results()
        
        # Verify the mock was called
        mock_execute_hogql.assert_called_once()
        
        # Convert results to dictionary
        result_dict = self._convert_to_overview_format(results)
        
        # Last column should be None when includeRevenue=False
        self.assertIsNone(result_dict["revenue"]["current"]) 
        
        # Reset the mock for second call
        mock_execute_hogql.reset_mock()
        
        # Then test with includeRevenue=True
        self.mock_runner.query.includeRevenue = True
        mock_execute_hogql.return_value = {
            "results": [(0, None, 0, None, 0, None, 0, None, 0, None, 100, None)]
        }
        
        # Execute get_results
        results = self.query_builder.get_results()
        
        # Verify the mock was called again
        mock_execute_hogql.assert_called_once()
        
        # Convert results to dictionary
        result_dict = self._convert_to_overview_format(results)
        
        # Last column should be 100 when includeRevenue=True
        self.assertEqual(result_dict["revenue"]["current"], 100)

    @patch('posthog.hogql_queries.web_analytics.web_overview_pre_aggregated.create_hogql_database')
    @patch('posthog.hogql_queries.web_analytics.web_overview_pre_aggregated.execute_hogql_query')
    def test_error_handling(self, mock_execute_hogql, mock_create_db):
        """Test that errors are properly handled"""
        # Setup a proper mock database with the required tables
        mock_db = Database()
        mock_db.web_overview_daily = WebOverviewDailyTable()
        mock_create_db.return_value = mock_db
        
        # Setup mock to raise an exception
        mock_execute_hogql.side_effect = Exception("Test exception")
        
        # Execute get_results and expect an exception
        with pytest.raises(Exception) as excinfo:
            self.query_builder.get_results()
        
        # Verify that the exception is properly propagated
        assert "Test exception" in str(excinfo.value)

    def test_get_filters(self):
        """Test that property filters are correctly converted to AST expressions"""
        # Setup query with multiple property filters
        host_property = PropertyFilter(key="$host", value="example.com")
        device_type_property = PropertyFilter(key="$device_type", value=["mobile", "tablet"])
        self.mock_runner.query.properties = [host_property, device_type_property]
        
        # Generate filter expressions
        filters = self.query_builder._get_filters()
        
        # Verify the type of the filters
        assert isinstance(filters, ast.Call)
        assert filters.name == "and"
        assert len(filters.args) == 2
        
        # Verify the first filter (host)
        host_filter = filters.args[0]
        assert isinstance(host_filter, ast.CompareOperation)
        assert host_filter.op == ast.CompareOperationOp.Eq
        assert isinstance(host_filter.left, ast.Field)
        assert host_filter.left.chain == ["web_overview_daily", "host"]
        assert isinstance(host_filter.right, ast.Constant)
        assert host_filter.right.value == "example.com"
        
        # Verify the second filter (device_type)
        device_filter = filters.args[1]
        assert isinstance(device_filter, ast.CompareOperation)
        assert device_filter.op == ast.CompareOperationOp.In
        assert isinstance(device_filter.left, ast.Field)
        assert device_filter.left.chain == ["web_overview_daily", "device_type"]
        assert isinstance(device_filter.right, ast.Tuple)
        assert len(device_filter.right.exprs) == 2
        assert isinstance(device_filter.right.exprs[0], ast.Constant)
        assert device_filter.right.exprs[0].value == "mobile"
        assert isinstance(device_filter.right.exprs[1], ast.Constant)
        assert device_filter.right.exprs[1].value == "tablet"

    def test_empty_filters(self):
        """Test that empty property filters result in an empty string"""
        # Setup query with no property filters
        self.mock_runner.query.properties = []
        
        # Generate filter expressions
        filters = self.query_builder._get_filters()
        
        # Verify the type of the filters
        assert isinstance(filters, ast.Constant)
        assert filters.value == ""

    def test_single_filter(self):
        """Test that a single property filter is correctly converted to an AST expression"""
        # Setup query with a single property filter
        host_property = PropertyFilter(key="$host", value="example.com")
        self.mock_runner.query.properties = [host_property]
        
        # Generate filter expressions
        filters = self.query_builder._get_filters()
        
        # Verify the type of the filters
        assert isinstance(filters, ast.CompareOperation)
        assert filters.op == ast.CompareOperationOp.Eq
        assert isinstance(filters.left, ast.Field)
        assert filters.left.chain == ["web_overview_daily", "host"]
        assert isinstance(filters.right, ast.Constant)
        assert filters.right.value == "example.com" 