from posthog.test.base import BaseTest

from posthog.schema import EventsNode, ExperimentMeanMetric, ExperimentMetricMathType

from posthog.hogql import ast

from posthog.hogql_queries.experiments.base_query_utils import get_metric_value
from posthog.hogql_queries.experiments.hogql_aggregation_utils import extract_aggregation_and_inner_expr


class TestHogQLAggregationIntegration(BaseTest):
    def test_get_metric_value_with_hogql_aggregation(self):
        """Test that get_metric_value correctly extracts inner expressions from HogQL aggregations."""

        # Test with aggregation function
        metric_with_agg = ExperimentMeanMetric(
            source=EventsNode(
                event="revenue_event",
                math=ExperimentMetricMathType.HOGQL,
                math_hogql="sum(properties.revenue - properties.expense)",
            )
        )

        result = get_metric_value(metric_with_agg)

        # Should return the inner expression (ArithmeticOperation), not the full sum() call
        self.assertIsInstance(result, ast.ArithmeticOperation)
        self.assertEqual(result.op, ast.ArithmeticOperationOp.Sub)  # type: ignore[attr-defined]

        # Test without aggregation function
        metric_without_agg = ExperimentMeanMetric(
            source=EventsNode(
                event="revenue_event", math=ExperimentMetricMathType.HOGQL, math_hogql="properties.revenue"
            )
        )

        result_no_agg = get_metric_value(metric_without_agg)

        # Should return the field expression directly
        self.assertIsInstance(result_no_agg, ast.Field)
        self.assertEqual(result_no_agg.chain, ["properties", "revenue"])  # type: ignore[attr-defined]

    def test_hogql_aggregation_examples(self):
        """Test various HogQL aggregation examples that users might input."""

        test_cases = [
            # (input_expression, expected_aggregation, description)
            ("sum(properties.revenue - properties.expense)", "sum", "Revenue minus expense"),
            ("avg(properties.price * properties.quantity)", "avg", "Average of price times quantity"),
            ("count(distinct properties.user_id)", "count", "Distinct user count"),
            ("min(properties.score)", "min", "Minimum score"),
            ("max(toFloat(properties.value))", "max", "Maximum converted value"),
            ("properties.simple_value", None, "Simple property access"),
            ("properties.a + properties.b", None, "Simple arithmetic"),
        ]

        for expr_str, expected_agg, description in test_cases:
            with self.subTest(expression=expr_str, description=description):
                aggregation, inner_expr, _ = extract_aggregation_and_inner_expr(expr_str)

                if expected_agg is None:
                    self.assertIsNone(aggregation, f"Expected no aggregation for: {expr_str}")
                else:
                    self.assertEqual(aggregation, expected_agg, f"Wrong aggregation for: {expr_str}")

                # Inner expression should never be None
                self.assertIsNotNone(inner_expr, f"Inner expression should not be None for: {expr_str}")
