from typing import Dict, List, Tuple
import math
from unittest.mock import patch
from freezegun import freeze_time

from posthog.clickhouse.client.execute import sync_execute
from posthog.hogql.context import HogQLContext
from posthog.hogql.printer import print_ast
from posthog.hogql_queries.web_analytics.web_overview import WebOverviewQueryRunner

from posthog.schema import (WebOverviewQuery, DateRange)
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    _create_event,
    _create_person,
    snapshot_clickhouse_queries,
)
from posthog.hogql.transforms.state_aggregations import (
    transform_query_to_state_aggregations,
    wrap_state_query_in_merge_query,
)
from datetime import datetime
import uuid

class TestWebOverviewStateTransform(ClickhouseTestMixin, APIBaseTest):
    """Test that web overview queries work correctly with state transformations."""
    
    QUERY_TIMESTAMP = "2025-01-29"
    
    def _create_events(self, data, event="$pageview"):
        person_result = []
        for id, timestamps in data:
            with freeze_time(timestamps[0][0]):
                person_result.append(
                    _create_person(
                        team_id=self.team.pk,
                        distinct_ids=[id],
                        properties={
                            "name": id,
                            **({"email": "test@posthog.com"} if id == "test" else {}),
                        },
                    )
                )
            for timestamp, session_id, *extra in timestamps:
                url = None
                elements = None
                if event == "$pageview":
                    url = extra[0] if extra else None
                properties = {
                    "$session_id": session_id,
                    "$current_url": url,
                }
                if len(extra) > 1 and isinstance(extra[1], dict):
                    properties.update(extra[1])

                _create_event(
                    team=self.team,
                    event=event,
                    distinct_id=id,
                    timestamp=timestamp,
                    properties=properties,
                    elements=elements,
                )
        return person_result

    def _run_web_overview_query(
        self,
        date_from: str,
        date_to: str,
    ):
        """Run the web overview query and return both original and state-transformed results."""
        with freeze_time(self.QUERY_TIMESTAMP):
            query = WebOverviewQuery(
                dateRange=DateRange(date_from=date_from, date_to=date_to),
                properties=[],
                compareFilter=None,
                filterTestAccounts=False,
            )
            runner = WebOverviewQueryRunner(team=self.team, query=query)
            original_query_ast = runner.to_query()
                    
            # Execute original query
            context_original = HogQLContext(team_id=self.team.pk, team=self.team, enable_select_queries=True)
            original_sql = print_ast(original_query_ast, context=context_original, dialect="clickhouse")
            original_result = sync_execute(original_sql, context_original.values)

            # Full transformation (agg -> state -> merge)
            state_query_ast = transform_query_to_state_aggregations(original_query_ast)
            wrapper_query_ast = wrap_state_query_in_merge_query(state_query_ast)

            # Execute transformed query
            context_transformed = HogQLContext(team_id=self.team.pk, team=self.team, enable_select_queries=True)
            transformed_sql = print_ast(wrapper_query_ast, context=context_transformed, dialect="clickhouse")
            transformed_result = sync_execute(transformed_sql, context_transformed.values)
            
            return original_result, transformed_result, original_sql, transformed_sql

    def test_web_overview_query_with_real_data(self):
        """Test that web overview query with state transformation produces the same results as the original."""
        # Generate session IDs with deterministic UUIDs for consistent testing
        s1 = str(uuid.UUID("12345678-1234-5678-1234-567812345671"))
        s2 = str(uuid.UUID("12345678-1234-5678-1234-567812345672"))
        s3 = str(uuid.UUID("12345678-1234-5678-1234-567812345673"))
        
        # Create test data - users with pageviews on different days
        self._create_events(
            [
                # User 1 with 2 pageviews in session 1
                ("user1", [
                    ("2023-12-01", s1, "https://example.com/page1"),
                    ("2023-12-01", s1, "https://example.com/page2", {"$session_duration": 300})
                ]),
                # User 2 with 1 pageview in session 2
                ("user2", [
                    ("2023-12-02", s2, "https://example.com/page1")
                ]),
                # User 3 with 2 pageviews across 2 pages in session 3
                ("user3", [
                    ("2023-12-03", s3, "https://example.com/page1"),
                    ("2023-12-03", s3, "https://example.com/page2", {"$session_duration": 600})
                ]),
            ]
        )
        
        # Run the query for this date range
        original_result, transformed_result, original_sql, transformed_sql = self._run_web_overview_query(
            "2023-12-01", "2023-12-03"
        )
        
        # Helper function to compare results with proper NaN handling
        def compare_results(result1, result2):
            if len(result1) != len(result2):
                return False
            
            for row1, row2 in zip(result1, result2):
                if len(row1) != len(row2):
                    return False
                
                for val1, val2 in zip(row1, row2):
                    # Handle NaN values - consider NaN values equal to each other
                    if isinstance(val1, float) and isinstance(val2, float) and math.isnan(val1) and math.isnan(val2):
                        continue
                    # Compare other values normally
                    elif val1 != val2:
                        return False
            
            return True
        
        # Assert that the results match
        self.assertTrue(compare_results(original_result, transformed_result), 
                        f"Results differ:\nOriginal: {original_result}\nTransformed: {transformed_result}")
        
        # Verify specific metrics
        if len(original_result) > 0:
            # Parse the results assuming the web overview query format:
            # [visitors, pageviews, sessions, session_duration, bounce_rate, ...]
            row = original_result[0]
            
            visitors = row[0]
            pageviews = row[1]
            sessions = row[2]
            
            # With our test data, we should have:
            self.assertEqual(visitors, 3)  # 3 distinct users
            self.assertEqual(pageviews, 5)  # 5 total pageviews
            self.assertEqual(sessions, 3)   # 3 distinct sessions
            
            # Verify same numbers in transformed result
            transformed_row = transformed_result[0]
            self.assertEqual(transformed_row[0], 3)  # 3 distinct users
            self.assertEqual(transformed_row[1], 5)  # 5 total pageviews
            self.assertEqual(transformed_row[2], 3)   # 3 distinct sessions

    def test_web_overview_query_with_constants(self):
        """Test that web overview query with NULL constants handles them correctly."""
        # Generate session ID
        s1 = str(uuid.UUID("12345678-1234-5678-1234-567812345674"))
        
        # Create minimal test data - just one user with one pageview
        self._create_events(
            [
                ("user1", [
                    ("2023-12-01", s1, "https://example.com/page1", {"$session_duration": 300})
                ]),
            ]
        )
        
        # Run the query for this date range
        original_result, transformed_result, original_sql, transformed_sql = self._run_web_overview_query(
            "2023-12-01", "2023-12-03"
        )
        
        # Helper function to compare results with proper NaN handling
        def compare_results(result1, result2):
            if len(result1) != len(result2):
                return False
            
            for row1, row2 in zip(result1, result2):
                if len(row1) != len(row2):
                    return False
                
                for val1, val2 in zip(row1, row2):
                    # Handle NaN values - consider NaN values equal to each other
                    if isinstance(val1, float) and isinstance(val2, float) and math.isnan(val1) and math.isnan(val2):
                        continue
                    # Check if both are None
                    elif val1 is None and val2 is None:
                        continue
                    # Compare other values normally
                    elif val1 != val2:
                        return False
            
            return True
        
        # Assert that the results match
        self.assertTrue(compare_results(original_result, transformed_result), 
                        f"Results differ:\nOriginal: {original_result}\nTransformed: {transformed_result}")
        
        # Verify specific metrics and NULL handling
        if len(original_result) > 0:
            row = original_result[0]
            transformed_row = transformed_result[0]
            
            # Assume some values are NULL in the results and verify they're preserved correctly
            for i in range(len(row)):
                if row[i] is None:
                    self.assertIsNone(transformed_row[i], 
                                     f"NULL value at position {i} not preserved: {row[i]} vs {transformed_row[i]}")
                elif isinstance(row[i], float) and math.isnan(row[i]):
                    self.assertTrue(isinstance(transformed_row[i], float) and math.isnan(transformed_row[i]),
                                   f"NaN value at position {i} not preserved: {row[i]} vs {transformed_row[i]}") 