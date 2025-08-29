from posthog.test.base import BaseTest

from posthog.schema import HogQLQueryModifiers

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import create_hogql_database
from posthog.hogql.modifiers import create_default_modifiers_for_team
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import print_ast
from posthog.hogql.transforms.timestamp_condition import optimize_timestamp_conditions


class TestTimestampConditionOptimizer(BaseTest):
    def setUp(self):
        super().setUp()
        modifiers = create_default_modifiers_for_team(self.team, HogQLQueryModifiers(optimizeTimestampConditions=False))
        self.context = HogQLContext(
            team_id=self.team.pk,
            enable_select_queries=True,
            modifiers=modifiers,
        )
        self.context.database = create_hogql_database(self.team.pk)

    def _parse_and_optimize(self, query: str) -> ast.SelectQuery:
        """Parse a query and apply timestamp optimization."""
        parsed = parse_select(query)
        optimize_timestamp_conditions(parsed, self.context)
        return parsed

    def _print_optimized(self, query: str) -> str:
        """Parse, optimize, and print the query."""
        optimized = self._parse_and_optimize(query)
        return print_ast(optimized, self.context, dialect="clickhouse", pretty=False)

    def test_simple_query_without_timestamp_conditions(self):
        """Test that a simple query without timestamp conditions is not modified."""
        query = "SELECT count(*) FROM events WHERE event = 'pageview'"
        result = self._print_optimized(query)

        # Should not contain toDate conditions since there are no timestamp conditions
        assert "toDate(timestamp)" not in result

    def test_query_with_existing_timestamp_condition(self):
        """Test that timestamp conditions get corresponding toDate conditions added."""
        query = "SELECT count(*) FROM events WHERE timestamp > '2024-01-01' AND event = 'pageview'"
        result = self._print_optimized(query)

        # Should contain both the original timestamp condition and the added toDate condition
        # The output uses SQL parameter placeholders and functions like greater() and toDate()
        assert "greater(toTimeZone(events.timestamp" in result
        assert "greaterOrEquals(toDate(toTimeZone(events.timestamp" in result

    def test_query_with_existing_todate_condition(self):
        """Test that queries with existing toDate conditions don't get duplicated."""
        query = """
                SELECT count(*)
                FROM events
                WHERE toDate(timestamp) >= toDate('2024-01-01')
                  AND toDate(timestamp) <= toDate('2024-01-31')
                  AND event = 'pageview' \
                """
        result = self._print_optimized(query)

        # Count occurrences of toDate - should be exactly 2 (the original ones)
        # No new toDate conditions should be added since these are already toDate conditions
        todate_count = result.count("toDate(toTimeZone(events.timestamp")
        assert todate_count == 2

    def test_query_with_table_alias(self):
        """Test that queries with table aliases work correctly when no timestamp conditions exist."""
        query = "SELECT count(*) FROM events e WHERE e.event = 'pageview'"
        result = self._print_optimized(query)

        # Should not contain toDate conditions since there are no timestamp conditions
        assert "toDate(" not in result

    def test_query_with_join(self):
        """Test that queries with joins are handled correctly."""
        query = """
                SELECT count(*)
                FROM events e
                         JOIN persons p ON e.person_id = p.id
                WHERE e.event = 'pageview' \
                """
        result = self._print_optimized(query)

        # Should not contain toDate conditions since there are no timestamp conditions
        assert "toDate(" not in result

    def test_query_with_subquery(self):
        """Test that subqueries are handled correctly."""
        query = """
                SELECT event, cnt
                FROM (SELECT event, count(*) as cnt
                      FROM events
                      WHERE event = 'pageview'
                      GROUP BY event) \
                """
        result = self._print_optimized(query)

        # Should not contain toDate conditions since there are no timestamp conditions in the subquery
        assert "toDate(" not in result

    def test_query_with_date_range_extraction(self):
        """Test that date ranges are correctly extracted from various conditions."""
        query = """
                SELECT count(*)
                FROM events
                WHERE timestamp >= '2024-01-01 00:00:00'
                  AND timestamp
                    < '2024-02-01 00:00:00'
                  AND event = 'pageview' \
                """
        result = self._print_optimized(query)

        # Should contain toDate conditions matching the extracted range
        assert "toDate(toTimeZone(events.timestamp" in result
        # Should have two conditions for both >= and <
        assert result.count("toDate(toTimeZone(events.timestamp") >= 2

    def test_query_with_or_conditions(self):
        """Test that OR conditions are handled appropriately."""
        query = """
                SELECT count(*)
                FROM events
                WHERE (event = 'pageview' OR event = 'click') \
                """
        result = self._print_optimized(query)

        # Should not add toDate conditions since there are no timestamp conditions
        assert "toDate(" not in result

    def test_query_with_now_function(self):
        """Test that queries using now() function are handled."""
        query = """
                SELECT count(*)
                FROM events
                WHERE timestamp
                    > now() - interval 7 day
                  AND event = 'pageview' \
                """
        result = self._print_optimized(query)

        # Should not contain toDate conditions since the interval syntax isn't handled yet
        # This would need more sophisticated parsing to extract timestamp conditions
        assert "toDate(" not in result

    def test_query_without_events_table(self):
        """Test that queries not using the events table are not modified."""
        query = "SELECT count(*) FROM persons WHERE properties.email = 'test@example.com'"
        result = self._print_optimized(query)

        # Should not contain toDate conditions since this isn't an events table query
        assert "toDate(" not in result

    def test_complex_query_with_multiple_conditions(self):
        """Test a complex query with multiple conditions."""
        query = """
                SELECT event,
                       count(*)                 as cnt,
                       avg(properties.duration) as avg_duration
                FROM events
                WHERE
                    timestamp >= '2024-01-01'
                  AND timestamp <= '2024-01-31 23:59:59'
                  AND event IN ('pageview'
                    , 'click'
                    , 'submit')
                  AND properties.page_url LIKE '%/dashboard%'
                GROUP BY event
                ORDER BY cnt DESC
                    LIMIT 10 \
                """
        result = self._print_optimized(query)

        # Should contain toDate conditions based on the timestamp range
        assert "toDate(toTimeZone(events.timestamp" in result
        # There should be two toDate conditions (for >= and <=)
        assert result.count("toDate(toTimeZone(events.timestamp") >= 2

    def test_query_with_cte(self):
        """Test that CTEs (Common Table Expressions) are handled."""
        query = """
                WITH daily_events AS (SELECT toDate(timestamp) as day, count (*) as cnt
                FROM events
                WHERE event = 'pageview'
                GROUP BY day
                    )
                SELECT *
                FROM daily_events \
                """
        result = self._print_optimized(query)

        # Should not add toDate conditions to the CTE since there are no timestamp conditions in WHERE
        # The toDate in SELECT is different - it's for grouping, not filtering
        assert "toDate(" in result  # The one in SELECT should still be there

    def test_query_without_any_conditions(self):
        """Test that queries without any conditions are not modified."""
        query = "SELECT count(*) FROM events"
        result = self._print_optimized(query)

        # Should not contain toDate conditions since there are no timestamp conditions
        assert "toDate(timestamp)" not in result

    def test_partial_date_conditions(self):
        """Test queries with only start or only end date conditions."""
        # Only start date
        query_start = "SELECT count(*) FROM events WHERE timestamp > '2024-01-15'"
        result_start = self._print_optimized(query_start)
        assert "toDate(toTimeZone(events.timestamp" in result_start
        assert "greaterOrEquals(toDate(toTimeZone(events.timestamp" in result_start

        # Only end date
        query_end = "SELECT count(*) FROM events WHERE timestamp < '2024-02-15'"
        result_end = self._print_optimized(query_end)
        assert "toDate(toTimeZone(events.timestamp" in result_end
        assert "lessOrEquals(toDate(toTimeZone(events.timestamp" in result_end

    def test_nested_and_conditions(self):
        """Test nested AND conditions are handled correctly."""
        query = """
                SELECT count(*)
                FROM events
                WHERE (
                          (timestamp >= '2024-01-01' AND timestamp <= '2024-01-31')
                              AND (event = 'pageview' AND properties.browser = 'Chrome')
                          ) \
                """
        result = self._print_optimized(query)

        # Should extract date range and add toDate conditions
        assert "toDate(toTimeZone(events.timestamp" in result
        # Should have two toDate conditions for the nested timestamp conditions
        assert result.count("toDate(toTimeZone(events.timestamp") >= 2
