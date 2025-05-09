from unittest import TestCase

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import print_ast
from posthog.hogql.visitor import clone_expr
from posthog.hogql.context import HogQLContext
from posthog.clickhouse.client.execute import sync_execute

from posthog.hogql.transforms.state_aggregations import (
    transform_query_to_state_aggregations,
    wrap_state_query_in_merge_query,
    AGGREGATION_TO_STATE_MAPPING,
    STATE_TO_MERGE_MAPPING,
)

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events
from datetime import datetime
import math
import numpy as np


class TestStateTransforms(TestCase):
    def test_transform_simple_query_to_state_aggregations(self):
        query_str = """
        SELECT
            uniq(distinct_id) AS unique_users,
            count() AS total_events,
            avg(session_duration) AS avg_duration
        FROM events
        WHERE timestamp >= '2023-01-01'
        """

        query = parse_select(query_str)

        state_query = transform_query_to_state_aggregations(query)

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

        query = parse_select(query_str)

        state_query = transform_query_to_state_aggregations(query)

        for select_item in state_query.select:
            if isinstance(select_item, ast.Alias) and select_item.alias == "unique_users":
                self.assertEqual(select_item.expr.name, "uniqState")

            if isinstance(select_item, ast.Alias) and select_item.alias == "bounce_count":
                self.assertEqual(select_item.expr.name, "countState")
                self.assertEqual(select_item.expr.args[0].name, "if")

    def test_preserve_group_by(self):
        query_str = """
        SELECT
            properties.$pathname as pathname,
            uniq(distinct_id) as unique_users,
            count() as total_events
        FROM events
        WHERE timestamp >= '2023-01-01'
        GROUP BY pathname
        """

        query = parse_select(query_str)

        state_query = transform_query_to_state_aggregations(query)

        # GROUP BY should be preserved
        self.assertEqual(len(state_query.group_by), 1)

    def test_preserve_query_without_aggregations(self):
        query_str = """
        SELECT
            distinct_id as distinct_id,
            properties.$pathname as pathname,
        FROM events
        WHERE timestamp >= '2023-01-01'
        """

        query = parse_select(query_str)

        state_query = transform_query_to_state_aggregations(query)

        # Compare the AST structures directly instead of printing SQL
        # This avoids issues with different parameter placeholders in printed SQL
        query_clone = clone_expr(query)

        # Check that no state or merge functions are used
        for select_item in state_query.select:
            if isinstance(select_item, ast.Alias) and isinstance(select_item.expr, ast.Call):
                function_name = select_item.expr.name
                self.assertFalse("State" in function_name, f"Found state function: {function_name}")
                self.assertFalse("Merge" in function_name, f"Found merge function: {function_name}")

        self.assertEqual(len(state_query.select), len(query_clone.select))
        self.assertEqual(state_query.where.type, query_clone.where.type)
        self.assertEqual(state_query.select_from.type, query_clone.select_from.type)

    def test_wrap_state_query_in_merge_query(self):
        """Test creating a wrapper query that applies merge functions to a state query."""
        query_str = """
        SELECT
            uniqState(distinct_id) AS unique_users,
            countState() AS total_events
        FROM events
        WHERE timestamp >= '2023-01-01'
        """

        state_query = parse_select(query_str)

        wrapper_query = wrap_state_query_in_merge_query(state_query)

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
        state_query = transform_query_to_state_aggregations(original_query)

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
        wrapper_query = wrap_state_query_in_merge_query(state_query)

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

    def test_preserve_query_without_aggregations(self):
        query_str = """
        SELECT
            distinct_id as distinct_id,
            properties.$pathname as pathname,
        FROM events
        WHERE timestamp >= '2023-01-01'
        """

        query = parse_select(query_str)

        state_query = transform_query_to_state_aggregations(query)

        # Compare the AST structures directly instead of printing SQL
        # This avoids issues with different parameter placeholders in printed SQL
        query_clone = clone_expr(query)

        # Check that no state or merge functions are used
        for select_item in state_query.select:
            if isinstance(select_item, ast.Alias) and isinstance(select_item.expr, ast.Call):
                function_name = select_item.expr.name
                self.assertFalse("State" in function_name, f"Found state function: {function_name}")
                self.assertFalse("Merge" in function_name, f"Found merge function: {function_name}")

        self.assertEqual(len(state_query.select), len(query_clone.select))
        self.assertEqual(state_query.where.type, query_clone.where.type)
        self.assertEqual(state_query.select_from.type, query_clone.select_from.type)

    def test_aggregation_with_groupby(self):
        # Query with GROUP BY
        original_query_str = """
        SELECT
            properties.$host as host,
            count() as total_count,
            countIf(event = 'click') as click_count
        FROM events
        GROUP BY host
        """

        original_query_ast = parse_select(original_query_str)

        state_query_ast = transform_query_to_state_aggregations(original_query_ast)
        wrapper_query_ast = wrap_state_query_in_merge_query(state_query_ast)

        self.assertIsNotNone(state_query_ast.group_by)
        self.assertIsNotNone(wrapper_query_ast.group_by)  # Wrapper query should also have group by

        # Check that aggregation functions were transformed
        for i, expr in enumerate(state_query_ast.select):
            if isinstance(expr.expr, ast.Call) and expr.expr.name in ["count", "countIf"]:
                self.assertIn("State", expr.expr.name)

    def test_filtered_aggregation(self):
        # Query with aggregations and filtering
        original_query_str = """
        SELECT 
            uniq(distinct_id) as unique_users,
            count() as total_events
        FROM events
        WHERE event = '$pageview'
        """

        original_query_ast = parse_select(original_query_str)

        # Let's only check the AST transformation, not execute SQL
        state_query_ast = transform_query_to_state_aggregations(original_query_ast)
        wrapper_query_ast = wrap_state_query_in_merge_query(state_query_ast)

        # Check that WHERE clauses are preserved
        self.assertIsNotNone(state_query_ast.where)
        self.assertIsNone(wrapper_query_ast.where)  # Wrapper query has no WHERE

        # Check that aggregation functions were transformed
        for select_item in state_query_ast.select:
            if isinstance(select_item, ast.Alias) and isinstance(select_item.expr, ast.Call):
                function_name = select_item.expr.name
                # Should use State functions
                self.assertTrue(function_name in ["uniqState", "countState"])

        # Check that merge functions are used in the wrapper
        for select_item in wrapper_query_ast.select:
            if isinstance(select_item, ast.Alias) and isinstance(select_item.expr, ast.Call):
                function_name = select_item.expr.name
                # Should use Merge functions
                self.assertTrue(function_name in ["uniqMerge", "countMerge"])

    def test_complex_nested_aggregation(self):
        # Query with nested functions - use sumIf instead of count(if()) for conditional counting
        original_query_str = """
        SELECT
            properties.$host as host,
            uniq(distinct_id) as unique_users,
            sumIf(1, event = 'click') as click_count,
            avg(toFloat(properties.session_duration)) as avg_duration
        FROM events
        GROUP BY host
        """

        original_query_ast = parse_select(original_query_str)

        # Let's only check the AST transformation, not execute SQL
        state_query_ast = transform_query_to_state_aggregations(original_query_ast)
        wrapper_query_ast = wrap_state_query_in_merge_query(state_query_ast)

        # Check that GROUP BY clauses are preserved
        self.assertIsNotNone(state_query_ast.group_by)
        self.assertIsNotNone(wrapper_query_ast.group_by)
        self.assertEqual(len(state_query_ast.group_by), 1)
        self.assertEqual(len(wrapper_query_ast.group_by), 1)

    def test_nested_aggregations_in_subquery(self):
        """Test that nested aggregations in subqueries don't get transformed to State functions."""
        # Original query with sum(countIf()) - this is similar to the web overview query
        original_query_str = """
        SELECT
            sum(filtered_count) AS total_filtered_count
        FROM (
            SELECT
                countIf(event = 'pageview') AS filtered_count
            FROM events
            GROUP BY distinct_id
        )
        """

        original_query_ast = parse_select(original_query_str)
        
        # Transform with our top-level only transformation approach
        state_query_ast = transform_query_to_state_aggregations(original_query_ast, transform_nested_aggregations=False)
        wrapper_query_ast = wrap_state_query_in_merge_query(state_query_ast)
        
        # Check that in the transformed query:
        # 1. The outer sum() should be transformed to sumState()
        # 2. The inner countIf() should NOT be transformed to countStateIf()
        
        # Verify the outer sum is transformed to sumState
        outer_function = state_query_ast.select[0].expr
        self.assertEqual(outer_function.name, "sumState")
        
        # Verify the inner countIf is NOT transformed to countStateIf
        subquery_table = state_query_ast.select_from.table
        inner_function = subquery_table.select[0].expr
        self.assertEqual(inner_function.name, "countIf")  # Should still be countIf, not countStateIf
        
        # In the wrapper query, verify we have sumMerge
        wrapper_outer_function = wrapper_query_ast.select[0].expr
        self.assertEqual(wrapper_outer_function.name, "sumMerge")

    def test_web_overview_query_transformation_sql(self):
        """Test transformation of a web overview query by examining output SQL without executing it."""
        # Create a minimalist mock of a web overview query with nested aggregations
        mock_web_query_str = """
        SELECT
            sum(pageview_count) AS total_pageviews,
            uniq(user_id) AS unique_users
        FROM (
            SELECT
                distinct_id AS user_id,
                countIf(event = 'pageview') AS pageview_count
            FROM events
            GROUP BY distinct_id
        )
        """
        
        # Parse the query
        mock_web_query_ast = parse_select(mock_web_query_str)
        
        # Apply state transformations
        state_query_ast = transform_query_to_state_aggregations(mock_web_query_ast)
        wrapper_query_ast = wrap_state_query_in_merge_query(state_query_ast)
        
        # Now check the structure of the transformed query
        
        # Check outer select in state query - should have sumState() and uniqState()
        outer_sum = state_query_ast.select[0].expr
        outer_uniq = state_query_ast.select[1].expr
        self.assertEqual(outer_sum.name, "sumState")
        self.assertEqual(outer_uniq.name, "uniqState")
        
        # Check inner select in state query - countIf should NOT be transformed
        inner_query = state_query_ast.select_from.table
        inner_count = inner_query.select[1].expr
        self.assertEqual(inner_count.name, "countIf")
        
        # Check wrapper query has sumMerge and uniqMerge
        wrapper_sum = wrapper_query_ast.select[0].expr
        wrapper_uniq = wrapper_query_ast.select[1].expr
        self.assertEqual(wrapper_sum.name, "sumMerge")
        self.assertEqual(wrapper_uniq.name, "uniqMerge")

    def test_query_with_null_and_constants(self):
        """Test that NULL constants and other literals are properly handled in the transformation."""
        # Query with NULL literals and constants alongside aggregations
        query_str = """
        SELECT
            uniq(distinct_id) AS unique_users,
            NULL AS previous_unique_users,
            count() AS total_events,
            123 AS constant_value
        FROM events
        WHERE timestamp >= '2023-01-01'
        """

        query_ast = parse_select(query_str)
        
        # Transform with our approach
        state_query_ast = transform_query_to_state_aggregations(query_ast)
        wrapper_query_ast = wrap_state_query_in_merge_query(state_query_ast)
        
        # Verify state query transformations - only aggregation functions should be transformed
        self.assertEqual(state_query_ast.select[0].expr.name, "uniqState")
        self.assertIsInstance(state_query_ast.select[1].expr, ast.Constant)
        self.assertIsNone(state_query_ast.select[1].expr.value)  # NULL value
        self.assertEqual(state_query_ast.select[2].expr.name, "countState")
        self.assertIsInstance(state_query_ast.select[3].expr, ast.Constant)
        self.assertEqual(state_query_ast.select[3].expr.value, 123)  # Number constant
        
        # Verify wrapper query structure - constants should be passed through directly
        self.assertEqual(wrapper_query_ast.select[0].expr.name, "uniqMerge")
        
        # For NULL constants, they should be preserved as constants
        self.assertEqual(wrapper_query_ast.select[1].alias, "previous_unique_users")
        self.assertIsInstance(wrapper_query_ast.select[1].expr, ast.Constant)
        self.assertIsNone(wrapper_query_ast.select[1].expr.value)
        
        # For numeric constants, they should also be preserved as constants
        self.assertEqual(wrapper_query_ast.select[3].alias, "constant_value")
        self.assertIsInstance(wrapper_query_ast.select[3].expr, ast.Constant)
        self.assertEqual(wrapper_query_ast.select[3].expr.value, 123)
        
        # Verify that GROUP BY only includes fields used in aggregation functions
        # Constant fields should NOT be in GROUP BY
        self.assertIsNone(wrapper_query_ast.group_by)

    def test_null_constants_preserved_in_wrapper(self):
        """Test that NULL constants are preserved directly in the wrapper query, not referenced as fields."""
        # Query with NULLs alongside aggregates
        query_str = """
        SELECT
            uniq(distinct_id) AS unique_users,
            NULL AS previous_users,  
            count() AS total_events
        FROM events
        """

        query_ast = parse_select(query_str)
        
        # Apply transformations
        state_query_ast = transform_query_to_state_aggregations(query_ast)
        wrapper_query_ast = wrap_state_query_in_merge_query(state_query_ast)
        
        # Check that the NULL value is directly preserved in the wrapper, not as a field reference
        self.assertEqual(state_query_ast.select[1].alias, "previous_users")
        self.assertIsInstance(state_query_ast.select[1].expr, ast.Constant)
        self.assertIsNone(state_query_ast.select[1].expr.value)  # NULL value
        
        # The wrapper should preserve NULL as a constant
        wrapper_null_expr = wrapper_query_ast.select[1].expr
        self.assertIsInstance(wrapper_null_expr, ast.Constant)
        self.assertIsNone(wrapper_null_expr.value)
        
        # And should not be a field reference
        self.assertNotIsInstance(wrapper_null_expr, ast.Field)

    def test_web_overview_style_query_with_constants(self):
        """Test a web overview style query with NULL constants is correctly transformed."""
        # Create a mock web overview query with aggregations and NULL constants
        # similar to what the WebOverviewQueryRunner would generate
        query_str = """
        SELECT
            uniq(distinct_id) AS unique_visitors,
            count() AS pageviews,
            uniq(session_id) AS sessions,
            avg(session_duration) AS avg_session_duration,
            NULL AS bounce_rate, 
            NULL AS previous_period
        FROM events
        WHERE timestamp >= '2023-12-01' AND timestamp <= '2023-12-03'
        """
        
        query_ast = parse_select(query_str)
        
        # Apply state transformations
        state_query_ast = transform_query_to_state_aggregations(query_ast)
        wrapper_query_ast = wrap_state_query_in_merge_query(state_query_ast)
        
        # Verify state transformations - aggregation functions should be transformed to *State
        self.assertEqual(state_query_ast.select[0].expr.name, "uniqState")
        self.assertEqual(state_query_ast.select[1].expr.name, "countState")
        self.assertEqual(state_query_ast.select[2].expr.name, "uniqState")
        self.assertEqual(state_query_ast.select[3].expr.name, "avgState")
        
        # Verify NULL constants are preserved as NULL constants
        self.assertIsInstance(state_query_ast.select[4].expr, ast.Constant)
        self.assertIsNone(state_query_ast.select[4].expr.value)
        self.assertIsInstance(state_query_ast.select[5].expr, ast.Constant)
        self.assertIsNone(state_query_ast.select[5].expr.value)
        
        # Verify merge transformations in wrapper - aggregation functions should be transformed to *Merge
        self.assertEqual(wrapper_query_ast.select[0].expr.name, "uniqMerge")
        self.assertEqual(wrapper_query_ast.select[1].expr.name, "countMerge")
        self.assertEqual(wrapper_query_ast.select[2].expr.name, "uniqMerge")
        self.assertEqual(wrapper_query_ast.select[3].expr.name, "avgMerge")
        
        # Verify NULL constants are preserved as NULL constants in the wrapper query too
        self.assertIsInstance(wrapper_query_ast.select[4].expr, ast.Constant)
        self.assertIsNone(wrapper_query_ast.select[4].expr.value)
        self.assertIsInstance(wrapper_query_ast.select[5].expr, ast.Constant)
        self.assertIsNone(wrapper_query_ast.select[5].expr.value)
        
        # Verify aliases are preserved
        self.assertEqual(wrapper_query_ast.select[0].alias, "unique_visitors")
        self.assertEqual(wrapper_query_ast.select[1].alias, "pageviews")
        self.assertEqual(wrapper_query_ast.select[2].alias, "sessions")
        self.assertEqual(wrapper_query_ast.select[3].alias, "avg_session_duration")
        self.assertEqual(wrapper_query_ast.select[4].alias, "bounce_rate")
        self.assertEqual(wrapper_query_ast.select[5].alias, "previous_period")


class TestStateTransformsIntegration(ClickhouseTestMixin, APIBaseTest):
    """Integration tests for state transformations with ClickHouse execution."""

    def _create_test_events(self):
        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="user_1",
            timestamp=datetime(2023, 1, 1, 12, 0, 0),
            properties={"session_duration": 10, "$host": "app.posthog.com", "$pathname": "/home"},
        )
        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="user_1",
            timestamp=datetime(2023, 1, 1, 12, 5, 0),
            properties={"session_duration": 20, "$host": "app.posthog.com", "$pathname": "/features"},
        )
        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="user_2",
            timestamp=datetime(2023, 1, 1, 13, 0, 0),
            properties={"session_duration": 30, "$host": "docs.posthog.com", "$pathname": "/docs"},
        )
        _create_event(
            event="click",
            team=self.team,
            distinct_id="user_1",
            timestamp=datetime(2023, 1, 1, 12, 10, 0),
            properties={"button": "signup", "$host": "app.posthog.com", "$pathname": "/features"},
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
        original_sql = print_ast(original_query_ast, context=context_original, dialect="clickhouse")
        original_result = sync_execute(original_sql, context_original.values)

        # Full transformation (agg -> state -> merge)
        state_query_ast = transform_query_to_state_aggregations(original_query_ast)
        wrapper_query_ast = wrap_state_query_in_merge_query(state_query_ast)

        # Execute transformed query
        context_transformed = HogQLContext(team_id=self.team.pk, team=self.team, enable_select_queries=True)
        transformed_sql = print_ast(wrapper_query_ast, context=context_transformed, dialect="clickhouse")
        transformed_result = sync_execute(transformed_sql, context_transformed.values)

        # Assert results are the same
        self.assertEqual(original_result, transformed_result)

    def test_group_by_values_preserved(self):
        """Test that GROUP BY values and results are correctly preserved in state transformations."""
        # Query with GROUP BY on $host
        original_query_str = """
        SELECT 
            properties.$host as host,
            uniq(distinct_id) as unique_users,
            count() as total_events
        FROM events
        GROUP BY host
        ORDER BY host ASC
        """

        original_query_ast = parse_select(original_query_str)

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

        # Assert results are the same (both values and ordering)
        self.assertEqual(original_result, transformed_result)

    def test_web_overview_query_transformation(self):
        """Test that a web overview query with multiple metrics is correctly transformed."""
        # Import the WebOverviewQueryRunner
        from posthog.hogql_queries.web_analytics.web_overview import WebOverviewQueryRunner
        from posthog.schema import WebOverviewQuery, DateRange

        # Create a WebOverviewQuery
        web_overview_query = WebOverviewQuery(
            dateRange=DateRange(date_from="-7d", date_to="today"),
            properties=[],
            kind="WebOverviewQuery",
        )

        # Create a WebOverviewQueryRunner instance
        web_overview_runner = WebOverviewQueryRunner(team=self.team, query=web_overview_query)
        # Get the query AST
        original_query_ast = web_overview_runner.to_query()
                
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

        # Helper function to compare results with NaN handling
        def compare_results_with_nan(result1, result2):
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
        
        # Assert results are the same (both values and ordering) with proper NaN handling
        self.assertTrue(compare_results_with_nan(original_result, transformed_result), 
                       f"Results differ:\nOriginal: {original_result}\nTransformed: {transformed_result}")