from posthog.test.base import BaseTest

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr

from posthog.hogql_queries.experiments.hogql_aggregation_utils import (
    build_aggregation_call,
    extract_aggregation_and_inner_expr,
    is_aggregation_function,
)


class TestHogQLAggregationUtils(BaseTest):
    def test_is_aggregation_function(self):
        """Test that we can identify aggregation functions."""

        # Test aggregation functions
        self.assertTrue(is_aggregation_function("sum"))
        self.assertTrue(is_aggregation_function("avg"))
        self.assertTrue(is_aggregation_function("count"))
        self.assertTrue(is_aggregation_function("min"))
        self.assertTrue(is_aggregation_function("max"))

        # Test case insensitive
        self.assertTrue(is_aggregation_function("SUM"))
        self.assertTrue(is_aggregation_function("AVG"))
        self.assertTrue(is_aggregation_function("COUNT"))

        # Test non-aggregation functions
        self.assertFalse(is_aggregation_function("plus"))
        self.assertFalse(is_aggregation_function("minus"))
        self.assertFalse(is_aggregation_function("toFloat"))
        self.assertFalse(is_aggregation_function("toString"))
        self.assertFalse(is_aggregation_function("if"))

    def test_extract_aggregation_and_inner_expr_with_aggregation(self):
        """Test extracting aggregation function and inner expression."""

        # Test sum with arithmetic operation
        aggregation, inner_expr = extract_aggregation_and_inner_expr("sum(properties.revenue - properties.expense)")
        self.assertEqual(aggregation, "sum")
        self.assertIsInstance(inner_expr, ast.ArithmeticOperation)

        # Test avg with field
        aggregation, inner_expr = extract_aggregation_and_inner_expr("avg(properties.price)")
        self.assertEqual(aggregation, "avg")
        self.assertIsInstance(inner_expr, ast.Field)

        # Test count with no arguments
        aggregation, inner_expr = extract_aggregation_and_inner_expr("count()")
        self.assertEqual(aggregation, "count")
        self.assertIsInstance(inner_expr, ast.Constant)
        self.assertEqual(inner_expr.value, 1)  # type: ignore[attr-defined]

        # Test min with field
        aggregation, inner_expr = extract_aggregation_and_inner_expr("min(properties.score)")
        self.assertEqual(aggregation, "min")
        self.assertIsInstance(inner_expr, ast.Field)

        # Test max with field
        aggregation, inner_expr = extract_aggregation_and_inner_expr("max(properties.value)")
        self.assertEqual(aggregation, "max")
        self.assertIsInstance(inner_expr, ast.Field)

    def test_extract_aggregation_and_inner_expr_without_aggregation(self):
        """Test extracting from non-aggregation expressions."""

        # Test simple field
        aggregation, inner_expr = extract_aggregation_and_inner_expr("properties.revenue")
        self.assertIsNone(aggregation)
        self.assertIsInstance(inner_expr, ast.Field)

        # Test arithmetic operation
        aggregation, inner_expr = extract_aggregation_and_inner_expr("1 + 2")
        self.assertIsNone(aggregation)
        self.assertIsInstance(inner_expr, ast.ArithmeticOperation)

        # Test function call that's not an aggregation
        aggregation, inner_expr = extract_aggregation_and_inner_expr("toFloat(properties.value)")
        self.assertIsNone(aggregation)
        self.assertIsInstance(inner_expr, ast.Call)

    def test_extract_aggregation_and_inner_expr_with_ast_input(self):
        """Test that the function works with AST nodes as input."""

        # Parse expression first
        expr = parse_expr("sum(properties.revenue)")

        # Extract from AST
        aggregation, inner_expr = extract_aggregation_and_inner_expr(expr)
        self.assertEqual(aggregation, "sum")
        self.assertIsInstance(inner_expr, ast.Field)

    def test_build_aggregation_call(self):
        """Test building aggregation calls."""

        inner_expr = parse_expr("properties.revenue - properties.expense")

        # Test building a sum aggregation
        agg_call = build_aggregation_call("sum", inner_expr)

        self.assertIsInstance(agg_call, ast.Call)
        self.assertEqual(agg_call.name, "sum")
        self.assertEqual(len(agg_call.args), 1)
        self.assertEqual(agg_call.args[0], inner_expr)
        self.assertFalse(agg_call.distinct)

        # Test building with distinct
        agg_call_distinct = build_aggregation_call("count", inner_expr, distinct=True)
        self.assertTrue(agg_call_distinct.distinct)
