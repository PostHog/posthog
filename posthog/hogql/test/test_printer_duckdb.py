from typing import cast

from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.errors import ExposedHogQLError
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.printer import prepare_and_print_ast, prepare_ast_for_printing, print_prepared_ast


class TestPrinterDuckDB(BaseTest):
    """Test the HogQL printer with DuckDB dialect."""

    maxDiff = None

    def _expr(
        self,
        query: str,
        context: HogQLContext | None = None,
    ) -> str:
        """Translate HogQL expression to DuckDB SQL."""
        node = parse_expr(query)
        context = context or HogQLContext(team_id=self.team.pk, enable_select_queries=True)
        select_query = ast.SelectQuery(select=[node], select_from=ast.JoinExpr(table=ast.Field(chain=["events"])))
        prepared_select_query: ast.SelectQuery = cast(
            ast.SelectQuery,
            prepare_ast_for_printing(select_query, context=context, dialect="duckdb", stack=[select_query]),
        )
        return print_prepared_ast(
            prepared_select_query.select[0],
            context=context,
            dialect="duckdb",
            stack=[prepared_select_query],
        )

    def _select(
        self,
        query: str,
        context: HogQLContext | None = None,
        placeholders: dict[str, ast.Expr] | None = None,
    ) -> str:
        """Translate HogQL SELECT query to DuckDB SQL."""
        return prepare_and_print_ast(
            parse_select(query, placeholders=placeholders),
            context or HogQLContext(team_id=self.team.pk, enable_select_queries=True),
            "duckdb",
        )[0]

    def _assert_expr_error(self, expr: str, expected_error: str):
        """Assert that expression raises an error containing expected_error."""
        with self.assertRaises(ExposedHogQLError) as context:
            self._expr(expr)
        self.assertIn(expected_error, str(context.exception))

    def _assert_select_error(self, statement: str, expected_error: str):
        """Assert that SELECT statement raises an error containing expected_error."""
        with self.assertRaises(ExposedHogQLError) as context:
            self._select(statement)
        self.assertIn(expected_error, str(context.exception))

    # Arithmetic operations - DuckDB uses standard SQL operators
    @parameterized.expand(
        [
            ("1 + 2", "(1 + 2)"),
            ("3 - 1", "(3 - 1)"),
            ("2 * 3", "(2 * 3)"),
            ("6 / 2", "(6 / 2)"),
            ("7 % 3", "(7 % 3)"),
            ("1 + 2 * 3", "(1 + (2 * 3))"),
            ("(1 + 2) * 3", "((1 + 2) * 3)"),
        ]
    )
    def test_arithmetic_operators(self, hogql: str, expected: str):
        self.assertEqual(self._expr(hogql), expected)

    # Boolean operations - DuckDB uses standard SQL operators
    @parameterized.expand(
        [
            ("true and false", "(true AND false)"),
            ("true or false", "(true OR false)"),
            ("not true", "(NOT true)"),
            ("true and true and false", "(true AND true AND false)"),
            ("true or true or false", "(true OR true OR false)"),
        ]
    )
    def test_boolean_operators(self, hogql: str, expected: str):
        self.assertEqual(self._expr(hogql), expected)

    # Comparison operations - DuckDB uses standard SQL operators
    @parameterized.expand(
        [
            ("1 = 2", "(1 = 2)"),
            ("1 != 2", "(1 != 2)"),
            ("1 < 2", "(1 < 2)"),
            ("1 <= 2", "(1 <= 2)"),
            ("1 > 2", "(1 > 2)"),
            ("1 >= 2", "(1 >= 2)"),
            ("'a' LIKE 'b'", "('a' LIKE 'b')"),
            ("'a' ILIKE 'b'", "('a' ILIKE 'b')"),
            ("'a' NOT LIKE 'b'", "('a' NOT LIKE 'b')"),
            ("'a' NOT ILIKE 'b'", "('a' NOT ILIKE 'b')"),
            ("1 IN (1, 2, 3)", "(1 IN tuple(1, 2, 3))"),
            ("1 NOT IN (1, 2, 3)", "(1 NOT IN tuple(1, 2, 3))"),
        ]
    )
    def test_comparison_operators(self, hogql: str, expected: str):
        self.assertEqual(self._expr(hogql), expected)

    # Regex operations
    @parameterized.expand(
        [
            ("'abc' =~ 'a.*'", "REGEXP_MATCHES('abc', 'a.*')"),
            ("'abc' !~ 'a.*'", "(NOT REGEXP_MATCHES('abc', 'a.*'))"),
            ("'abc' =~* 'A.*'", "REGEXP_MATCHES('abc', '(?i)' || 'A.*')"),
            ("'abc' !~* 'A.*'", "(NOT REGEXP_MATCHES('abc', '(?i)' || 'A.*'))"),
        ]
    )
    def test_regex_operators(self, hogql: str, expected: str):
        self.assertEqual(self._expr(hogql), expected)

    # Constants
    @parameterized.expand(
        [
            ("true", "true"),
            ("false", "false"),
            ("null", "NULL"),
            ("123", "123"),
            ("12.34", "12.34"),
            ("'hello'", "'hello'"),
        ]
    )
    def test_constants(self, hogql: str, expected: str):
        self.assertEqual(self._expr(hogql), expected)

    # Between expression
    def test_between(self):
        self.assertEqual(self._expr("1 BETWEEN 0 AND 10"), "1 BETWEEN 0 AND 10")
        self.assertEqual(self._expr("1 NOT BETWEEN 0 AND 10"), "1 NOT BETWEEN 0 AND 10")

    # Functions - verify DuckDB mappings
    @parameterized.expand(
        [
            ("length('hello')", "LENGTH('hello')"),
            ("lower('HELLO')", "LOWER('HELLO')"),
            ("upper('hello')", "UPPER('hello')"),
            ("trim(' hello ')", "TRIM(' hello ')"),
            ("coalesce(null, 'a', 'b')", "COALESCE(NULL, 'a', 'b')"),
            ("if(true, 'a', 'b')", "IF(true, 'a', 'b')"),
            ("nullif('a', 'b')", "NULLIF('a', 'b')"),
            ("concat('a', 'b', 'c')", "CONCAT('a', 'b', 'c')"),
            ("substring('hello', 1, 3)", "SUBSTRING('hello', 1, 3)"),
            ("abs(-5)", "ABS(-5)"),
            ("round(3.14159, 2)", "ROUND(3.14159, 2)"),
            ("floor(3.7)", "FLOOR(3.7)"),
            ("ceil(3.2)", "CEIL(3.2)"),
        ]
    )
    def test_functions(self, hogql: str, expected: str):
        self.assertEqual(self._expr(hogql), expected)

    # Test type conversion functions map to DuckDB CAST
    @parameterized.expand(
        [
            ("toString(123)", "CAST(123 AS VARCHAR)"),
            ("toInt32('123')", "CAST('123' AS INTEGER)"),
            ("toFloat64('3.14')", "CAST('3.14' AS DOUBLE)"),
        ]
    )
    def test_type_conversion_functions(self, hogql: str, expected: str):
        self.assertEqual(self._expr(hogql), expected)

    # Aggregation functions - DuckDB uppercases function names
    @parameterized.expand(
        [
            ("count()", "COUNT()"),
            ("sum(1)", "SUM(1)"),
            ("avg(1)", "AVG(1)"),
            ("min(1)", "MIN(1)"),
            ("max(1)", "MAX(1)"),
        ]
    )
    def test_aggregation_functions(self, hogql: str, expected: str):
        self.assertEqual(self._expr(hogql), expected)

    # SELECT queries
    def test_select_simple(self):
        result = self._select("SELECT 1, 2, 3")
        # Result may include LIMIT from limit_top_select
        self.assertTrue(result.startswith("SELECT 1, 2, 3"))

    def test_select_from_table(self):
        result = self._select("SELECT event FROM events")
        self.assertIn("SELECT", result)
        self.assertIn("events", result)

    def test_select_with_where(self):
        result = self._select("SELECT event FROM events WHERE event = 'test'")
        self.assertIn("WHERE", result)
        self.assertIn("=", result)  # DuckDB uses = not equals()

    def test_select_with_group_by(self):
        result = self._select("SELECT event, count() FROM events GROUP BY event")
        self.assertIn("GROUP BY", result)

    def test_select_with_order_by(self):
        result = self._select("SELECT event FROM events ORDER BY event ASC")
        self.assertIn("ORDER BY", result)

    def test_select_with_limit(self):
        result = self._select("SELECT event FROM events LIMIT 10")
        self.assertIn("LIMIT", result)

    # Unsupported features should raise errors
    def test_array_join_not_supported(self):
        self._assert_select_error(
            "SELECT x FROM events ARRAY JOIN [1, 2, 3] AS x", "ARRAY JOIN is not supported in DuckDB"
        )

    def test_sample_not_supported(self):
        self._assert_select_error("SELECT event FROM events SAMPLE 0.1", "SAMPLE is not supported in DuckDB")

    def test_limit_by_not_supported(self):
        self._assert_select_error("SELECT event FROM events LIMIT 1 BY event", "LIMIT BY is not supported in DuckDB")

    def test_in_cohort_not_supported(self):
        self._assert_expr_error("person_id IN COHORT 1", "IN COHORT is not supported in DuckDB")

    # No team_id guard for DuckDB
    def test_no_team_id_guard(self):
        result = self._select("SELECT event FROM events")
        # DuckDB queries should not have team_id filter
        self.assertNotIn("team_id", result.lower())

    # Identifier escaping - DuckDB uses double quotes
    def test_identifier_with_spaces(self):
        # Test that identifiers with special characters are properly quoted
        result = self._expr("1 as `my column`")
        self.assertIn('"my column"', result)  # DuckDB uses double quotes


class TestPrinterDuckDBIntegration(BaseTest):
    """Integration tests for DuckDB dialect with more complex queries."""

    def _select(
        self,
        query: str,
        context: HogQLContext | None = None,
    ) -> str:
        return prepare_and_print_ast(
            parse_select(query),
            context or HogQLContext(team_id=self.team.pk, enable_select_queries=True),
            "duckdb",
        )[0]

    def test_subquery(self):
        result = self._select("SELECT count() FROM (SELECT event FROM events WHERE event = 'test')")
        self.assertIn("SELECT", result)
        self.assertIn("COUNT()", result)  # DuckDB uses uppercase function names

    def test_join(self):
        result = self._select("SELECT e.event FROM events e LEFT JOIN persons p ON e.person_id = p.id")
        self.assertIn("LEFT JOIN", result)

    def test_union(self):
        result = self._select(
            "SELECT event FROM events WHERE event = 'a' UNION ALL SELECT event FROM events WHERE event = 'b'"
        )
        self.assertIn("UNION ALL", result)

    def test_window_function(self):
        result = self._select("SELECT event, row_number() OVER (PARTITION BY event ORDER BY timestamp) FROM events")
        self.assertIn("OVER", result)
        self.assertIn("PARTITION BY", result)
