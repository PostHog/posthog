from typing import Optional
from django.test import override_settings
from freezegun import freeze_time

from posthog.clickhouse.client.execute import sync_execute
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import print_ast
from posthog.hogql.query import execute_hogql_query
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import create_hogql_database
from posthog.hogql_queries.web_analytics.web_overview_state_transform import (
    transform_query_to_state,
    state_functions_to_merge_functions,
)
from posthog.models.utils import uuid7
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    _create_event,
    _create_person,
    snapshot_clickhouse_queries,
)


@snapshot_clickhouse_queries
class TestWebOverviewStateTransformIntegration(ClickhouseTestMixin, APIBaseTest):
    """Integration tests for the HogQL state transformation utility."""

    maxDiff = None
    
    def setUp(self):
        super().setUp()
        # Create test data with pageviews across multiple sessions and users
        self._create_test_events()

    def _create_test_events(self):
        """Create test events to use for aggregation testing."""
        # Create 3 users with sessions
        num_persons = 3
        persons = []
        
        for i in range(num_persons):
            person_id = f"person{i}"
            
            with freeze_time(f"2023-10-0{i+1} 12:00:00"):
                persons.append(
                    _create_person(
                        team_id=self.team.pk,
                        distinct_ids=[person_id],
                        properties={"name": f"Person {i}"},
                    )
                )
            
            # Each person has different number of sessions and pageviews
            for j in range(i + 1):  # Person 0 has 1 session, Person 1 has 2, etc.
                session_id = str(uuid7())
                
                # Each session has variable number of pageviews
                for k in range(j + 1):  # First session has 1 pageview, second has 2, etc.
                    _create_event(
                        team=self.team,
                        event="$pageview",
                        distinct_id=person_id,
                        timestamp=f"2023-10-0{i+1} 12:{j}{k}:00",
                        properties={
                            "$session_id": session_id,
                            "$current_url": f"https://example.com/path{k}",
                            "$pathname": f"/path{k}",
                        },
                    )
    
    def _execute_clickhouse_query(self, query_str: str) -> list:
        """Helper method to execute a raw ClickHouse query."""
        return sync_execute(query_str)
    
    def _execute_hogql_query(self, hogql_query: str) -> list:
        """Helper method to execute a HogQL query."""
        # Parse the query
        query = parse_select(hogql_query)
        
        # Create a context and database
        context = HogQLContext(team_id=self.team.pk, team=self.team)
        context.database = create_hogql_database(team_id=self.team.pk)
        
        # Print the query as ClickHouse SQL
        clickhouse_query = print_ast(query, dialect="clickhouse", context=context)
        
        # Execute the query
        return self._execute_clickhouse_query(clickhouse_query)
    
    def test_state_functions_basic(self):
        """Test that state functions work correctly in basic queries."""
        # Regular query with count
        regular_query = """
        SELECT count() as event_count
        FROM events
        WHERE team_id = {team_id}
        """
        
        # State version of the query
        state_query = """
        SELECT countState() as event_count_state 
        FROM events
        WHERE team_id = {team_id}
        """
        
        # Merge version of the query
        merge_query = """
        SELECT countMerge(event_count_state) as event_count
        FROM (
            SELECT countState() as event_count_state 
            FROM events
            WHERE team_id = {team_id}
        )
        """
        
        # Execute the queries
        regular_result = self._execute_hogql_query(regular_query.format(team_id=self.team.pk))
        state_result = self._execute_hogql_query(state_query.format(team_id=self.team.pk))
        merge_result = self._execute_hogql_query(merge_query.format(team_id=self.team.pk))
        
        # All queries should return the same count
        self.assertEqual(regular_result[0][0], merge_result[0][0])
        self.assertIsNotNone(state_result[0][0])  # State result is a serialized state object
    
    def test_aggregation_functions_comparison(self):
        """Test different aggregation functions both with regular and state+merge approaches."""
        # Dictionary of function types to test
        functions_to_test = {
            "count": {"column": ""},  # count doesn't need a column
            "uniq": {"column": "distinct_id"},
            "sum": {"column": "1"},  # Sum of 1s gives us the count
        }
        
        for func_name, config in functions_to_test.items():
            column = config["column"]
            column_arg = f"({column})" if column else "()"
            
            # Regular query
            regular_query = f"""
            SELECT {func_name}{column_arg} as result
            FROM events
            WHERE team_id = {{team_id}}
            """
            
            # State and merge approach
            state_query = f"""
            SELECT {func_name}State{column_arg} as result_state
            FROM events
            WHERE team_id = {{team_id}}
            """
            
            merge_query = f"""
            SELECT {func_name}Merge(result_state) as result
            FROM (
                SELECT {func_name}State{column_arg} as result_state
                FROM events
                WHERE team_id = {{team_id}}
            )
            """
            
            # Execute the queries
            regular_result = self._execute_hogql_query(regular_query.format(team_id=self.team.pk))
            merge_result = self._execute_hogql_query(merge_query.format(team_id=self.team.pk))
            
            # Both approaches should give the same result
            self.assertEqual(
                regular_result[0][0], 
                merge_result[0][0], 
                f"Results don't match for {func_name}: regular={regular_result[0][0]}, merge={merge_result[0][0]}"
            )
    
    def test_transformation_utilities(self):
        """Test our transformation utilities with actual query execution."""
        # Create a query
        original_query_str = """
        SELECT 
            uniq(distinct_id) as unique_visitors,
            count() as total_events,
            sum(1) as event_count
        FROM events
        WHERE team_id = {team_id}
        """
        
        # Parse the query
        original_query = parse_select(original_query_str.format(team_id=self.team.pk))
        
        # Transform to state query
        state_query = transform_query_to_state(original_query)
        
        # Create a context
        context = HogQLContext(team_id=self.team.pk, team=self.team)
        context.database = create_hogql_database(team_id=self.team.pk)
        
        # Print the queries
        original_sql = print_ast(original_query, dialect="clickhouse", context=context)
        state_sql = print_ast(state_query, dialect="clickhouse", context=context)
        
        # Execute the original query
        original_result = sync_execute(original_sql)
        
        # Now create a query that will use the state results with merge functions
        merge_query = state_functions_to_merge_functions(
            parse_select("""
            SELECT
                unique_visitors,
                total_events,
                event_count
            FROM (
                {state_query}
            )
            """.format(state_query=state_sql))
        )
        
        # Print and execute the merge query
        merge_sql = print_ast(merge_query, dialect="clickhouse", context=context)
        merge_result = sync_execute(merge_sql)
        
        # Results should match for all metrics
        self.assertEqual(original_result[0][0], merge_result[0][0])  # unique_visitors
        self.assertEqual(original_result[0][1], merge_result[0][1])  # total_events
        self.assertEqual(original_result[0][2], merge_result[0][2])  # event_count
    
    def test_complex_transformation_with_groups(self):
        """Test transformation with GROUP BY and multiple aggregations."""
        # Original query with GROUP BY
        original_query_str = """
        SELECT 
            properties.$pathname as pathname,
            uniq(distinct_id) as unique_visitors,
            count() as total_events
        FROM events
        WHERE team_id = {team_id} AND event = '$pageview'
        GROUP BY pathname
        ORDER BY unique_visitors DESC
        """
        
        # Parse the query
        original_query = parse_select(original_query_str.format(team_id=self.team.pk))
        
        # Transform to state query
        state_query = transform_query_to_state(original_query)
        
        # Create a context
        context = HogQLContext(team_id=self.team.pk, team=self.team)
        context.database = create_hogql_database(team_id=self.team.pk)
        
        # Print the queries
        original_sql = print_ast(original_query, dialect="clickhouse", context=context)
        state_sql = print_ast(state_query, dialect="clickhouse", context=context)
        
        # Execute the original query
        original_result = sync_execute(original_sql)
        
        # Now create a query that will use the state results with merge functions
        merge_query = state_functions_to_merge_functions(
            parse_select("""
            SELECT
                pathname,
                unique_visitors,
                total_events
            FROM (
                {state_query}
            )
            ORDER BY unique_visitors DESC
            """.format(state_query=state_sql))
        )
        
        # Print and execute the merge query
        merge_sql = print_ast(merge_query, dialect="clickhouse", context=context)
        merge_result = sync_execute(merge_sql)
        
        # Results should match when ordered by pathname (the GROUP BY field)
        # We need to sort them ourselves because the order might be different
        original_result_sorted = sorted(original_result, key=lambda row: row[0] or '')
        merge_result_sorted = sorted(merge_result, key=lambda row: row[0] or '')
        
        # Check each path has same metrics
        for i in range(len(original_result_sorted)):
            self.assertEqual(original_result_sorted[i][0], merge_result_sorted[i][0])  # pathname
            self.assertEqual(original_result_sorted[i][1], merge_result_sorted[i][1])  # unique_visitors
            self.assertEqual(original_result_sorted[i][2], merge_result_sorted[i][2])  # total_events
    
    def test_combined_aggregation_with_union_all(self):
        """Test combining state results from multiple sources with UNION ALL."""
        # Create a date filter to split the data
        # First half of events
        first_half_filter = "timestamp < '2023-10-02 00:00:00'"
        # Second half of events
        second_half_filter = "timestamp >= '2023-10-02 00:00:00'"
        
        # Base query to get total unique visitors
        base_query = """
        SELECT uniq(distinct_id) as unique_visitors
        FROM events
        WHERE team_id = {team_id}
        """
        
        # Execute regular query to get the total count
        total_result = self._execute_hogql_query(base_query.format(team_id=self.team.pk))
        total_visitors = total_result[0][0]
        
        # State queries for each half
        first_half_state_query = transform_query_to_state(
            parse_select(f"""
            SELECT uniq(distinct_id) as unique_visitors
            FROM events
            WHERE team_id = {self.team.pk} AND {first_half_filter}
            """)
        )
        
        second_half_state_query = transform_query_to_state(
            parse_select(f"""
            SELECT uniq(distinct_id) as unique_visitors
            FROM events
            WHERE team_id = {self.team.pk} AND {second_half_filter}
            """)
        )
        
        # Create context for printing
        context = HogQLContext(team_id=self.team.pk, team=self.team)
        context.database = create_hogql_database(team_id=self.team.pk)
        
        # Print state queries
        first_half_sql = print_ast(first_half_state_query, dialect="clickhouse", context=context)
        second_half_sql = print_ast(second_half_state_query, dialect="clickhouse", context=context)
        
        # Combined query using UNION ALL and merge function
        combined_query = f"""
        SELECT uniqMerge(unique_visitors) as total_unique_visitors
        FROM 
        (
            SELECT unique_visitors
            FROM 
            (
                {first_half_sql}
            )
            
            UNION ALL
            
            SELECT unique_visitors
            FROM 
            (
                {second_half_sql}
            )
        )
        """
        
        # Execute the combined query
        combined_result = sync_execute(combined_query)
        combined_visitors = combined_result[0][0]
        
        # Total should match the combined result
        self.assertEqual(total_visitors, combined_visitors) 