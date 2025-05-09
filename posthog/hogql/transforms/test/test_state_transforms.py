import traceback
import pytest
from unittest import TestCase

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import print_ast
from posthog.hogql.visitor import clone_expr
from posthog.hogql.context import HogQLContext
from posthog.clickhouse.client.execute import sync_execute

from posthog.hogql.transforms.state_transforms import (
    transform_query_to_state,
    create_merge_wrapper_query,
    AggregationToStateTransformer,
    AGGREGATION_TO_STATE_MAPPING,
    STATE_TO_MERGE_MAPPING
)

from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    _create_event,
    flush_persons_and_events
)
from posthog.models.team.team import Team # Required for ClickhouseTestMixin
from datetime import datetime # Required for _create_event


class TestStateTransforms(TestCase):
    def test_transform_simple_query_to_state(self):
        """Test transforming a simple query with aggregation functions to state functions"""
        # Simple query with various aggregation functions
        query_str = """
        SELECT
            uniq(distinct_id) AS unique_users,
            count() AS total_events,
            avg(session_duration) AS avg_duration
        FROM events
        WHERE timestamp >= '2023-01-01'
        """

        # Parse the query
        query = parse_select(query_str)
        
        # Create a context for printing SQL
        context = HogQLContext(team_id=1)
        
        # Transform to state query
        state_query = transform_query_to_state(query)
        
        # Check that functions have been transformed but aliases remain unchanged
        for select_item in state_query.select:
            if isinstance(select_item, ast.Alias) and isinstance(select_item.expr, ast.Call):
                # Original alias should be preserved
                self.assertFalse(select_item.alias.endswith("_state"))

                # Function name should be transformed to State version
                function_name = select_item.expr.name
                original_function = function_name.replace("State", "")
                if original_function in AGGREGATION_TO_STATE_MAPPING:
                    self.assertEqual(AGGREGATION_TO_STATE_MAPPING[original_function], function_name)
                    
        # Verify countState() gets argument when count() had none
        for select_item in state_query.select:
            if isinstance(select_item, ast.Alias) and select_item.alias == "total_events":
                # Check countState has at least one argument
                self.assertGreaterEqual(len(select_item.expr.args), 1)

    def test_transform_nested_expressions(self):
        """Test transforming expressions with nested function calls"""
        # Query with nested expressions
        query_str = """
        SELECT
            uniq(distinct_id) AS unique_users,
            count(if(is_bounce, 1, 0)) AS bounce_count
        FROM events
        WHERE timestamp >= '2023-01-01'
        """

        # Parse the query
        query = parse_select(query_str)

        # Transform to state query
        state_query = transform_query_to_state(query)

        # Check nested expressions
        for select_item in state_query.select:
            if isinstance(select_item, ast.Alias) and select_item.alias == "unique_users":
                # Check that uniq was transformed to uniqState
                self.assertEqual(select_item.expr.name, "uniqState")
            
            if isinstance(select_item, ast.Alias) and select_item.alias == "bounce_count":
                # Check that count was transformed to countState
                self.assertEqual(select_item.expr.name, "countState")
                # The inner if function should remain unchanged
                self.assertEqual(select_item.expr.args[0].name, "if")

    def test_preserve_group_by(self):
        """Test that GROUP BY clauses are preserved correctly"""
        # Query with GROUP BY
        query_str = """
        SELECT
            properties.$pathname as pathname,
            uniq(distinct_id) as unique_users,
            count() as total_events
        FROM events
        WHERE timestamp >= '2023-01-01'
        GROUP BY pathname
        """

        # Parse the query
        query = parse_select(query_str)

        # Transform to state query
        state_query = transform_query_to_state(query)

        # GROUP BY should be preserved
        self.assertEqual(len(state_query.group_by), 1)

    def test_create_merge_wrapper_query(self):
        """Test creating a wrapper query that applies merge functions to a state query."""
        # Simple query with state functions
        query_str = """
        SELECT
            uniqState(distinct_id) AS unique_users,
            countState() AS total_events
        FROM events
        WHERE timestamp >= '2023-01-01'
        """

        # Parse the query
        state_query = parse_select(query_str)
        
        # Create wrapper query
        wrapper_query = create_merge_wrapper_query(state_query)
        
        # Verify structure and transformations
        self.assertEqual(len(wrapper_query.select), len(state_query.select))
        
        for i, item in enumerate(wrapper_query.select):
            state_item = state_query.select[i]
            # Aliases should be preserved
            if isinstance(state_item, ast.Alias):
                self.assertEqual(item.alias, state_item.alias)
                
            # Check function transformations
            if isinstance(item, ast.Alias) and isinstance(item.expr, ast.Call):
                if isinstance(state_item.expr, ast.Call) and state_item.expr.name in STATE_TO_MERGE_MAPPING:
                    expected_merge_func = STATE_TO_MERGE_MAPPING[state_item.expr.name]
                    self.assertEqual(item.expr.name, expected_merge_func)
                    
                    # Args should be a reference to the alias
                    self.assertEqual(len(item.expr.args), 1)
                    self.assertIsInstance(item.expr.args[0], ast.Field)
                    self.assertEqual(item.expr.args[0].chain, [state_item.alias])
        
        # Verify we have a subquery with the original state query
        self.assertIsInstance(wrapper_query.select_from, ast.JoinExpr)
        self.assertEqual(wrapper_query.select_from.table, state_query)

    def test_full_transform_chain_with_wrapper(self):
        """Test the complete transformation chain with wrapper query creation."""
        # Original query with regular aggregate functions
        query_str = """
        SELECT
            uniq(distinct_id) AS unique_users,
            count() AS total_events,
            avg(session_duration) AS avg_duration
        FROM events
        WHERE timestamp >= '2023-01-01'
        GROUP BY properties.$host
        ORDER BY total_events DESC
        LIMIT 10
        """

        # Parse the query
        original_query = parse_select(query_str)
        
        # Step 1: Transform to state query
        state_query = transform_query_to_state(original_query)
        
        # Check state transformations
        for item in state_query.select:
            if isinstance(item, ast.Alias) and isinstance(item.expr, ast.Call):
                function_name = item.expr.name
                if function_name in ["uniqState", "countState", "avgState"]:
                    self.assertTrue(function_name.endswith("State"))
        
        # Ensure GROUP BY, ORDER BY, and LIMIT are preserved
        self.assertEqual(len(state_query.group_by), 1)
        self.assertEqual(len(state_query.order_by), 1)
        self.assertEqual(state_query.limit, original_query.limit)
        
        # Step 2: Create wrapper query with merge functions
        wrapper_query = create_merge_wrapper_query(state_query)
        
        # Verify wrapper structure
        self.assertEqual(len(wrapper_query.select), len(state_query.select))
        
        # Check merge functions in wrapper
        for item in wrapper_query.select:
            if isinstance(item, ast.Alias) and isinstance(item.expr, ast.Call):
                function_name = item.expr.name
                if function_name in ["uniqMerge", "countMerge", "avgMerge"]:
                    self.assertTrue(function_name.endswith("Merge"))
                    
                    # Args should be fields referencing inner query aliases
                    self.assertEqual(len(item.expr.args), 1)
                    self.assertIsInstance(item.expr.args[0], ast.Field)
                    
        # Print AST structure (for debugging)
        if 0:  # Set to 1 to enable debug output
            print("\n== Original Query ==")
            self._print_query_ast(original_query)
            
            print("\n== State Query ==")
            self._print_query_ast(state_query)
            
            print("\n== Wrapper Query ==")
            self._print_query_ast(wrapper_query)
    
    def _print_query_ast(self, query):
        """Helper to print AST structure of a query (for debugging)."""
        print(f"Query type: {query.__class__.__name__}")
        print("SELECT items:")
        for i, item in enumerate(query.select):
            print(f"  {i}: {item.__class__.__name__}")
            if isinstance(item, ast.Alias):
                print(f"    Alias: {item.alias}")
                print(f"    Expr: {type(item.expr).__name__}")
                if isinstance(item.expr, ast.Call):
                    print(f"      Function: {item.expr.name}")
                    print(f"      Args: {len(item.expr.args)} args")
        
        if query.group_by:
            print(f"GROUP BY: {len(query.group_by)} items")
        
        if query.order_by:
            print(f"ORDER BY: {len(query.order_by)} items")
        
        if query.limit:
            print(f"LIMIT: {query.limit}") 


class TestStateTransformsIntegration(ClickhouseTestMixin, APIBaseTest):
    """Integration tests for state transformations with ClickHouse execution."""

    def _create_test_events(self):
        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="user_1",
            timestamp=datetime(2023, 1, 1, 12, 0, 0),
            properties={"session_duration": 10, "$host": "app.posthog.com"}
        )
        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="user_1",
            timestamp=datetime(2023, 1, 1, 12, 5, 0),
            properties={"session_duration": 20, "$host": "app.posthog.com"}
        )
        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="user_2",
            timestamp=datetime(2023, 1, 1, 13, 0, 0),
            properties={"session_duration": 30, "$host": "docs.posthog.com"}
        )
        flush_persons_and_events() 

    def test_simple_aggregation_with_db(self):
        """Test full transformation chain executes and matches original query result."""
        self._create_test_events()

        original_query_str = f"""
        SELECT 
            uniq(distinct_id) as unique_users,
            count() as total_pageviews
        FROM events
        """
        original_query_ast = parse_select(original_query_str)

        # Execute original query
        context_original = HogQLContext(team_id=self.team.pk, team=self.team, enable_select_queries=True)
        context_original.enable_select_queries = True # Allow full query printing
        original_sql = print_ast(original_query_ast, context=context_original, dialect="clickhouse")
        original_result = sync_execute(original_sql, context_original.values)

        # Full transformation
        state_query_ast = transform_query_to_state(original_query_ast)
        wrapper_query_ast = create_merge_wrapper_query(state_query_ast)

        # Execute transformed query
        context_transformed = HogQLContext(team_id=self.team.pk, team=self.team, enable_select_queries=True)
        context_transformed.enable_select_queries = True # Allow full query printing
        transformed_sql = print_ast(wrapper_query_ast, context=context_transformed, dialect="clickhouse")
        transformed_result = sync_execute(transformed_sql, context_transformed.values)

        # Assert results are the same
        self.assertEqual(original_result, transformed_result)

        # Expected values based on created events
        self.assertEqual(len(original_result), 1) 
        self.assertEqual(original_result[0][0], 2)
        self.assertEqual(original_result[0][1], 3)