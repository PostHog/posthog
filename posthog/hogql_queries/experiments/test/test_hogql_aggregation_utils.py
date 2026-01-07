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
        assert is_aggregation_function("sum")
        assert is_aggregation_function("avg")
        assert is_aggregation_function("count")
        assert is_aggregation_function("min")
        assert is_aggregation_function("max")

        # Test case insensitive
        assert is_aggregation_function("SUM")
        assert is_aggregation_function("AVG")
        assert is_aggregation_function("COUNT")

        # Test non-aggregation functions
        assert not is_aggregation_function("plus")
        assert not is_aggregation_function("minus")
        assert not is_aggregation_function("toFloat")
        assert not is_aggregation_function("toString")
        assert not is_aggregation_function("if")

    def test_extract_aggregation_and_inner_expr_with_aggregation(self):
        """Test extracting aggregation function and inner expression."""

        # Test sum with arithmetic operation
        aggregation, inner_expr, params = extract_aggregation_and_inner_expr(
            "sum(properties.revenue - properties.expense)"
        )
        assert aggregation == "sum"
        assert isinstance(inner_expr, ast.ArithmeticOperation)
        assert params is None  # Non-parametric aggregation

        # Test avg with field
        aggregation, inner_expr, params = extract_aggregation_and_inner_expr("avg(properties.price)")
        assert aggregation == "avg"
        assert isinstance(inner_expr, ast.Field)
        assert params is None

        # Test count with no arguments
        aggregation, inner_expr, params = extract_aggregation_and_inner_expr("count()")
        assert aggregation == "count"
        assert isinstance(inner_expr, ast.Constant)
        assert inner_expr.value == 1  # type: ignore[attr-defined]
        assert params is None

        # Test min with field
        aggregation, inner_expr, params = extract_aggregation_and_inner_expr("min(properties.score)")
        assert aggregation == "min"
        assert isinstance(inner_expr, ast.Field)
        assert params is None

        # Test max with field
        aggregation, inner_expr, params = extract_aggregation_and_inner_expr("max(properties.value)")
        assert aggregation == "max"
        assert isinstance(inner_expr, ast.Field)
        assert params is None

    def test_extract_aggregation_and_inner_expr_without_aggregation(self):
        """Test extracting from non-aggregation expressions."""

        # Test simple field
        aggregation, inner_expr, params = extract_aggregation_and_inner_expr("properties.revenue")
        assert aggregation is None
        assert isinstance(inner_expr, ast.Field)
        assert params is None

        # Test arithmetic operation
        aggregation, inner_expr, params = extract_aggregation_and_inner_expr("1 + 2")
        assert aggregation is None
        assert isinstance(inner_expr, ast.ArithmeticOperation)
        assert params is None

        # Test function call that's not an aggregation
        aggregation, inner_expr, params = extract_aggregation_and_inner_expr("toFloat(properties.value)")
        assert aggregation is None
        assert isinstance(inner_expr, ast.Call)
        assert params is None

    def test_extract_aggregation_and_inner_expr_with_ast_input(self):
        """Test that the function works with AST nodes as input."""

        # Parse expression first
        expr = parse_expr("sum(properties.revenue)")

        # Extract from AST
        aggregation, inner_expr, params = extract_aggregation_and_inner_expr(expr)
        assert aggregation == "sum"
        assert isinstance(inner_expr, ast.Field)
        assert params is None

    def test_build_aggregation_call(self):
        """Test building aggregation calls."""

        inner_expr = parse_expr("properties.revenue - properties.expense")

        # Test building a sum aggregation
        agg_call = build_aggregation_call("sum", inner_expr)

        assert isinstance(agg_call, ast.Call)
        assert agg_call.name == "sum"
        assert len(agg_call.args) == 1
        assert agg_call.args[0] == inner_expr
        assert not agg_call.distinct

        # Test building with distinct
        agg_call_distinct = build_aggregation_call("count", inner_expr, distinct=True)
        assert agg_call_distinct.distinct

    def test_extract_aggregation_with_params(self):
        """Test that parametric aggregations preserve their parameters."""

        # Test quantile with single parameter
        agg, inner, params = extract_aggregation_and_inner_expr("quantile(0.90)(properties.margin)")
        assert agg == "quantile"
        assert isinstance(inner, ast.Field)
        assert params is not None
        assert params is not None  # for mypy
        assert len(params) == 1
        assert isinstance(params[0], ast.Constant)
        assert isinstance(params[0], ast.Constant)  # for mypy
        assert params[0].value == 0.9

        # Test quantile with different level
        agg, inner, params = extract_aggregation_and_inner_expr("quantile(0.50)(properties.value)")
        assert agg == "quantile"
        assert params is not None
        assert params is not None  # for mypy
        assert isinstance(params[0], ast.Constant)  # for mypy
        assert params[0].value == 0.5

        # Test non-parametric aggregation returns None for params
        agg, inner, params = extract_aggregation_and_inner_expr("sum(properties.revenue)")
        assert agg == "sum"
        assert params is None

    def test_build_aggregation_call_with_params(self):
        """Test that build_aggregation_call handles parametric functions."""

        inner_expr = parse_expr("properties.value")
        params: list[ast.Expr] = [ast.Constant(value=0.90)]

        # Build quantile with parameter
        result = build_aggregation_call("quantile", inner_expr, params=params)

        # Should produce: quantile(0.90)(properties.value)
        assert isinstance(result, ast.Call)
        assert result.name == "quantile"
        assert result.params is not None
        assert result.params is not None  # for mypy
        assert len(result.params) == 1
        assert isinstance(result.params[0], ast.Constant)  # for mypy
        assert result.params[0].value == 0.9
        assert result.args[0] == inner_expr

        # Test building without params (non-parametric aggregation)
        result_no_params = build_aggregation_call("sum", inner_expr, params=None)
        assert isinstance(result_no_params, ast.Call)
        assert result_no_params.name == "sum"
        assert result_no_params.params is None
