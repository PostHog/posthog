from django.test import override_settings
from posthog.hogql_queries.experiments.experiment_query_runner import ExperimentQueryRunner
from posthog.hogql_queries.experiments.test.experiment_query_runner.base import ExperimentQueryRunnerBaseTest
from posthog.schema import (
    EventsNode,
    ExperimentMetricMathType,
    ExperimentMetricResult,
    ExperimentQuery,
    ExperimentMeanMetric,
)
from posthog.test.base import (
    flush_persons_and_events,
    snapshot_clickhouse_queries,
)
from freezegun import freeze_time


@override_settings(IN_UNIT_TESTING=True)
class TestFrequentistMethod(ExperimentQueryRunnerBaseTest):
    @freeze_time("2020-01-01T12:00:00Z")
    @snapshot_clickhouse_queries
    def test_frequentist_property_sum_metric(self):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)
        experiment.stats_config = {"version": 2, "method": "frequentist"}
        experiment.save()

        metric = ExperimentMeanMetric(
            source=EventsNode(
                event="purchase",
                math=ExperimentMetricMathType.SUM,
                math_property="amount",
            ),
        )

        experiment_query = ExperimentQuery(
            experiment_id=experiment.id,
            kind="ExperimentQuery",
            metric=metric,
        )

        experiment.metrics = [metric.model_dump(mode="json")]
        experiment.save()

        self.create_standard_test_events(feature_flag)

        flush_persons_and_events()

        query_runner = ExperimentQueryRunner(query=experiment_query, team=self.team)

        result = query_runner.calculate()
        assert isinstance(result, ExperimentMetricResult)

        self.assertEqual(len(result.variants), 1)

        control_variant = result.baseline
        test_variant = result.variants[0]

        self.assertEqual(control_variant.sum, 20)
        self.assertEqual(test_variant.sum, 20)
        self.assertEqual(control_variant.number_of_samples, 10)
        self.assertEqual(test_variant.number_of_samples, 10)
