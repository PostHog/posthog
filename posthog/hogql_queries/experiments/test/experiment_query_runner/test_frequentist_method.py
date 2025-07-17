from typing import cast

from django.test import override_settings
from freezegun import freeze_time

from posthog.hogql_queries.experiments.experiment_query_runner import (
    ExperimentQueryRunner,
)
from posthog.hogql_queries.experiments.test.experiment_query_runner.base import (
    ExperimentQueryRunnerBaseTest,
)
from posthog.schema import (
    EventsNode,
    ExperimentMeanMetric,
    ExperimentMetricMathType,
    ExperimentQuery,
    ExperimentVariantResultFrequentist,
    NewExperimentQueryResponse,
)
from posthog.test.base import (
    flush_persons_and_events,
    snapshot_clickhouse_queries,
)


@override_settings(IN_UNIT_TESTING=True)
class TestFrequentistMethod(ExperimentQueryRunnerBaseTest):
    @freeze_time("2020-01-01T12:00:00Z")
    @snapshot_clickhouse_queries
    def test_frequentist_property_sum_metric(self):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)
        experiment.stats_config = {"method": "frequentist"}
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

        result = cast(NewExperimentQueryResponse, query_runner.calculate())

        self.assertEqual(len(result.variant_results), 1)

        control_variant = result.baseline
        test_variant = result.variant_results[0]
        assert isinstance(test_variant, ExperimentVariantResultFrequentist)

        self.assertEqual(control_variant.sum, 20)
        self.assertEqual(test_variant.sum, 20)
        self.assertEqual(control_variant.number_of_samples, 10)
        self.assertEqual(test_variant.number_of_samples, 10)
        self.assertEqual(test_variant.confidence_interval, [-1.9807682951982126, 1.9807682951982126])
        self.assertFalse(test_variant.significant)
        self.assertEqual(test_variant.p_value, 1.0)
