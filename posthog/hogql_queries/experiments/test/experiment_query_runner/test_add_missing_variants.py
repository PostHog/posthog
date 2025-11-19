from typing import cast

from freezegun import freeze_time

from django.test import override_settings

from posthog.schema import (
    Breakdown,
    BreakdownFilter,
    EventsNode,
    ExperimentMeanMetric,
    ExperimentMetricMathType,
    ExperimentQuery,
    ExperimentStatsBase,
)

from posthog.hogql_queries.experiments.experiment_query_runner import ExperimentQueryRunner
from posthog.hogql_queries.experiments.test.experiment_query_runner.base import ExperimentQueryRunnerBaseTest


@override_settings(IN_UNIT_TESTING=True)
class TestAddMissingVariants(ExperimentQueryRunnerBaseTest):
    """Tests for _add_missing_variants method which ensures all configured variants are present in results."""

    def setUp(self):
        super().setUp()
        self.feature_flag = self.create_feature_flag()
        self.experiment = self.create_experiment(feature_flag=self.feature_flag)

    @freeze_time("2020-01-01T12:00:00Z")
    def test_no_missing_variants(self):
        """When all variants are present, should return unchanged."""
        metric = ExperimentMeanMetric(
            source=EventsNode(event="purchase", math=ExperimentMetricMathType.TOTAL),
        )
        query = ExperimentQuery(experiment_id=self.experiment.id, kind="ExperimentQuery", metric=metric)
        runner = ExperimentQueryRunner(query=query, team=self.team)

        # Both control and test present
        variants = [
            (None, ExperimentStatsBase(key="control", number_of_samples=100, sum=250.0, sum_squares=750.0)),
            (None, ExperimentStatsBase(key="test", number_of_samples=150, sum=400.0, sum_squares=1200.0)),
        ]

        result = runner._add_missing_variants(cast(list[tuple[tuple[str, ...] | None, ExperimentStatsBase]], variants))

        assert len(result) == 2
        assert result == variants

    @freeze_time("2020-01-01T12:00:00Z")
    def test_missing_variant_without_breakdown(self):
        """Should add missing variant with None breakdown."""
        metric = ExperimentMeanMetric(
            source=EventsNode(event="purchase", math=ExperimentMetricMathType.TOTAL),
        )
        query = ExperimentQuery(experiment_id=self.experiment.id, kind="ExperimentQuery", metric=metric)
        runner = ExperimentQueryRunner(query=query, team=self.team)

        # Only control present, test missing
        variants = [
            (None, ExperimentStatsBase(key="control", number_of_samples=100, sum=250.0, sum_squares=750.0)),
        ]

        result = runner._add_missing_variants(cast(list[tuple[tuple[str, ...] | None, ExperimentStatsBase]], variants))

        assert len(result) == 2
        assert result[0][1].key == "control"
        assert result[1][0] is None  # No breakdown
        assert result[1][1].key == "test"
        assert result[1][1].number_of_samples == 0
        assert result[1][1].sum == 0
        assert result[1][1].sum_squares == 0

    @freeze_time("2020-01-01T12:00:00Z")
    def test_multiple_missing_variants_without_breakdown(self):
        """Should add all missing variants when multiple are missing."""
        # Create feature flag with 3 variants
        feature_flag = self.create_feature_flag(key="multi-variant-test")
        feature_flag.filters["multivariate"]["variants"].append(
            {"key": "test-2", "name": "Test 2", "rollout_percentage": 33}
        )
        feature_flag.save()
        experiment = self.create_experiment(feature_flag=feature_flag)

        metric = ExperimentMeanMetric(
            source=EventsNode(event="purchase", math=ExperimentMetricMathType.TOTAL),
        )
        query = ExperimentQuery(experiment_id=experiment.id, kind="ExperimentQuery", metric=metric)
        runner = ExperimentQueryRunner(query=query, team=self.team)

        # Only control present
        variants = [
            (None, ExperimentStatsBase(key="control", number_of_samples=100, sum=250.0, sum_squares=750.0)),
        ]

        result = runner._add_missing_variants(cast(list[tuple[tuple[str, ...] | None, ExperimentStatsBase]], variants))

        assert len(result) == 3
        keys = [v[1].key for v in result]
        assert "control" in keys
        assert "test" in keys
        assert "test-2" in keys

    @freeze_time("2020-01-01T12:00:00Z")
    def test_missing_variant_with_single_breakdown(self):
        """Should add missing variant for each breakdown value."""
        metric = ExperimentMeanMetric(
            source=EventsNode(event="purchase", math=ExperimentMetricMathType.TOTAL),
            breakdownFilter=BreakdownFilter(breakdowns=[Breakdown(property="$browser")]),
        )
        query = ExperimentQuery(experiment_id=self.experiment.id, kind="ExperimentQuery", metric=metric)
        runner = ExperimentQueryRunner(query=query, team=self.team)

        # Control present for both breakdowns, test missing
        variants = [
            (("Chrome",), ExperimentStatsBase(key="control", number_of_samples=50, sum=100.0, sum_squares=300.0)),
            (("Safari",), ExperimentStatsBase(key="control", number_of_samples=50, sum=150.0, sum_squares=450.0)),
        ]

        result = runner._add_missing_variants(cast(list[tuple[tuple[str, ...] | None, ExperimentStatsBase]], variants))

        assert len(result) == 4  # 2 control + 2 test
        # Check test variants were added for both breakdowns
        test_variants = [v for v in result if v[1].key == "test"]
        assert len(test_variants) == 2
        breakdown_values = {v[0] for v in test_variants}
        assert ("Chrome",) in breakdown_values
        assert ("Safari",) in breakdown_values
        # Verify they're empty
        for _, stats in test_variants:
            assert stats.number_of_samples == 0
            assert stats.sum == 0

    @freeze_time("2020-01-01T12:00:00Z")
    def test_missing_variant_with_multiple_breakdowns(self):
        """Should add missing variant for each breakdown combination."""
        metric = ExperimentMeanMetric(
            source=EventsNode(event="purchase", math=ExperimentMetricMathType.TOTAL),
            breakdownFilter=BreakdownFilter(breakdowns=[Breakdown(property="$os"), Breakdown(property="$browser")]),
        )
        query = ExperimentQuery(experiment_id=self.experiment.id, kind="ExperimentQuery", metric=metric)
        runner = ExperimentQueryRunner(query=query, team=self.team)

        # Control present for 2 breakdown combinations
        variants = [
            (
                ("MacOS", "Chrome"),
                ExperimentStatsBase(key="control", number_of_samples=50, sum=100.0, sum_squares=300.0),
            ),
            (
                ("Windows", "Firefox"),
                ExperimentStatsBase(key="control", number_of_samples=30, sum=75.0, sum_squares=200.0),
            ),
        ]

        result = runner._add_missing_variants(cast(list[tuple[tuple[str, ...] | None, ExperimentStatsBase]], variants))

        assert len(result) == 4  # 2 control + 2 test
        test_variants = [v for v in result if v[1].key == "test"]
        assert len(test_variants) == 2
        breakdown_values = {v[0] for v in test_variants}
        assert ("MacOS", "Chrome") in breakdown_values
        assert ("Windows", "Firefox") in breakdown_values

    @freeze_time("2020-01-01T12:00:00Z")
    def test_empty_variants_list(self):
        """Should add all configured variants when input is empty."""
        metric = ExperimentMeanMetric(
            source=EventsNode(event="purchase", math=ExperimentMetricMathType.TOTAL),
        )
        query = ExperimentQuery(experiment_id=self.experiment.id, kind="ExperimentQuery", metric=metric)
        runner = ExperimentQueryRunner(query=query, team=self.team)

        variants: list[tuple[tuple[str, ...] | None, ExperimentStatsBase]] = []

        result = runner._add_missing_variants(variants)

        assert len(result) == 2
        keys = [v[1].key for v in result]
        assert "control" in keys
        assert "test" in keys
        # All should have None breakdown
        for breakdown, stats in result:
            assert breakdown is None
            assert stats.number_of_samples == 0

    @freeze_time("2020-01-01T12:00:00Z")
    def test_preserves_existing_variants(self):
        """Should not modify existing variant data."""
        metric = ExperimentMeanMetric(
            source=EventsNode(event="purchase", math=ExperimentMetricMathType.TOTAL),
        )
        query = ExperimentQuery(experiment_id=self.experiment.id, kind="ExperimentQuery", metric=metric)
        runner = ExperimentQueryRunner(query=query, team=self.team)

        original_variants = [
            (None, ExperimentStatsBase(key="control", number_of_samples=100, sum=250.0, sum_squares=750.0)),
        ]

        result = runner._add_missing_variants(
            cast(list[tuple[tuple[str, ...] | None, ExperimentStatsBase]], original_variants)
        )

        # Original variant should be unchanged
        assert result[0] == original_variants[0]
        assert result[0][1].number_of_samples == 100
        assert result[0][1].sum == 250.0

    @freeze_time("2020-01-01T12:00:00Z")
    def test_creates_unique_objects_per_breakdown(self):
        """Verifies that each breakdown gets a unique ExperimentStatsBase object (regression test)."""
        metric = ExperimentMeanMetric(
            source=EventsNode(event="purchase", math=ExperimentMetricMathType.TOTAL),
            breakdownFilter=BreakdownFilter(breakdowns=[Breakdown(property="$browser")]),
        )
        query = ExperimentQuery(experiment_id=self.experiment.id, kind="ExperimentQuery", metric=metric)
        runner = ExperimentQueryRunner(query=query, team=self.team)

        # Control present for multiple breakdowns
        variants = [
            (("Chrome",), ExperimentStatsBase(key="control", number_of_samples=50, sum=100.0, sum_squares=300.0)),
            (("Safari",), ExperimentStatsBase(key="control", number_of_samples=30, sum=75.0, sum_squares=200.0)),
            (("Firefox",), ExperimentStatsBase(key="control", number_of_samples=20, sum=50.0, sum_squares=150.0)),
        ]

        result = runner._add_missing_variants(cast(list[tuple[tuple[str, ...] | None, ExperimentStatsBase]], variants))

        # Get all test variants
        test_variants = [v for v in result if v[1].key == "test"]
        assert len(test_variants) == 3

        # Verify they're not the same object (would be a bug)
        objects = [v[1] for v in test_variants]
        assert objects[0] is not objects[1]
        assert objects[0] is not objects[2]
        assert objects[1] is not objects[2]

    @freeze_time("2020-01-01T12:00:00Z")
    def test_with_holdout_variant(self):
        """Should handle holdout variants correctly."""
        from posthog.models.experiment import ExperimentHoldout

        holdout = ExperimentHoldout.objects.create(
            team=self.team, name="Test Holdout", filters=[{"properties": [], "rollout_percentage": 20}]
        )
        self.experiment.holdout = holdout
        self.experiment.save()

        metric = ExperimentMeanMetric(
            source=EventsNode(event="purchase", math=ExperimentMetricMathType.TOTAL),
        )
        query = ExperimentQuery(experiment_id=self.experiment.id, kind="ExperimentQuery", metric=metric)
        runner = ExperimentQueryRunner(query=query, team=self.team)

        # Only control present
        variants = [
            (None, ExperimentStatsBase(key="control", number_of_samples=100, sum=250.0, sum_squares=750.0)),
        ]

        result = runner._add_missing_variants(cast(list[tuple[tuple[str, ...] | None, ExperimentStatsBase]], variants))

        assert len(result) == 3  # control + test + holdout
        keys = [v[1].key for v in result]
        assert "control" in keys
        assert "test" in keys
        assert f"holdout-{holdout.id}" in keys
