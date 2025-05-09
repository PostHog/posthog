from unittest import TestCase
import re
from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.visitor import clone_expr
from posthog.hogql_queries.web_analytics.web_overview_state_transform import (
    transform_query_to_state,
    state_functions_to_merge_functions,
    AggregationToStateTransformer,
    AGGREGATION_TO_STATE_MAPPING,
    STATE_TO_MERGE_MAPPING,
)


class TestWebOverviewStateTransform(TestCase):
    def test_transform_simple_query_to_state(self):
        """Test transforming a simple query with aggregation functions to state functions"""
        # Simple query with various aggregation functions
        query_str = """
        SELECT
            uniq(session_person_id) AS unique_users,
            count(session_id) AS total_sessions,
            sum(pageview_count) AS total_pageviews,
            avg(session_duration) AS avg_duration,
            any(is_bounce) AS has_bounce
        FROM events
        WHERE timestamp >= '2023-01-01'
        """
        
        # Parse the query
        query = parse_select(query_str)
        
        # Transform to state query
        state_query = transform_query_to_state(query)
        
        # Check that functions have been transformed but aliases remain unchanged
        for select_item in state_query.select:
            if isinstance(select_item, ast.Alias) and isinstance(select_item.expr, ast.Call):
                # Original alias should be preserved
                self.assertFalse(select_item.alias.endswith("_state"))
                
                # Function name should be transformed to State version
                function_name = select_item.expr.name
                self.assertTrue(function_name.endswith("State"))
                
                # Check if the transformation is correct according to our mapping
                original_function = function_name.replace("State", "")
                self.assertEqual(AGGREGATION_TO_STATE_MAPPING[original_function], function_name)
    
    def test_transform_nested_expressions(self):
        """Test transforming queries with nested expressions"""
        query_str = """
        SELECT
            uniq(session_person_id) AS unique_users,
            count(if(is_bounce, 1, 0)) AS bounce_count,
            sum(multiIf(device_type = 'mobile', 1, device_type = 'tablet', 2, 3)) AS device_score
        FROM events
        """
        
        # Parse the query
        query = parse_select(query_str)
        
        # Transform to state query
        state_query = transform_query_to_state(query)
        
        # Check that outer functions have been transformed to state functions
        # but inner functions remain unchanged
        select_items = state_query.select
        
        # Check first item - uniqState
        self.assertEqual(select_items[0].alias, "unique_users")
        self.assertEqual(select_items[0].expr.name, "uniqState")
        
        # Check second item - countState with if inside
        self.assertEqual(select_items[1].alias, "bounce_count")
        self.assertEqual(select_items[1].expr.name, "countState")
        self.assertEqual(select_items[1].expr.args[0].name, "if")  # if function should remain unchanged
        
        # Check third item - sumState with multiIf inside
        self.assertEqual(select_items[2].alias, "device_score")
        self.assertEqual(select_items[2].expr.name, "sumState")
        self.assertEqual(select_items[2].expr.args[0].name, "multiIf")  # multiIf function should remain unchanged
    
    def test_transformer_tracking(self):
        """Test that the transformer correctly tracks the transformed functions"""
        # Simple query with various aggregation functions
        query_str = """
        SELECT
            uniq(session_person_id) AS unique_users,
            count(session_id) AS total_sessions,
            sum(pageview_count) AS total_pageviews
        FROM events
        """
        
        # Parse the query
        query = parse_select(query_str)
        
        # Create transformer and apply it directly
        transformer = AggregationToStateTransformer()
        transformed_query = clone_expr(query)
        
        # Transform each expression in the select clause
        for i, item in enumerate(transformed_query.select):
            if isinstance(item, ast.Alias) and isinstance(item.expr, ast.Call):
                transformed_query.select[i].expr = transformer.visit(item.expr)
        
        # Check that the transformer correctly tracked the transformed functions
        expected_transformations = {
            "uniq": "uniqState",
            "count": "countState",
            "sum": "sumState",
        }
        
        self.assertEqual(transformer.transformed_functions, expected_transformations)
    
    def test_group_by_preserved(self):
        """Test that GROUP BY clauses are preserved in the transformation"""
        query_str = """
        SELECT
            host,
            uniq(session_person_id) AS unique_users,
            count(session_id) AS total_sessions
        FROM events
        GROUP BY host
        """
        
        # Parse the query
        query = parse_select(query_str)
        
        # Transform to state query
        state_query = transform_query_to_state(query)
        
        # Check that GROUP BY is preserved
        self.assertIsNotNone(state_query.group_by)
        self.assertEqual(len(state_query.group_by), 1)
        
        # Check that regular field is not transformed
        self.assertIsInstance(state_query.select[0], ast.Field)
        self.assertEqual(state_query.select[0].chain, ['host'])
        
        # Check that aggregate functions are transformed but aliases remain the same
        self.assertEqual(state_query.select[1].alias, "unique_users")
        self.assertEqual(state_query.select[1].expr.name, "uniqState")
        
        self.assertEqual(state_query.select[2].alias, "total_sessions")
        self.assertEqual(state_query.select[2].expr.name, "countState")
    
    def test_state_functions_to_merge_functions(self):
        """Test converting state functions to merge functions"""
        # Start with a query that already has state functions
        query_str = """
        SELECT
            uniqState(session_person_id) AS unique_users,
            countState(session_id) AS total_sessions,
            sumState(pageview_count) AS total_pageviews
        FROM events
        """
        
        # Parse the query
        query = parse_select(query_str)
        
        # Transform to merge query
        merge_query = state_functions_to_merge_functions(query)
        
        # Check that functions have been transformed but aliases remain unchanged
        select_items = merge_query.select
        
        # Check the functions were transformed properly
        self.assertEqual(select_items[0].alias, "unique_users")
        self.assertEqual(select_items[0].expr.name, "uniqMerge")
        
        self.assertEqual(select_items[1].alias, "total_sessions")
        self.assertEqual(select_items[1].expr.name, "countMerge")
        
        self.assertEqual(select_items[2].alias, "total_pageviews")
        self.assertEqual(select_items[2].expr.name, "sumMerge")
    
    def test_full_transformation_chain(self):
        """Test the entire transformation chain from regular to state to merge functions"""
        query_str = """
        SELECT
            uniq(session_person_id) AS unique_users,
            count(session_id) AS total_sessions,
            sum(pageview_count) AS total_pageviews
        FROM events
        """
        
        # Parse the query
        original_query = parse_select(query_str)
        
        # Step 1: Transform to state query
        state_query = transform_query_to_state(original_query)
        
        # Verify state transformation
        self.assertEqual(state_query.select[0].expr.name, "uniqState")
        self.assertEqual(state_query.select[1].expr.name, "countState")
        self.assertEqual(state_query.select[2].expr.name, "sumState")
        
        # Step 2: Transform to merge query
        merge_query = state_functions_to_merge_functions(state_query)
        
        # Verify merge transformation
        self.assertEqual(merge_query.select[0].expr.name, "uniqMerge")
        self.assertEqual(merge_query.select[1].expr.name, "countMerge")
        self.assertEqual(merge_query.select[2].expr.name, "sumMerge")
        
        # Aliases should be preserved throughout the chain
        self.assertEqual(merge_query.select[0].alias, "unique_users")
        self.assertEqual(merge_query.select[1].alias, "total_sessions")
        self.assertEqual(merge_query.select[2].alias, "total_pageviews") 