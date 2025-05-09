import pytest

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import print_ast
from posthog.hogql.test.utils import pretty_print_in_tests
from posthog.hogql.context import HogQLContext
from posthog.clickhouse.client.execute import sync_execute

from posthog.hogql.transforms.state_aggregations import (
    transform_query_to_state_aggregations,
    wrap_state_query_in_merge_query,
    AGGREGATION_TO_STATE_MAPPING,
    STATE_TO_MERGE_MAPPING,
)

from posthog.test.base import APIBaseTest, BaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events
from datetime import datetime


class TestStateTransforms(BaseTest):
    def _print_select(self, expr: ast.SelectQuery):
        query = print_ast(
            expr,
            HogQLContext(team_id=self.team.pk, enable_select_queries=True),
            "clickhouse",
        )
        return pretty_print_in_tests(query, self.team.pk)

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

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_transform_nested_expressions(self):
        query_str = """
        SELECT
            uniq(distinct_id) AS unique_users,
            count(if(event = '$pageview', 1, 0)) AS pageview_count
        FROM events
        WHERE timestamp >= '2023-01-01'
        """

        query = parse_select(query_str)
        state_query = transform_query_to_state_aggregations(query)

        printed = self._print_select(state_query)
        assert printed == self.snapshot

    @pytest.mark.usefixtures("unittest_snapshot")
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

        printed = self._print_select(state_query)
        assert printed == self.snapshot

    @pytest.mark.usefixtures("unittest_snapshot")
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

        printed = self._print_select(state_query)
        assert printed == self.snapshot

    @pytest.mark.usefixtures("unittest_snapshot")
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

        self.assertEqual(len(wrapper_query.select), len(state_query.select))

        # Keeping the assertions here to check the AST structure as well as the printed query, it is useful for debugging and improving the transform
        for i, item in enumerate(wrapper_query.select):
            state_item = state_query.select[i]
            if isinstance(state_item, ast.Alias):
                self.assertEqual(item.alias, state_item.alias)

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

        printed = self._print_select(wrapper_query)
        assert printed == self.snapshot

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_merge_wraps_works_with_more_complex_queries(self):
        """Test the complete transformation chain with wrapper query creation."""
        query_str = """
        SELECT
            uniq(distinct_id) AS unique_users,
            count() AS total_events,
            properties.$host as host
        FROM events
        WHERE timestamp >= '2023-01-01'
        GROUP BY host
        ORDER BY total_events DESC
        LIMIT 10
        """

        original_query = parse_select(query_str)
        state_query = transform_query_to_state_aggregations(original_query)
        wrapper_query = wrap_state_query_in_merge_query(state_query)

        printed = self._print_select(wrapper_query)
        assert printed == self.snapshot

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_wrapper_query_aggregation_with_groupby(self):
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

        printed = self._print_select(wrapper_query_ast)
        assert printed == self.snapshot

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_filtered_aggregation(self):
        original_query_str = """
        SELECT
            uniq(distinct_id) as unique_users,
            count() as total_events
        FROM events
        WHERE event = '$pageview'
        """

        original_query_ast = parse_select(original_query_str)

        state_query_ast = transform_query_to_state_aggregations(original_query_ast)
        wrapper_query_ast = wrap_state_query_in_merge_query(state_query_ast)

        printed = self._print_select(wrapper_query_ast)
        assert printed == self.snapshot

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_nested_functions_aggregations_and_conversions(self):
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

        state_query_ast = transform_query_to_state_aggregations(original_query_ast)
        wrapper_query_ast = wrap_state_query_in_merge_query(state_query_ast)

        printed = self._print_select(wrapper_query_ast)
        assert printed == self.snapshot

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_nested_aggregations_in_subquery(self):
        """Test that nested aggregations in subqueries don't get transformed to State functions."""
        original_query_str = """
        SELECT
            sum(filtered_count) AS total_filtered_count
        FROM (
            SELECT
                countIf(event = '$pageview') AS filtered_count
            FROM events
            GROUP BY distinct_id
        )
        """

        original_query_ast = parse_select(original_query_str)

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

        printed = self._print_select(wrapper_query_ast)
        assert printed == self.snapshot

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_query_similar_to_web_overview_query_transformation_sql(self):
        """Test transformation of a web overview query by examining output SQL without executing it."""
        # Create a minimalist mock of a web overview query with nested aggregations
        mock_web_query_str = """
        SELECT
            sum(pageview_count) AS total_pageviews,
            uniq(user_id) AS unique_users
        FROM (
            SELECT
                distinct_id AS user_id,
                countIf(event = '$pageview') AS pageview_count
            FROM events
            GROUP BY distinct_id
        )
        """

        # Parse the query
        mock_web_query_ast = parse_select(mock_web_query_str)
        state_query_ast = transform_query_to_state_aggregations(mock_web_query_ast)
        wrapper_query_ast = wrap_state_query_in_merge_query(state_query_ast)

        printed = self._print_select(wrapper_query_ast)
        assert printed == self.snapshot

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_query_with_as_constants(self):
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

        printed = self._print_select(wrapper_query_ast)
        assert printed == self.snapshot


class TestStateTransformsIntegration(ClickhouseTestMixin, APIBaseTest):
    """Integration tests for state transformations with ClickHouse execution."""

    def setUp(self):
        super().setUp()
        self._create_test_events()

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

    def execute_original_and_merge_queries(self, original_query_ast):
        context_original = HogQLContext(team_id=self.team.pk, team=self.team, enable_select_queries=True)
        original_sql = print_ast(original_query_ast, context=context_original, dialect="clickhouse")
        original_result = sync_execute(original_sql, context_original.values)

        state_query_ast = transform_query_to_state_aggregations(original_query_ast)
        wrapper_query_ast = wrap_state_query_in_merge_query(state_query_ast)

        context_transformed = HogQLContext(team_id=self.team.pk, team=self.team, enable_select_queries=True)
        transformed_sql = print_ast(wrapper_query_ast, context=context_transformed, dialect="clickhouse")
        transformed_result = sync_execute(transformed_sql, context_transformed.values)

        return original_result, transformed_result

    def test_simple_aggregation_with_db(self):
        original_query_str = f"""
        SELECT
            uniq(distinct_id) as unique_users,
            count() as total_pageviews
        FROM events
        """
        original_query_ast = parse_select(original_query_str)

        original_result, transformed_result = self.execute_original_and_merge_queries(original_query_ast)

        self.assertEqual(original_result, transformed_result)

    def test_group_by_values_preserved(self):
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

        original_result, transformed_result = self.execute_original_and_merge_queries(original_query_ast)

        self.assertEqual(original_result, transformed_result)
