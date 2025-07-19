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

    @freeze_time("2020-01-01T12:00:00Z")
    def test_frequentist_zero_control_mean_fallback(self):
        """Test that frequentist method handles zero control mean by falling back to absolute difference"""
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

        # Create events where control group has zero sum
        # but test group has non-zero sum
        self.create_test_events_zero_control(feature_flag)

        flush_persons_and_events()

        query_runner = ExperimentQueryRunner(query=experiment_query, team=self.team)

        # This should not raise StatisticError
        result = cast(NewExperimentQueryResponse, query_runner.calculate())

        self.assertEqual(len(result.variant_results), 1)

        control_variant = result.baseline
        test_variant = result.variant_results[0]
        assert isinstance(test_variant, ExperimentVariantResultFrequentist)

        # Control should have zero sum
        self.assertEqual(control_variant.sum, 0)
        # Test variant should have non-zero sum
        self.assertGreater(test_variant.sum, 0)
        # Should have sample sizes
        self.assertGreater(control_variant.number_of_samples, 0)
        self.assertGreater(test_variant.number_of_samples, 0)
        # Should have computed confidence interval and p-value (using absolute difference)
        self.assertIsNotNone(test_variant.confidence_interval)
        self.assertIsNotNone(test_variant.p_value)

    def create_test_events_zero_control(self, feature_flag):
        """
        Creates test events where control group has zero sum (no amount values)
        but test group has non-zero sum. This tests the zero control mean scenario.
        """
        from posthog.test.base import _create_event, _create_person

        feature_flag_property = f"$feature/{feature_flag.key}"

        # Control variant: 10 users, all have purchase events but with amount=0 or no amount
        for i in range(10):
            _create_person(distinct_ids=[f"user_control_{i}"], team_id=self.team.pk)
            _create_event(
                team=self.team,
                event="$feature_flag_called",
                distinct_id=f"user_control_{i}",
                timestamp="2020-01-02T12:00:00Z",
                properties={
                    feature_flag_property: "control",
                    "$feature_flag_response": "control",
                    "$feature_flag": feature_flag.key,
                },
            )
            # Control purchases with zero amount (or missing amount)
            _create_event(
                team=self.team,
                event="purchase",
                distinct_id=f"user_control_{i}",
                timestamp="2020-01-02T12:01:00Z",
                properties={feature_flag_property: "control", "amount": 0},  # Zero amount!
            )

        # Test variant: 10 users, some have purchase events with positive amounts
        for i in range(10):
            _create_person(distinct_ids=[f"user_test_{i}"], team_id=self.team.pk)
            _create_event(
                team=self.team,
                event="$feature_flag_called",
                distinct_id=f"user_test_{i}",
                timestamp="2020-01-02T12:00:00Z",
                properties={
                    feature_flag_property: "test",
                    "$feature_flag_response": "test",
                    "$feature_flag": feature_flag.key,
                },
            )
            if i < 6:  # 6 out of 10 users make purchases
                _create_event(
                    team=self.team,
                    event="purchase",
                    distinct_id=f"user_test_{i}",
                    timestamp="2020-01-02T12:01:00Z",
                    properties={feature_flag_property: "test", "amount": 10},  # Positive amount
                )
