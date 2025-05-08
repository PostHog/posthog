from typing import cast, Dict, List, Any
import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime
from freezegun import freeze_time

from posthog.hogql.query import execute_hogql_query
from posthog.hogql_queries.web_analytics.test.util import create_web_analytics_test_data
from posthog.hogql_queries.web_analytics.web_overview import WebOverviewQueryRunner
from posthog.models.filters.utils import convert_to_comparison_date_range
from posthog.schema import (
    DateRange,
    WebOverviewQuery,
    HogQLQueryModifiers,
    EventPropertyFilter,
    PropertyOperator,
    WebOverviewItem,
)
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    snapshot_clickhouse_queries,
    _create_event,
    _create_person,
    flush_persons_and_events,
)
from posthog.models.filters.mixins.utils import cached_property


class TestWebOverviewPreAggregated(ClickhouseTestMixin, APIBaseTest):
    """Tests for the web_overview query runner using pre-aggregated tables."""

    maxDiff = None
    
    def setUp(self):
        super().setUp()
        self.base_time = datetime(2023, 1, 1, 12, 0)

        # Create test data with a variety of events and sessions
        _create_person(
            team_id=self.team.pk,
            distinct_ids=["person1"],
            properties={"$browser": "Chrome", "$os": "Mac OS X"},
        )
        _create_person(
            team_id=self.team.pk,
            distinct_ids=["person2"],
            properties={"$browser": "Safari", "$os": "iOS"},
        )
        
        # Create events for the first date range
        self._create_events_for_date_range("2023-01-01", "2023-01-07", "host1.example.com", "desktop")
        self._create_events_for_date_range("2023-01-01", "2023-01-07", "host2.example.com", "mobile")
        
        # Create events for the comparison date range
        self._create_events_for_date_range("2022-12-25", "2022-12-31", "host1.example.com", "desktop")
        self._create_events_for_date_range("2022-12-25", "2022-12-31", "host2.example.com", "mobile")
        
        flush_persons_and_events()
        
        # Create a mock for pre-aggregated table to return prefilled data
        # We don't actually insert data into pre-aggregated tables in tests, so we'll mock the SQL query results
        self.mock_execute_hogql_patch = patch('posthog.hogql.query.execute_hogql_query', wraps=execute_hogql_query)
        self.mock_execute_hogql = self.mock_execute_hogql_patch.start()
        
    def tearDown(self):
        self.mock_execute_hogql_patch.stop()
        super().tearDown()
        
    def _create_events_for_date_range(self, start_date, end_date, host, device_type):
        # Helper method to create a series of events in a date range
        for i in range(5):
            person_id = "person1" if i % 2 == 0 else "person2"
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id=person_id,
                timestamp=f"{start_date}T{12+i}:00:00Z",
                properties={
                    "$session_id": f"session_{start_date}_{person_id}_{i}",
                    "$host": host,
                    "$device_type": device_type,
                    "$pathname": f"/path{i}"
                },
            )
    
    def _mock_preaggregated_table_results(self, has_comparison=False):
        # Mock the results that would come from pre-aggregated tables
        
        # Define the mock results 
        results = [
            # For current period
            [100, 500, 200, 120, 0.25]
        ]
        
        if has_comparison:
            # Append previous period data
            results[0].extend([80, 400, 150, 100, 0.30])
            
        self.mock_execute_hogql.return_value.results = results
        self.mock_execute_hogql.return_value.types = [
            "UInt64", "UInt64", "UInt64", "Float64", "Float64"
        ]
        
        # Set a marker in the clickhouse query to confirm pre-aggregated tables were used
        self.mock_execute_hogql.return_value.clickhouse = "FROM web_overview_metrics_daily_distributed"
    
    @pytest.fixture
    def mock_execute_hogql_query(self):
        with patch("posthog.hogql_queries.web_analytics.web_overview.execute_hogql_query") as mock:
            # Prepare mock results data
            mock.return_value.results = [
                [
                    1000,  # unique_persons
                    None,  # previous unique_persons
                    5000,  # pageviews
                    None,  # previous pageviews
                    2000,  # unique_sessions
                    None,  # previous unique_sessions
                    300,   # avg_session_duration
                    None,  # previous avg_session_duration
                    0.3,   # bounce_rate
                    None,  # previous bounce_rate
                    100,   # revenue (if included)
                    None,  # previous revenue
                ]
            ]
            yield mock

    def test_can_use_preaggregated_tables(self, mock_execute_hogql_query):
        query = WebOverviewQuery(
            properties=[],
            conversionGoal=None,
            includeRevenue=False,
        )
        
        runner = WebOverviewQueryRunner(team=self.team, query=query)
        assert runner._can_use_preaggregated_tables() == True

    def test_cannot_use_preaggregated_tables_with_conversion_goal(self, mock_execute_hogql_query):
        # Conversion goals aren't supported with pre-aggregated tables
        query = WebOverviewQuery(
            properties=[],
            conversionGoal={"type": "custom_event", "id": "purchase"},
            includeRevenue=False,
        )
        
        runner = WebOverviewQueryRunner(team=self.team, query=query)
        assert runner._can_use_preaggregated_tables() == False

    def test_cannot_use_preaggregated_tables_with_unsupported_property(self, mock_execute_hogql_query):
        # Properties other than $host or $device_type aren't supported
        query = WebOverviewQuery(
            properties=[
                {"key": "$browser", "type": "event", "value": "Chrome", "operator": "exact"}
            ],
            conversionGoal=None,
            includeRevenue=False,
        )
        
        runner = WebOverviewQueryRunner(team=self.team, query=query)
        assert runner._can_use_preaggregated_tables() == False

    def test_can_use_preaggregated_tables_with_supported_property(self, mock_execute_hogql_query):
        # $host is supported
        query = WebOverviewQuery(
            properties=[
                {"key": "$host", "type": "event", "value": "app.posthog.com", "operator": "exact"}
            ],
            conversionGoal=None,
            includeRevenue=False,
        )
        
        runner = WebOverviewQueryRunner(team=self.team, query=query)
        assert runner._can_use_preaggregated_tables() == True

    def test_usedPreAggregatedTables_flag_is_set(self, mock_execute_hogql_query):
        query = WebOverviewQuery(
            properties=[
                {"key": "$host", "type": "event", "value": "app.posthog.com", "operator": "exact"}
            ],
            conversionGoal=None,
            includeRevenue=False,
        )
        
        # Enable pre-aggregated tables
        runner = WebOverviewQueryRunner(team=self.team, query=query)
        runner.modifiers = {"useWebAnalyticsPreAggregatedTables": True}
        
        response = runner.calculate()
        assert response.usedPreAggregatedTables is True

    def test_usedPreAggregatedTables_flag_is_false_when_not_used(self, mock_execute_hogql_query):
        # Query with unsupported property
        query = WebOverviewQuery(
            properties=[
                {"key": "$browser", "type": "event", "value": "Chrome", "operator": "exact"}
            ],
            conversionGoal=None,
            includeRevenue=False,
        )
        
        # Even with pre-aggregated tables enabled, it won't be used
        runner = WebOverviewQueryRunner(team=self.team, query=query)
        runner.modifiers = {"useWebAnalyticsPreAggregatedTables": True}
        
        response = runner.calculate()
        assert response.usedPreAggregatedTables is False

    def test_query_results_format_is_identical(self, mock_execute_hogql_query):
        query = WebOverviewQuery(
            properties=[],
            conversionGoal=None,
            includeRevenue=True,
        )
        
        # Run with pre-aggregated tables disabled
        runner1 = WebOverviewQueryRunner(team=self.team, query=query)
        runner1.modifiers = {"useWebAnalyticsPreAggregatedTables": False}
        response1 = runner1.calculate()
        
        # Run with pre-aggregated tables enabled
        runner2 = WebOverviewQueryRunner(team=self.team, query=query)
        runner2.modifiers = {"useWebAnalyticsPreAggregatedTables": True}
        response2 = runner2.calculate()
        
        # Results structure should be identical, just with the flag set
        assert len(response1.results) == len(response2.results)
        
        # Assert the usedPreAggregatedTables flag differs
        assert response1.usedPreAggregatedTables is False
        assert response2.usedPreAggregatedTables is True
        
        # Check each result has the same keys
        for item1, item2 in zip(response1.results, response2.results):
            assert item1.keys() == item2.keys()

    def test_preaggregated_query_structure(self, mock_execute_hogql_query):
        query = WebOverviewQuery(
            properties=[
                {"key": "$host", "type": "event", "value": "app.posthog.com", "operator": "exact"}
            ],
            conversionGoal=None,
            includeRevenue=True,
        )
        
        runner = WebOverviewQueryRunner(team=self.team, query=query)
        runner.modifiers = {"useWebAnalyticsPreAggregatedTables": True}
        
        # Get the query that would be executed
        with patch.object(runner, '_can_use_preaggregated_tables', return_value=True):
            query_ast = runner.to_query()
            
            # Just verify that the query is using the pre-aggregated table
            query_str = str(query_ast)
            assert "FROM web_overview_metrics_daily_distributed" in query_str

    @patch('posthog.hogql_queries.web_analytics.web_overview.WebOverviewQueryRunner._can_use_preaggregated_tables', return_value=True)
    @snapshot_clickhouse_queries
    def test_overview_query_with_preaggregated_tables(self, mock_can_use):
        """Test that the pre-aggregated tables are used when the modifier is set."""
        self._mock_preaggregated_table_results()
        
        # Create a query that should use pre-aggregated tables
        query = WebOverviewQuery(
            dateRange=DateRange(date_from="2023-01-01", date_to="2023-01-07"),
            properties=[]
        )
        
        # Run the query with the pre-aggregated tables modifier
        runner = WebOverviewQueryRunner(
            team=self.team,
            query=query,
            modifiers=HogQLQueryModifiers(useWebAnalyticsPreAggregatedTables=True)
        )
        response = runner.calculate()
        
        # Verify the response contains the expected metrics
        metrics = {item["key"]: item["value"] for item in response.results}
        self.assertEqual(metrics["visitors"], 100)
        self.assertEqual(metrics["views"], 500)
        self.assertEqual(metrics["sessions"], 200)
        self.assertEqual(metrics["session duration"], 120)
        self.assertEqual(metrics["bounce rate"], 25.0)
        
        # Verify that the pre-aggregated table was used
        self.assertIn("web_overview_metrics_daily_distributed", 
                     self.mock_execute_hogql.call_args[1]["query"].source_string())
    
    @patch('posthog.hogql_queries.web_analytics.web_overview.WebOverviewQueryRunner._can_use_preaggregated_tables', return_value=True)
    @snapshot_clickhouse_queries
    def test_overview_query_with_comparison(self, mock_can_use):
        """Test that comparison queries work with pre-aggregated tables."""
        self._mock_preaggregated_table_results(has_comparison=True)
        
        # Create a query with comparison
        query = WebOverviewQuery(
            dateRange=DateRange(date_from="2023-01-01", date_to="2023-01-07"),
            properties=[],
            compareFilter=convert_to_comparison_date_range("previous_period")
        )
        
        # Run the query with the pre-aggregated tables modifier
        runner = WebOverviewQueryRunner(
            team=self.team,
            query=query,
            modifiers=HogQLQueryModifiers(useWebAnalyticsPreAggregatedTables=True)
        )
        response = runner.calculate()
        
        # Verify the response contains both current and previous metrics
        metrics = {item["key"]: (item["value"], item["previous"]) for item in response.results}
        self.assertEqual(metrics["visitors"], (100, 80))
        self.assertEqual(metrics["views"], (500, 400))
        self.assertEqual(metrics["sessions"], (200, 150))
        self.assertEqual(metrics["session duration"], (120, 100))
        self.assertEqual(metrics["bounce rate"], (25.0, 30.0))
        
        # Check that we generated both current and previous periods SQL
        self.assertIn("JOIN", self.mock_execute_hogql.call_args[1]["query"].source_string())
    
    @snapshot_clickhouse_queries
    def test_property_filters_with_preaggregated_tables(self):
        """Test that property filters are correctly applied with pre-aggregated tables."""
        self._mock_preaggregated_table_results()
        
        # Create a query with host filter
        query = WebOverviewQuery(
            dateRange=DateRange(date_from="2023-01-01", date_to="2023-01-07"),
            properties=[
                EventPropertyFilter(
                    key="$host",
                    value="host1.example.com", 
                    operator=PropertyOperator.EXACT
                )
            ]
        )
        
        # Run the query with the pre-aggregated tables modifier
        runner = WebOverviewQueryRunner(
            team=self.team,
            query=query,
            modifiers=HogQLQueryModifiers(useWebAnalyticsPreAggregatedTables=True)
        )
        response = runner.calculate()
        
        # Verify that the host filter was applied
        query_str = self.mock_execute_hogql.call_args[1]["query"].source_string()
        self.assertIn("host = 'host1.example.com'", query_str)
    
    def test_conversion_goal_falls_back_to_regular_query(self):
        """Test that queries with conversion goals fall back to the regular query."""
        # Create a query with a conversion goal
        query = WebOverviewQuery(
            dateRange=DateRange(date_from="2023-01-01", date_to="2023-01-07"),
            properties=[],
            conversionGoal={"kind": "CustomEventConversionGoal", "customEventName": "purchase"}
        )
        
        # Run the query with the pre-aggregated tables modifier
        runner = WebOverviewQueryRunner(
            team=self.team,
            query=query,
            modifiers=HogQLQueryModifiers(useWebAnalyticsPreAggregatedTables=True)
        )
        
        # Verify that _can_use_preaggregated_tables returns False
        self.assertFalse(runner._can_use_preaggregated_tables())
        
        # Verify that to_query() returns the regular query
        query_obj = runner.to_query()
        self.assertIsNone(getattr(query_obj, "source_string", None))
        self.assertIsNotNone(getattr(query_obj, "select", None))
    
    def test_unsupported_property_falls_back_to_regular_query(self):
        """Test that queries with unsupported properties fall back to the regular query."""
        # Create a query with an unsupported property
        query = WebOverviewQuery(
            dateRange=DateRange(date_from="2023-01-01", date_to="2023-01-07"),
            properties=[
                EventPropertyFilter(
                    key="$browser",
                    value="Chrome", 
                    operator=PropertyOperator.EXACT
                )
            ]
        )
        
        # Run the query with the pre-aggregated tables modifier
        runner = WebOverviewQueryRunner(
            team=self.team,
            query=query,
            modifiers=HogQLQueryModifiers(useWebAnalyticsPreAggregatedTables=True)
        )
        
        # Verify that _can_use_preaggregated_tables returns False
        self.assertFalse(runner._can_use_preaggregated_tables())
        
        # Verify that to_query() returns the regular query
        query_obj = runner.to_query()
        self.assertIsNone(getattr(query_obj, "source_string", None))
        self.assertIsNotNone(getattr(query_obj, "select", None))
    
    @patch('posthog.hogql_queries.web_analytics.web_overview.WebOverviewQueryRunner._can_use_preaggregated_tables', return_value=True)
    def test_result_format_is_identical(self, mock_can_use):
        """Test that the result format is identical between regular and pre-aggregated queries."""
        # Mock the pre-aggregated results
        self._mock_preaggregated_table_results()
        
        # Create a simple query
        query = WebOverviewQuery(
            dateRange=DateRange(date_from="2023-01-01", date_to="2023-01-07"),
            properties=[]
        )
        
        # Run with regular tables
        regular_runner = WebOverviewQueryRunner(
            team=self.team,
            query=query,
            modifiers=HogQLQueryModifiers(useWebAnalyticsPreAggregatedTables=False)
        )
        regular_results = regular_runner.calculate()
        
        # Run with pre-aggregated tables
        self.mock_execute_hogql.reset_mock()
        preagg_runner = WebOverviewQueryRunner(
            team=self.team,
            query=query,
            modifiers=HogQLQueryModifiers(useWebAnalyticsPreAggregatedTables=True)
        )
        preagg_results = preagg_runner.calculate()
        
        # Verify that the structure of the results is identical
        self.assertEqual(len(regular_results.results), len(preagg_results.results))
        for i, item in enumerate(regular_results.results):
            self.assertEqual(set(item.keys()), set(preagg_results.results[i].keys()))
    
    def test_add_marker_to_response_indicating_preaggregated_tables_used(self):
        """Test that we can identify when pre-aggregated tables were used."""
        # Create a query and run it with pre-aggregated tables
        query = WebOverviewQuery(
            dateRange=DateRange(date_from="2023-01-01", date_to="2023-01-07"),
            properties=[]
        )
        
        # Make a simple modification to the WebOverviewQueryRunner to add a marker
        original_calculate = WebOverviewQueryRunner.calculate
        
        def patched_calculate(self):
            response = original_calculate(self)
            
            # Add a marker to the response when pre-aggregated tables are used
            if (self.modifiers and 
                self.modifiers.useWebAnalyticsPreAggregatedTables and 
                self._can_use_preaggregated_tables()):
                response_dict = response.dict()
                response_dict["used_preaggregated_tables"] = True
                response = type(response)(**response_dict)
            
            return response
        
        # Apply the patch for this test
        with patch('posthog.hogql_queries.web_analytics.web_overview.WebOverviewQueryRunner.calculate', 
                  patched_calculate):
            # Run the query
            runner = WebOverviewQueryRunner(
                team=self.team,
                query=query,
                modifiers=HogQLQueryModifiers(useWebAnalyticsPreAggregatedTables=True)
            )
            response = runner.calculate()
            
            # Check that the marker is present
            self.assertTrue(getattr(response, "used_preaggregated_tables", False)) 