from posthog.models.experiment import Experiment
from posthog.models.feature_flag.feature_flag import FeatureFlag
from posthog.schema import (
    EventsNode,
    ExperimentFunnelMetric,
    ExperimentQuery,
    ExperimentSignificanceCode,
    FunnelsQuery,
)
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    _create_event,
    _create_person,
    flush_persons_and_events,
)
from posthog.hogql_queries.experiments.experiment_query_runner import ExperimentQueryRunner
from freezegun import freeze_time
from django.utils import timezone
from datetime import timedelta


class TestFrequentistFunnelExperiments(ClickhouseTestMixin, APIBaseTest):
    def create_feature_flag(self, key="test-experiment"):
        return FeatureFlag.objects.create(
            name=f"Test experiment flag: {key}",
            key=key,
            team=self.team,
            filters={
                "groups": [{"properties": [], "rollout_percentage": None}],
                "multivariate": {
                    "variants": [
                        {
                            "key": "control",
                            "name": "Control",
                            "rollout_percentage": 50,
                        },
                        {
                            "key": "test",
                            "name": "Test",
                            "rollout_percentage": 50,
                        },
                    ]
                },
            },
            created_by=self.user,
        )

    def create_experiment(self, name="test-experiment", feature_flag=None, start_date=None, end_date=None):
        if feature_flag is None:
            feature_flag = self.create_feature_flag(name)
        if start_date is None:
            start_date = timezone.now()
        else:
            start_date = timezone.make_aware(start_date)  # Make naive datetime timezone-aware
        if end_date is None:
            end_date = timezone.now() + timedelta(days=14)
        elif end_date is not None:
            end_date = timezone.make_aware(end_date)  # Make naive datetime timezone-aware
        return Experiment.objects.create(
            name=name,
            team=self.team,
            feature_flag=feature_flag,
            start_date=start_date,
            end_date=end_date,
        )

    @freeze_time("2020-01-01T12:00:00Z")
    def test_frequentist_query_runner(self):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)

        feature_flag_property = f"$feature/{feature_flag.key}"

        funnels_query = FunnelsQuery(
            series=[EventsNode(event="$pageview"), EventsNode(event="purchase")],
            dateRange={"date_from": "2020-01-01", "date_to": "2020-01-14"},
        )

        experiment_metric = ExperimentFunnelMetric(
            series=funnels_query.series,
        )

        experiment_query = ExperimentQuery(
            experiment_id=experiment.id,
            kind="ExperimentQuery",
            metric=experiment_metric,
            stats_method="frequentist",  # Use frequentist method
        )

        # Create 10 users in each variant, with different conversion rates
        for variant, purchase_count in [("control", 6), ("test", 8)]:
            for i in range(10):
                _create_person(distinct_ids=[f"user_{variant}_{i}"], team_id=self.team.pk)
                # Create feature flag exposure event (required for experiments)
                _create_event(
                    team=self.team,
                    event="$feature_flag_called",
                    distinct_id=f"user_{variant}_{i}",
                    timestamp="2020-01-02T12:00:00Z",
                    properties={
                        "$feature_flag": feature_flag.key,
                        "$feature_flag_response": variant,
                        feature_flag_property: variant,
                    },
                )
                _create_event(
                    team=self.team,
                    event="$pageview",
                    distinct_id=f"user_{variant}_{i}",
                    timestamp="2020-01-02T12:01:00Z",
                    properties={feature_flag_property: variant},
                )
                if i < purchase_count:
                    _create_event(
                        team=self.team,
                        event="purchase",
                        distinct_id=f"user_{variant}_{i}",
                        timestamp="2020-01-02T12:02:00Z",
                        properties={feature_flag_property: variant},
                    )

        flush_persons_and_events()

        query_runner = ExperimentQueryRunner(query=experiment_query, team=self.team)
        result = query_runner.calculate()

        # Verify the stats method is frequentist
        self.assertEqual(query_runner.stats_method, "frequentist")

        # Check the variant counts
        self.assertEqual(len(result.variants), 2)

        control_variant = next(variant for variant in result.variants if variant.key == "control")
        test_variant = next(variant for variant in result.variants if variant.key == "test")

        self.assertEqual(control_variant.success_count, 6)
        self.assertEqual(control_variant.failure_count, 4)
        self.assertEqual(test_variant.success_count, 8)
        self.assertEqual(test_variant.failure_count, 2)

        # Check the probabilities are calculated using the frequentist method
        # The test variant has a higher conversion rate, so its probability should be higher
        self.assertGreaterEqual(result.probability["test"], result.probability["control"])

        # Check the confidence intervals are calculated
        self.assertTrue("control" in result.credible_intervals)
        self.assertTrue("test" in result.credible_intervals)

        # The frequentist implementation should provide significance code
        self.assertEqual(result.significance_code, ExperimentSignificanceCode.NOT_ENOUGH_EXPOSURE)

        # With such a small sample size, it shouldn't be deemed significant
        self.assertFalse(result.significant)

    @freeze_time("2020-01-01T12:00:00Z")
    def test_frequentist_vs_bayesian(self):
        """Compare frequentist and Bayesian results with the same data"""
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)

        feature_flag_property = f"$feature/{feature_flag.key}"

        funnels_query = FunnelsQuery(
            series=[EventsNode(event="$pageview"), EventsNode(event="purchase")],
            dateRange={"date_from": "2020-01-01", "date_to": "2020-01-14"},
        )

        experiment_metric = ExperimentFunnelMetric(
            series=funnels_query.series,
        )

        # For a significant difference, we need a larger sample size
        # Create 200 users in each variant with very different conversion rates
        for variant, purchase_count in [("control", 80), ("test", 120)]:
            for i in range(200):
                _create_person(distinct_ids=[f"user_{variant}_{i}"], team_id=self.team.pk)
                # Create feature flag exposure event (required for experiments)
                _create_event(
                    team=self.team,
                    event="$feature_flag_called",
                    distinct_id=f"user_{variant}_{i}",
                    timestamp="2020-01-02T12:00:00Z",
                    properties={
                        "$feature_flag": feature_flag.key,
                        "$feature_flag_response": variant,
                        feature_flag_property: variant,
                    },
                )
                _create_event(
                    team=self.team,
                    event="$pageview",
                    distinct_id=f"user_{variant}_{i}",
                    timestamp="2020-01-02T12:01:00Z",
                    properties={feature_flag_property: variant},
                )
                if i < purchase_count:
                    _create_event(
                        team=self.team,
                        event="purchase",
                        distinct_id=f"user_{variant}_{i}",
                        timestamp="2020-01-02T12:02:00Z",
                        properties={feature_flag_property: variant},
                    )

        flush_persons_and_events()

        # Run with frequentist method
        frequentist_query = ExperimentQuery(
            experiment_id=experiment.id,
            kind="ExperimentQuery",
            metric=experiment_metric,
            stats_method="frequentist",
        )
        frequentist_runner = ExperimentQueryRunner(query=frequentist_query, team=self.team)
        frequentist_result = frequentist_runner.calculate()

        # Run with Bayesian method
        bayesian_query = ExperimentQuery(
            experiment_id=experiment.id,
            kind="ExperimentQuery",
            metric=experiment_metric,
            stats_method="bayesian",
        )
        bayesian_runner = ExperimentQueryRunner(query=bayesian_query, team=self.team)
        bayesian_result = bayesian_runner.calculate()

        # Both methods should agree that test is better than control
        self.assertTrue(frequentist_result.probability["test"] >= frequentist_result.probability["control"])
        self.assertTrue(bayesian_result.probability["test"] >= bayesian_result.probability["control"])

        # Both should have confidence/credible intervals
        self.assertTrue("control" in frequentist_result.credible_intervals)
        self.assertTrue("test" in frequentist_result.credible_intervals)
        self.assertTrue("control" in bayesian_result.credible_intervals)
        self.assertTrue("test" in bayesian_result.credible_intervals)

        # With a large enough sample and difference, both should detect significance
        # Either both or neither should be significant (edge cases might disagree)
        self.assertEqual(frequentist_result.significant, bayesian_result.significant)
