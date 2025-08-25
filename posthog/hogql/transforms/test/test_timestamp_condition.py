

from posthog.test.base import BaseTest

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import create_hogql_database
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import print_ast
from posthog.hogql.transforms.timestamp_condition import optimize_timestamp_conditions


class TestTimestampConditionOptimizer(BaseTest):
    def setUp(self):
        super().setUp()
        self.context = HogQLContext(team_id=self.team.pk)
        self.context.database = create_hogql_database(self.team.pk)

    def _parse_and_optimize(self, query: str) -> ast.SelectQuery:
        """Parse a query and apply timestamp optimization."""
        parsed = parse_select(query)
        return optimize_timestamp_conditions(parsed, self.context)

    def _print_optimized(self, query: str) -> str:
        """Parse, optimize, and print the query."""
        optimized = self._parse_and_optimize(query)
        return print_ast(optimized, self.context, dialect="clickhouse", pretty=False)

    def test_simple_query_without_date_conditions(self):
        """Test that a simple query without date conditions gets toDate conditions added."""
        query = "SELECT count(*) FROM events WHERE event = 'pageview'"
        result = self._print_optimized(query)

        # Should contain toDate conditions
        assert "toDate(timestamp)" in result
        assert ">=" in result
        assert "<=" in result

    def test_query_with_existing_timestamp_condition(self):
        """Test that existing timestamp conditions are used to determine date range."""
        query = "SELECT count(*) FROM events WHERE timestamp > '2024-01-01' AND event = 'pageview'"
        result = self._print_optimized(query)

        print(result)
        # Should contain toDate conditions based on the existing timestamp
        assert "toDate(timestamp)" in result
        assert "toDate('2024-01-01')" in result

    def test_query_with_existing_todate_condition(self):
        """Test that queries with existing toDate conditions are not modified."""
        query = """
            SELECT count(*) FROM events 
            WHERE toDate(timestamp) >= toDate('2024-01-01') 
            AND toDate(timestamp) <= toDate('2024-01-31')
            AND event = 'pageview'
        """
        result = self._print_optimized(query)

        # Count occurrences of toDate(timestamp) - should be exactly 2 (the original ones)
        todate_count = result.count("toDate(timestamp)")
        assert todate_count == 2

    def test_query_with_table_alias(self):
        """Test that queries with table aliases work correctly."""
        query = "SELECT count(*) FROM events e WHERE e.event = 'pageview'"
        result = self._print_optimized(query)

        # Should contain toDate conditions with the alias
        assert "toDate(e.timestamp)" in result or "toDate(timestamp)" in result

    def test_query_with_join(self):
        """Test that queries with joins are handled correctly."""
        query = """
            SELECT count(*) 
            FROM events e
            JOIN persons p ON e.person_id = p.id
            WHERE e.event = 'pageview'
        """
        result = self._print_optimized(query)

        # Should contain toDate conditions for the events table
        assert "toDate(" in result
        assert "timestamp" in result

    def test_query_with_subquery(self):
        """Test that subqueries are handled correctly."""
        query = """
            SELECT event, cnt FROM (
                SELECT event, count(*) as cnt 
                FROM events 
                WHERE event = 'pageview'
                GROUP BY event
            )
        """
        result = self._print_optimized(query)

        # Should contain toDate conditions in the subquery
        assert "toDate(timestamp)" in result

    def test_query_with_date_range_extraction(self):
        """Test that date ranges are correctly extracted from various conditions."""
        query = """
            SELECT count(*) FROM events 
            WHERE timestamp >= '2024-01-01 00:00:00' 
            AND timestamp < '2024-02-01 00:00:00'
            AND event = 'pageview'
        """
        result = self._print_optimized(query)

        # Should contain toDate conditions matching the extracted range
        assert "toDate(timestamp)" in result
        assert "2024-01-" in result or "2024-02-" in result

    def test_query_with_or_conditions(self):
        """Test that OR conditions are handled appropriately."""
        query = """
            SELECT count(*) FROM events 
            WHERE (event = 'pageview' OR event = 'click')
        """
        result = self._print_optimized(query)

        # Should still add toDate conditions
        assert "toDate(timestamp)" in result

    def test_query_with_now_function(self):
        """Test that queries using now() function are handled."""
        query = """
            SELECT count(*) FROM events 
            WHERE timestamp > now() - interval 7 day
            AND event = 'pageview'
        """
        result = self._print_optimized(query)

        # Should contain toDate conditions
        assert "toDate(timestamp)" in result

    def test_query_without_events_table(self):
        """Test that queries not using the events table are not modified."""
        query = "SELECT count(*) FROM persons WHERE properties.email = 'test@example.com'"
        result = self._print_optimized(query)

        # Should not contain toDate conditions
        assert "toDate(timestamp)" not in result

    def test_complex_query_with_multiple_conditions(self):
        """Test a complex query with multiple conditions."""
        query = """
            SELECT 
                event,
                count(*) as cnt,
                avg(properties.duration) as avg_duration
            FROM events
            WHERE 
                timestamp >= '2024-01-01'
                AND timestamp <= '2024-01-31 23:59:59'
                AND event IN ('pageview', 'click', 'submit')
                AND properties.page_url LIKE '%/dashboard%'
            GROUP BY event
            ORDER BY cnt DESC
            LIMIT 10
        """
        result = self._print_optimized(query)

        # Should contain toDate conditions based on the timestamp range
        assert "toDate(timestamp)" in result
        assert "toDate('2024-01-01')" in result
        assert "toDate('2024-01-31')" in result

    def test_query_with_cte(self):
        """Test that CTEs (Common Table Expressions) are handled."""
        query = """
            WITH daily_events AS (
                SELECT 
                    toDate(timestamp) as day,
                    count(*) as cnt
                FROM events
                WHERE event = 'pageview'
                GROUP BY day
            )
            SELECT * FROM daily_events
        """
        result = self._print_optimized(query)

        # The CTE already has toDate in SELECT, but should also have it in WHERE
        assert result.count("toDate(timestamp)") >= 2

    def test_default_date_range(self):
        """Test that the default date range (30 days) is applied when no conditions exist."""
        query = "SELECT count(*) FROM events"
        result = self._print_optimized(query)

        # Should contain toDate conditions with a reasonable default range
        assert "toDate(timestamp)" in result
        assert ">=" in result
        assert "<=" in result

        # The actual dates will depend on when the test runs,
        # but there should be date conditions
        assert "toDate(" in result

    def test_partial_date_conditions(self):
        """Test queries with only start or only end date conditions."""
        # Only start date
        query_start = "SELECT count(*) FROM events WHERE timestamp > '2024-01-15'"
        result_start = self._print_optimized(query_start)
        assert "toDate(timestamp)" in result_start
        assert "toDate('2024-01-15')" in result_start

        # Only end date
        query_end = "SELECT count(*) FROM events WHERE timestamp < '2024-02-15'"
        result_end = self._print_optimized(query_end)
        assert "toDate(timestamp)" in result_end
        assert "toDate('2024-02-15')" in result_end

    def test_nested_and_conditions(self):
        """Test nested AND conditions are handled correctly."""
        query = """
            SELECT count(*) FROM events 
            WHERE (
                (timestamp >= '2024-01-01' AND timestamp <= '2024-01-31')
                AND (event = 'pageview' AND properties.browser = 'Chrome')
            )
        """
        result = self._print_optimized(query)

        # Should extract date range and add toDate conditions
        assert "toDate(timestamp)" in result
        assert "2024-01" in result
