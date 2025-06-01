from typing import Any
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
)

from posthog.test.base import APIBaseTest, BaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events
from datetime import datetime


class TestStateTransforms(BaseTest):
    snapshot: Any

    def _print_select(self, expr: ast.SelectQuery | ast.SelectSetQuery):
        query = print_ast(
            expr,
            HogQLContext(team_id=self.team.pk, enable_select_queries=True),
            "clickhouse",
        )
        return pretty_print_in_tests(query, self.team.pk)

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_transform_simple_query_to_state_aggregations(self):
        query_str = """
        SELECT
            uniq(distinct_id) AS unique_users,
            count() AS total_events
        FROM events
        WHERE timestamp >= '2023-01-01'
        """

        query = parse_select(query_str)
        state_query = transform_query_to_state_aggregations(query)

        printed = self._print_select(state_query)
        assert printed == self.snapshot

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

        printed = self._print_select(state_query)
        assert printed == self.snapshot

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_preserve_query_without_aggregations(self):
        query_str = """
        SELECT
            distinct_id as distinct_id,
            properties.$pathname as pathname
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

        state_query_ast = transform_query_to_state_aggregations(original_query_ast)
        wrapper_query_ast = wrap_state_query_in_merge_query(state_query_ast)

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
        state_query_ast = transform_query_to_state_aggregations(query_ast)
        wrapper_query_ast = wrap_state_query_in_merge_query(state_query_ast)

        printed = self._print_select(wrapper_query_ast)
        assert printed == self.snapshot

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_combine_two_different_state_queries_into_one_merge_query(self):
        """Test combining two different state queries into one merge query without database interaction."""
        # Define the queries
        old_data_query = """
        SELECT
            count() AS total_pageviews
        FROM events
        WHERE timestamp < now() - INTERVAL 1 DAY
        """
        current_data_query = """
        SELECT
            count() AS total_pageviews
        FROM events
        WHERE timestamp >= now() - INTERVAL 1 DAY
        """

        old_data_query_ast = parse_select(old_data_query)
        current_data_query_ast = parse_select(current_data_query)

        old_data_state_query_ast = transform_query_to_state_aggregations(old_data_query_ast)
        current_data_state_query_ast = transform_query_to_state_aggregations(current_data_query_ast)

        # Create a SelectSetQuery with the two queries. This is a possible way we can combine the pre-aggregated data with the current data.
        # Example: web_bounces_daily with the current day results of web_overview query.
        select_set_query_ast = ast.SelectSetQuery(
            initial_select_query=old_data_state_query_ast,
            subsequent_select_queries=[
                ast.SelectSetNode(select_query=current_data_state_query_ast, set_operator="UNION ALL")
            ],
        )

        wrapper_query_ast = wrap_state_query_in_merge_query(select_set_query_ast)

        wrapper_simplified = self._print_select(wrapper_query_ast)
        assert wrapper_simplified == self.snapshot

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_union_all_state_queries_into_one_merge_query(self):
        """Test combining two different state queries into one merge query without database interaction."""
        # Define the queries
        query = """
        SELECT
            count() AS total_pageviews
        FROM events
        WHERE timestamp < now() - INTERVAL 1 DAY
        UNION ALL
        SELECT
            count() AS total_pageviews
        FROM events
        WHERE timestamp >= now() - INTERVAL 1 DAY
        """

        query_ast = parse_select(query)

        state_query_ast = transform_query_to_state_aggregations(query_ast)
        wrapper_query_ast = wrap_state_query_in_merge_query(state_query_ast)

        wrapper_simplified = self._print_select(wrapper_query_ast)
        assert wrapper_simplified == self.snapshot

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_tuple_with_state_aggregations(self):
        query_str = """
        SELECT
            (uniqState(distinct_id), countState()) AS user_stats,
            properties.$host as host
        FROM events
        WHERE timestamp >= '2023-01-01'
        GROUP BY host
        """

        state_query = parse_select(query_str)
        wrapper_query = wrap_state_query_in_merge_query(state_query)

        printed = self._print_select(wrapper_query)
        assert printed == self.snapshot

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_tuple_with_conditional_aggregations(self):
        query_str = """
        SELECT
            (
                uniqStateIf(distinct_id, 1),
                countStateIf(1),
                sumStateIf(1, 1)
            ) AS conditional_stats
        FROM events
        """

        state_query = parse_select(query_str)
        wrapper_query = wrap_state_query_in_merge_query(state_query)

        printed = self._print_select(wrapper_query)
        assert printed == self.snapshot

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_tuple_with_mixed_aggregations_and_non_aggregations(self):
        query_str = """
        SELECT
            (uniqState(distinct_id), 'constant_value', countState()) AS mixed_stats,
            sumState(1) as total_sum
        FROM events
        WHERE timestamp >= '2023-01-01'
        """

        state_query = parse_select(query_str)
        wrapper_query = wrap_state_query_in_merge_query(state_query)

        printed = self._print_select(wrapper_query)
        assert printed == self.snapshot

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_multiple_tuples_with_state_aggregations(self):
        query_str = """
        SELECT
            (uniqState(distinct_id), countState()) AS user_stats,
            (sumState(1), avgState(1)) AS metric_stats
        FROM events
        WHERE timestamp >= '2023-01-01'
        """

        state_query = parse_select(query_str)
        wrapper_query = wrap_state_query_in_merge_query(state_query)

        printed = self._print_select(wrapper_query)
        assert printed == self.snapshot

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_transformation_from_regular_to_state_then_merge_with_tuples(self):
        original_query_str = """
        SELECT
            (uniq(distinct_id), count()) AS user_stats,
            (sum(1), avg(1)) AS metric_stats
        FROM events
        WHERE timestamp >= '2023-01-01'
        """

        original_query = parse_select(original_query_str)
        state_query = transform_query_to_state_aggregations(original_query)
        wrapper_query = wrap_state_query_in_merge_query(state_query)

        printed = self._print_select(wrapper_query)
        assert printed == self.snapshot

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_tuple_with_constants_and_state_aggregations(self):
        query_str = """
        SELECT
            (uniqState(distinct_id), NULL, countState(), 'constant_string', 42) AS mixed_tuple
        FROM events
        """

        state_query = parse_select(query_str)
        wrapper_query = wrap_state_query_in_merge_query(state_query)

        printed = self._print_select(wrapper_query)
        assert printed == self.snapshot

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_tuple_in_subquery_remains_unchanged(self):
        query_str = """
        SELECT
            sumState(filtered_metrics.total_count) AS aggregated_total
        FROM (
            SELECT
                (uniq(distinct_id), count()) AS user_metrics,
                sum(1) AS total_count
            FROM events
        ) AS filtered_metrics
        """

        state_query = parse_select(query_str)
        wrapper_query = wrap_state_query_in_merge_query(state_query)

        printed = self._print_select(wrapper_query)
        assert printed == self.snapshot


class TestStateTransformsIntegration(ClickhouseTestMixin, APIBaseTest):
    """
    Integration tests for state transformations with ClickHouse execution.
    It is a simple way to make sure we're getting the same results from the original and transformed queries.
    """

    def setUp(self):
        super().setUp()
        self._create_test_events()

    def _print_select(self, expr: ast.SelectQuery):
        query = print_ast(
            expr,
            HogQLContext(team_id=self.team.pk, enable_select_queries=True),
            "clickhouse",
        )
        return pretty_print_in_tests(query, self.team.pk)

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
        original_query_str = """
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

    def test_tuple_aggregations_with_db(self):
        original_query_str = """
        SELECT
            (uniq(distinct_id), count()) as user_stats,
            properties.$host as host
        FROM events
        GROUP BY host
        ORDER BY host ASC
        """

        original_query_ast = parse_select(original_query_str)

        original_result, transformed_result = self.execute_original_and_merge_queries(original_query_ast)

        self.assertEqual(original_result, transformed_result)

    def test_complex_tuple_aggregations_with_db(self):
        original_query_str = """
        SELECT
            (
                uniq(distinct_id),
                countIf(event = '$pageview'),
                sum(toFloat(properties.session_duration))
            ) as complex_stats,
            properties.$host as host
        FROM events
        GROUP BY host
        ORDER BY host ASC
        """

        original_query_ast = parse_select(original_query_str)

        original_result, transformed_result = self.execute_original_and_merge_queries(original_query_ast)

        self.assertEqual(original_result, transformed_result)

    def test_multiple_tuples_aggregations_with_db(self):
        original_query_str = """
        SELECT
            (uniq(distinct_id), count()) as user_metrics,
            (sum(toFloat(properties.session_duration)), avg(toFloat(properties.session_duration))) as duration_metrics,
            properties.$host as host
        FROM events
        GROUP BY host
        ORDER BY host ASC
        """

        original_query_ast = parse_select(original_query_str)

        original_result, transformed_result = self.execute_original_and_merge_queries(original_query_ast)

        self.assertEqual(original_result, transformed_result)
