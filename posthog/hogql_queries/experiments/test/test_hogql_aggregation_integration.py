from posthog.test.base import BaseTest

from posthog.schema import EventsNode, ExperimentMeanMetric, ExperimentMetricMathType

from posthog.hogql import ast

from posthog.hogql_queries.experiments.base_query_utils import get_metric_aggregation_expr, get_metric_value
from posthog.hogql_queries.experiments.experiment_query_runner import ExperimentQueryRunner


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

    def test_experiment_query_runner_aggregation_expr_with_hogql(self):
        """Test that the experiment query runner creates the right aggregation expression for HogQL."""

        # Create a mock experiment and query runner
        from posthog.schema import ExperimentQuery

        from posthog.models import Experiment, FeatureFlag

        # Create feature flag and experiment
        feature_flag = FeatureFlag.objects.create(
            team=self.team,
            name="test-experiment",
            key="test-experiment",
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )

        experiment = Experiment.objects.create(
            team=self.team,
            name="Test Experiment",
            feature_flag=feature_flag,
        )

        # Test with sum aggregation
        metric_sum = ExperimentMeanMetric(
            source=EventsNode(
                event="revenue_event",
                math=ExperimentMetricMathType.HOGQL,
                math_hogql="sum(properties.revenue - properties.expense)",
            )
        )

        query_sum = ExperimentQuery(experiment_id=experiment.id, metric=metric_sum)
        runner_sum = ExperimentQueryRunner(query=query_sum, team=self.team)

        agg_expr_sum = get_metric_aggregation_expr(experiment, runner_sum.metric, runner_sum.team)

        # Should be a sum() call
        self.assertIsInstance(agg_expr_sum, ast.Call)
        self.assertEqual(agg_expr_sum.name, "sum")  # type: ignore[attr-defined]

        # Test with avg aggregation
        metric_avg = ExperimentMeanMetric(
            source=EventsNode(
                event="revenue_event", math=ExperimentMetricMathType.HOGQL, math_hogql="avg(properties.score)"
            )
        )

        query_avg = ExperimentQuery(experiment_id=experiment.id, metric=metric_avg)
        runner_avg = ExperimentQueryRunner(query=query_avg, team=self.team)

        agg_expr_avg = get_metric_aggregation_expr(experiment, runner_avg.metric, runner_avg.team)

        # Should be an avg() call
        self.assertIsInstance(agg_expr_avg, ast.Call)
        self.assertEqual(agg_expr_avg.name, "avg")  # type: ignore[attr-defined]

        # Test without aggregation (should default to sum)
        metric_no_agg = ExperimentMeanMetric(
            source=EventsNode(
                event="revenue_event", math=ExperimentMetricMathType.HOGQL, math_hogql="properties.revenue"
            )
        )

        query_no_agg = ExperimentQuery(experiment_id=experiment.id, metric=metric_no_agg)
        runner_no_agg = ExperimentQueryRunner(query=query_no_agg, team=self.team)

        agg_expr_no_agg = get_metric_aggregation_expr(experiment, runner_no_agg.metric, runner_no_agg.team)

        # Should default to sum()
        self.assertIsInstance(agg_expr_no_agg, ast.Call)
        self.assertEqual(agg_expr_no_agg.name, "sum")  # type: ignore[attr-defined]

    def test_hogql_aggregation_examples(self):
        """Test various HogQL aggregation examples that users might input."""

        from posthog.hogql_queries.experiments.hogql_aggregation_utils import extract_aggregation_and_inner_expr

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
                aggregation, inner_expr = extract_aggregation_and_inner_expr(expr_str)

                if expected_agg is None:
                    self.assertIsNone(aggregation, f"Expected no aggregation for: {expr_str}")
                else:
                    self.assertEqual(aggregation, expected_agg, f"Wrong aggregation for: {expr_str}")

                # Inner expression should never be None
                self.assertIsNotNone(inner_expr, f"Inner expression should not be None for: {expr_str}")
