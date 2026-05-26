from freezegun import freeze_time

from django.test import override_settings

from posthog.schema import EventsNode, ExperimentMeanMetric, ExperimentMetricMathType, ExperimentQuery

from posthog.hogql_queries.experiments.experiment_metric_fingerprint import compute_metric_fingerprint
from posthog.hogql_queries.experiments.experiment_query_runner import ExperimentQueryRunner
from posthog.hogql_queries.experiments.test.experiment_query_runner.base import ExperimentQueryRunnerBaseTest

from products.experiments.backend.models.experiment import ExperimentHoldout


@override_settings(IN_UNIT_TESTING=True)
class TestExcludedVariants(ExperimentQueryRunnerBaseTest):
    @freeze_time("2020-01-01T12:00:00Z")
    def test_excluded_variant_dropped_from_runner_variants(self):
        # Set up a feature flag with 3 variants: control, test, test-2
        feature_flag = self.create_feature_flag(key="multi-variant-exclusion-test")
        feature_flag.filters["multivariate"]["variants"].append(
            {"key": "test-2", "name": "Test 2", "rollout_percentage": 33}
        )
        feature_flag.save()

        experiment = self.create_experiment(feature_flag=feature_flag)

        # Exclude 'test-2'
        experiment.parameters = {"excluded_variants": ["test-2"]}
        experiment.save()

        metric = ExperimentMeanMetric(
            source=EventsNode(event="purchase", math=ExperimentMetricMathType.TOTAL),
        )
        query = ExperimentQuery(experiment_id=experiment.id, kind="ExperimentQuery", metric=metric)
        runner = ExperimentQueryRunner(query=query, team=self.team)

        assert "test-2" not in runner.variants
        assert "control" in runner.variants
        assert "test" in runner.variants

    @freeze_time("2020-01-01T12:00:00Z")
    def test_no_exclusions_leaves_variants_unchanged(self):
        feature_flag = self.create_feature_flag(key="no-exclusion-test")
        experiment = self.create_experiment(feature_flag=feature_flag)
        # parameters without excluded_variants
        experiment.parameters = {}
        experiment.save()

        metric = ExperimentMeanMetric(
            source=EventsNode(event="purchase", math=ExperimentMetricMathType.TOTAL),
        )
        query = ExperimentQuery(experiment_id=experiment.id, kind="ExperimentQuery", metric=metric)
        runner = ExperimentQueryRunner(query=query, team=self.team)

        assert set(runner.variants) == {"control", "test"}

    @freeze_time("2020-01-01T12:00:00Z")
    def test_none_parameters_leaves_variants_unchanged(self):
        feature_flag = self.create_feature_flag(key="null-parameters-test")
        experiment = self.create_experiment(feature_flag=feature_flag)
        experiment.parameters = None
        experiment.save()

        metric = ExperimentMeanMetric(
            source=EventsNode(event="purchase", math=ExperimentMetricMathType.TOTAL),
        )
        query = ExperimentQuery(experiment_id=experiment.id, kind="ExperimentQuery", metric=metric)
        runner = ExperimentQueryRunner(query=query, team=self.team)

        assert set(runner.variants) == {"control", "test"}

    @freeze_time("2020-01-01T12:00:00Z")
    def test_empty_excluded_variants_list_leaves_variants_unchanged(self):
        feature_flag = self.create_feature_flag(key="empty-exclusion-test")
        experiment = self.create_experiment(feature_flag=feature_flag)
        # Explicitly set excluded_variants to an empty list
        experiment.parameters = {"excluded_variants": []}
        experiment.save()

        metric = ExperimentMeanMetric(
            source=EventsNode(event="purchase", math=ExperimentMetricMathType.TOTAL),
        )
        query = ExperimentQuery(experiment_id=experiment.id, kind="ExperimentQuery", metric=metric)
        runner = ExperimentQueryRunner(query=query, team=self.team)

        assert set(runner.variants) == {"control", "test"}

    @freeze_time("2020-01-01T12:00:00Z")
    def test_holdout_not_in_runner_variants_even_with_excluded_variants(self):
        feature_flag = self.create_feature_flag(key="holdout-exclusion-test")
        feature_flag.filters["multivariate"]["variants"].append(
            {"key": "test-2", "name": "Test 2", "rollout_percentage": 33}
        )
        feature_flag.save()

        holdout = ExperimentHoldout.objects.create(
            team=self.team, name="Test Holdout", filters=[{"properties": [], "rollout_percentage": 20}]
        )

        experiment = self.create_experiment(feature_flag=feature_flag)
        experiment.holdout = holdout
        experiment.parameters = {"excluded_variants": ["test-2"]}
        experiment.save()

        metric = ExperimentMeanMetric(
            source=EventsNode(event="purchase", math=ExperimentMetricMathType.TOTAL),
        )
        query = ExperimentQuery(experiment_id=experiment.id, kind="ExperimentQuery", metric=metric)
        runner = ExperimentQueryRunner(query=query, team=self.team)

        assert set(runner.variants) == {"control", "test"}
        assert f"holdout-{holdout.id}" not in runner.variants
        assert "test-2" not in runner.variants

    @freeze_time("2020-01-01T12:00:00Z")
    def test_holdout_attached_does_not_appear_in_runner_variants(self):
        feature_flag = self.create_feature_flag(key="holdout-only-metric-test")
        holdout = ExperimentHoldout.objects.create(
            team=self.team,
            name="Holdout A",
            filters=[{"properties": [], "rollout_percentage": 20}],
        )
        experiment = self.create_experiment(feature_flag=feature_flag)
        experiment.holdout = holdout
        experiment.save()
        metric = ExperimentMeanMetric(source=EventsNode(event="purchase", math=ExperimentMetricMathType.TOTAL))
        query = ExperimentQuery(experiment_id=experiment.id, kind="ExperimentQuery", metric=metric)
        runner = ExperimentQueryRunner(query=query, team=self.team)

        assert f"holdout-{holdout.id}" not in runner.variants
        assert set(runner.variants) == {"control", "test"}
        # Holdout is still readable on the experiment for UI/etc.
        assert runner.experiment.holdout is not None

    @freeze_time("2020-01-01T12:00:00Z")
    def test_holdout_and_excluded_variants_both_filtered(self):
        feature_flag = self.create_feature_flag(key="both-filters-metric-test")
        feature_flag.filters["multivariate"]["variants"].append(
            {"key": "test-2", "name": "Test 2", "rollout_percentage": 33}
        )
        feature_flag.save()
        holdout = ExperimentHoldout.objects.create(
            team=self.team,
            name="Holdout B",
            filters=[{"properties": [], "rollout_percentage": 10}],
        )
        experiment = self.create_experiment(feature_flag=feature_flag)
        experiment.holdout = holdout
        experiment.parameters = {"excluded_variants": ["test-2"]}
        experiment.save()
        metric = ExperimentMeanMetric(source=EventsNode(event="purchase", math=ExperimentMetricMathType.TOTAL))
        query = ExperimentQuery(experiment_id=experiment.id, kind="ExperimentQuery", metric=metric)
        runner = ExperimentQueryRunner(query=query, team=self.team)

        assert set(runner.variants) == {"control", "test"}
        assert f"holdout-{holdout.id}" not in runner.variants
        assert "test-2" not in runner.variants

    @freeze_time("2020-01-01T12:00:00Z")
    def test_excluded_variants_containing_holdout_key_is_idempotent(self):
        feature_flag = self.create_feature_flag(key="exclude-names-holdout-metric-test")
        holdout = ExperimentHoldout.objects.create(
            team=self.team,
            name="Holdout C",
            filters=[{"properties": [], "rollout_percentage": 15}],
        )
        experiment = self.create_experiment(feature_flag=feature_flag)
        experiment.holdout = holdout
        experiment.parameters = {"excluded_variants": [f"holdout-{holdout.id}"]}
        experiment.save()
        metric = ExperimentMeanMetric(source=EventsNode(event="purchase", math=ExperimentMetricMathType.TOTAL))
        query = ExperimentQuery(experiment_id=experiment.id, kind="ExperimentQuery", metric=metric)
        runner = ExperimentQueryRunner(query=query, team=self.team)

        assert set(runner.variants) == {"control", "test"}


def test_fingerprint_changes_when_excluded_variants_change():
    metric = {"kind": "ExperimentMeanMetric", "source": {"kind": "EventsNode", "event": "$pageview"}}
    start = "2026-01-01T00:00:00+00:00"

    fp_none = compute_metric_fingerprint(metric, start, excluded_variants=None)
    fp_empty = compute_metric_fingerprint(metric, start, excluded_variants=[])
    fp_one = compute_metric_fingerprint(metric, start, excluded_variants=["test-2"])
    fp_two = compute_metric_fingerprint(metric, start, excluded_variants=["test-2", "test-3"])
    fp_two_reversed = compute_metric_fingerprint(metric, start, excluded_variants=["test-3", "test-2"])
    fp_one_other = compute_metric_fingerprint(metric, start, excluded_variants=["test-3"])

    assert fp_none == fp_empty
    assert fp_one != fp_empty
    assert fp_two != fp_one
    assert fp_two_reversed == fp_two, "Order of excluded keys must not affect fingerprint"
    assert fp_one != fp_one_other
