from datetime import datetime
from typing import cast

from freezegun import freeze_time
from posthog.test.base import _create_event, _create_person, flush_persons_and_events

from django.test import override_settings

from parameterized import parameterized

from posthog.schema import (
    EventsNode,
    ExperimentFunnelMetric,
    ExperimentQuery,
    ExperimentQueryResponse,
    ExperimentVariantResultFrequentist,
    FunnelConversionWindowTimeUnit,
    StepOrderValue,
)

from posthog.hogql_queries.experiments.experiment_query_runner import ExperimentQueryRunner
from posthog.hogql_queries.experiments.test.experiment_query_runner.base import ExperimentQueryRunnerBaseTest


@override_settings(IN_UNIT_TESTING=True)
class TestExperimentFunnelMetricCuped(ExperimentQueryRunnerBaseTest):
    def _create_exposure(self, feature_flag, distinct_id: str, variant: str, timestamp: str) -> None:
        feature_flag_property = f"$feature/{feature_flag.key}"
        _create_event(
            team=self.team,
            event="$feature_flag_called",
            distinct_id=distinct_id,
            timestamp=timestamp,
            properties={
                feature_flag_property: variant,
                "$feature_flag_response": variant,
                "$feature_flag": feature_flag.key,
            },
        )

    def _create_checkout(self, feature_flag, distinct_id: str, timestamp: str) -> None:
        _create_event(
            team=self.team,
            event="checkout completed",
            distinct_id=distinct_id,
            timestamp=timestamp,
            properties={f"$feature/{feature_flag.key}": "ignored"},
        )

    def _create_signup(self, feature_flag, distinct_id: str, timestamp: str) -> None:
        _create_event(
            team=self.team,
            event="signup",
            distinct_id=distinct_id,
            timestamp=timestamp,
            properties={f"$feature/{feature_flag.key}": "ignored"},
        )

    def _build_single_step_metric(
        self,
        conversion_window: int | None = None,
        conversion_window_unit: FunnelConversionWindowTimeUnit | None = None,
    ) -> ExperimentFunnelMetric:
        return ExperimentFunnelMetric(
            series=[EventsNode(event="checkout completed")],
            conversion_window=conversion_window,
            conversion_window_unit=conversion_window_unit,
        )

    def _build_multi_step_metric(self) -> ExperimentFunnelMetric:
        return ExperimentFunnelMetric(
            series=[
                EventsNode(event="signup"),
                EventsNode(event="checkout completed"),
            ],
        )

    def _run_metric(self, experiment, metric: ExperimentFunnelMetric) -> ExperimentQueryResponse:
        experiment.metrics = [metric.model_dump(mode="json")]
        experiment.save()

        experiment_query = ExperimentQuery(
            experiment_id=experiment.id,
            kind="ExperimentQuery",
            metric=metric,
        )

        query_runner = ExperimentQueryRunner(query=experiment_query, team=self.team)
        return cast(ExperimentQueryResponse, query_runner.calculate())

    def _create_correlated_funnel_data(
        self,
        feature_flag,
        samples_per_variant: int = 60,
        create_pre_exposure_events: bool = True,
    ) -> None:
        """
        Build correlated pre/post conversion data: users who converted in the
        pre-window are more likely to convert in the post-window. Treatment
        bumps post-window conversion rate.
        """
        for variant, treatment_bump in [("control", 0), ("test", 1)]:
            for i in range(samples_per_variant):
                distinct_id = f"{feature_flag.key}_{variant}_{i}"
                _create_person(distinct_ids=[distinct_id], team_id=self.team.pk)

                # Half the users converted in the pre-window
                converted_pre = i % 2 == 0
                if create_pre_exposure_events and converted_pre:
                    self._create_checkout(feature_flag, distinct_id, "2020-01-09T12:00:00Z")

                self._create_exposure(feature_flag, distinct_id, variant, "2020-01-10T12:00:00Z")

                # Pre converters convert again 90% of the time, non converters 30%.
                # Treatment bumps both rates.
                base_post_rate = 0.9 if converted_pre else 0.3
                threshold = int((base_post_rate + treatment_bump * 0.05) * 100)
                if (i * 7) % 100 < threshold:
                    self._create_checkout(feature_flag, distinct_id, "2020-01-10T13:00:00Z")

    @freeze_time("2020-01-15T12:00:00Z")
    def test_disabled_cuped_does_not_collect_covariate_columns(self):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(
            feature_flag=feature_flag,
            start_date=datetime(2020, 1, 10, 0, 0, 0),
            end_date=datetime(2020, 1, 15, 0, 0, 0),
        )
        experiment.stats_config = {"method": "frequentist"}
        experiment.save()

        for distinct_id, variant in [
            ("control_1", "control"),
            ("test_1", "test"),
        ]:
            _create_person(distinct_ids=[distinct_id], team_id=self.team.pk)
            self._create_checkout(feature_flag, distinct_id, "2020-01-09T12:00:00Z")
            self._create_exposure(feature_flag, distinct_id, variant, "2020-01-10T12:00:00Z")
            self._create_checkout(feature_flag, distinct_id, "2020-01-10T13:00:00Z")

        flush_persons_and_events()

        result = self._run_metric(experiment, self._build_single_step_metric())

        assert result.baseline is not None
        assert result.variant_results is not None
        self.assertEqual(result.baseline.sum, 1)
        self.assertEqual(result.variant_results[0].sum, 1)
        self.assertIsNone(result.baseline.covariate_sum)
        self.assertIsNone(result.variant_results[0].covariate_sum)

    @freeze_time("2020-01-15T12:00:00Z")
    def test_cuped_funnel_metric_collects_covariate_columns(self):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(
            feature_flag=feature_flag,
            start_date=datetime(2020, 1, 10, 0, 0, 0),
            end_date=datetime(2020, 1, 15, 0, 0, 0),
        )
        experiment.stats_config = {"method": "frequentist", "cuped": {"enabled": True, "lookback_days": 7}}
        experiment.save()

        # control_1: pre-converted, post-converted -> covariate=1, value=1
        # control_2: not pre-converted, post-converted -> covariate=0, value=1
        # test_1: pre-converted, not post-converted -> covariate=1, value=0
        # test_2: pre-converted, post-converted -> covariate=1, value=1
        _create_person(distinct_ids=["control_1"], team_id=self.team.pk)
        self._create_checkout(feature_flag, "control_1", "2020-01-08T12:00:00Z")
        self._create_exposure(feature_flag, "control_1", "control", "2020-01-10T12:00:00Z")
        self._create_checkout(feature_flag, "control_1", "2020-01-10T13:00:00Z")

        _create_person(distinct_ids=["control_2"], team_id=self.team.pk)
        self._create_exposure(feature_flag, "control_2", "control", "2020-01-10T12:00:00Z")
        self._create_checkout(feature_flag, "control_2", "2020-01-10T13:00:00Z")

        _create_person(distinct_ids=["test_1"], team_id=self.team.pk)
        self._create_checkout(feature_flag, "test_1", "2020-01-08T12:00:00Z")
        self._create_exposure(feature_flag, "test_1", "test", "2020-01-10T12:00:00Z")

        _create_person(distinct_ids=["test_2"], team_id=self.team.pk)
        self._create_checkout(feature_flag, "test_2", "2020-01-08T12:00:00Z")
        self._create_exposure(feature_flag, "test_2", "test", "2020-01-10T12:00:00Z")
        self._create_checkout(feature_flag, "test_2", "2020-01-10T13:00:00Z")

        flush_persons_and_events()

        result = self._run_metric(experiment, self._build_single_step_metric())

        assert result.baseline is not None
        assert result.variant_results is not None
        control_variant = result.baseline
        test_variant = result.variant_results[0]

        # Both control users converted post; one had a pre-window conversion.
        self.assertEqual(control_variant.sum, 2)
        self.assertEqual(control_variant.covariate_sum, 1)
        self.assertEqual(control_variant.covariate_sum_squares, 1)
        self.assertEqual(control_variant.covariate_sum_product, 1)

        # Test: 1 of 2 converted post; both had pre-window conversion.
        self.assertEqual(test_variant.sum, 1)
        self.assertEqual(test_variant.covariate_sum, 2)
        self.assertEqual(test_variant.covariate_sum_squares, 2)
        # Only the user that converted both pre and post contributes to the cross product.
        self.assertEqual(test_variant.covariate_sum_product, 1)

    @freeze_time("2020-01-15T12:00:00Z")
    def test_cuped_uses_pre_exposure_window_relative_to_first_exposure(self):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(
            feature_flag=feature_flag,
            start_date=datetime(2020, 1, 10, 0, 0, 0),
            end_date=datetime(2020, 1, 15, 0, 0, 0),
        )
        experiment.stats_config = {"method": "frequentist", "cuped": {"enabled": True, "lookback_days": 2}}
        experiment.save()

        # control_1's first exposure is at 2020-01-10T12:00:00Z, so pre-window is
        # [2020-01-08T12:00:00Z, 2020-01-10T12:00:00Z). The 2020-01-07 checkout is
        # outside the window and must not contribute to the covariate.
        _create_person(distinct_ids=["control_1"], team_id=self.team.pk)
        self._create_checkout(feature_flag, "control_1", "2020-01-07T12:00:00Z")
        self._create_checkout(feature_flag, "control_1", "2020-01-09T12:00:00Z")
        self._create_exposure(feature_flag, "control_1", "control", "2020-01-10T12:00:00Z")
        self._create_checkout(feature_flag, "control_1", "2020-01-11T12:00:00Z")
        # A later exposure should not shift the pre-window since first_exposure_time stays put.
        self._create_exposure(feature_flag, "control_1", "control", "2020-01-12T12:00:00Z")

        _create_person(distinct_ids=["test_1"], team_id=self.team.pk)
        self._create_checkout(feature_flag, "test_1", "2020-01-09T12:00:00Z")
        self._create_exposure(feature_flag, "test_1", "test", "2020-01-10T12:00:00Z")
        self._create_checkout(feature_flag, "test_1", "2020-01-11T12:00:00Z")

        flush_persons_and_events()

        result = self._run_metric(experiment, self._build_single_step_metric())

        assert result.baseline is not None
        assert result.variant_results is not None
        control_variant = result.baseline
        test_variant = result.variant_results[0]

        self.assertEqual(control_variant.sum, 1)
        self.assertEqual(control_variant.covariate_sum, 1)
        self.assertEqual(control_variant.covariate_sum_product, 1)

        self.assertEqual(test_variant.sum, 1)
        self.assertEqual(test_variant.covariate_sum, 1)
        self.assertEqual(test_variant.covariate_sum_product, 1)

    @freeze_time("2020-01-15T12:00:00Z")
    def test_cuped_multi_step_funnel_uses_last_step_for_covariate(self):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(
            feature_flag=feature_flag,
            start_date=datetime(2020, 1, 10, 0, 0, 0),
            end_date=datetime(2020, 1, 15, 0, 0, 0),
        )
        experiment.stats_config = {"method": "frequentist", "cuped": {"enabled": True, "lookback_days": 7}}
        experiment.save()

        # control_1: pre-window has only signup (not checkout) -> covariate = 0
        _create_person(distinct_ids=["control_1"], team_id=self.team.pk)
        self._create_signup(feature_flag, "control_1", "2020-01-08T12:00:00Z")
        self._create_exposure(feature_flag, "control_1", "control", "2020-01-10T12:00:00Z")
        self._create_signup(feature_flag, "control_1", "2020-01-10T13:00:00Z")
        self._create_checkout(feature_flag, "control_1", "2020-01-10T13:30:00Z")

        # control_2: pre-window has checkout but no signup -> covariate = 1 because the
        # last funnel step's event fired in the pre-window. Pre-window funnel completion
        # is intentionally not enforced — matching the example's last-step-event check.
        _create_person(distinct_ids=["control_2"], team_id=self.team.pk)
        self._create_checkout(feature_flag, "control_2", "2020-01-08T12:00:00Z")
        self._create_exposure(feature_flag, "control_2", "control", "2020-01-10T12:00:00Z")
        self._create_signup(feature_flag, "control_2", "2020-01-10T13:00:00Z")
        self._create_checkout(feature_flag, "control_2", "2020-01-10T13:30:00Z")

        # test_1: no pre-window funnel events at all -> covariate = 0
        _create_person(distinct_ids=["test_1"], team_id=self.team.pk)
        self._create_exposure(feature_flag, "test_1", "test", "2020-01-10T12:00:00Z")
        self._create_signup(feature_flag, "test_1", "2020-01-10T13:00:00Z")

        flush_persons_and_events()

        result = self._run_metric(experiment, self._build_multi_step_metric())

        assert result.baseline is not None
        assert result.variant_results is not None
        control_variant = result.baseline
        test_variant = result.variant_results[0]

        self.assertEqual(control_variant.sum, 2)  # both control users completed signup -> checkout
        self.assertEqual(control_variant.covariate_sum, 1)  # only control_2 fired checkout pre-window
        self.assertEqual(control_variant.covariate_sum_product, 1)

        self.assertEqual(test_variant.sum, 0)
        self.assertEqual(test_variant.covariate_sum, 0)
        self.assertEqual(test_variant.covariate_sum_product, 0)

    @freeze_time("2020-01-15T12:00:00Z")
    def test_cuped_query_uses_single_metric_events_scan(self):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(
            feature_flag=feature_flag,
            start_date=datetime(2020, 1, 10, 0, 0, 0),
            end_date=datetime(2020, 1, 15, 0, 0, 0),
        )
        experiment.stats_config = {"method": "frequentist", "cuped": {"enabled": True, "lookback_days": 7}}
        experiment.save()

        _create_person(distinct_ids=["control_1"], team_id=self.team.pk)
        self._create_exposure(feature_flag, "control_1", "control", "2020-01-10T12:00:00Z")
        _create_person(distinct_ids=["test_1"], team_id=self.team.pk)
        self._create_exposure(feature_flag, "test_1", "test", "2020-01-10T12:00:00Z")
        flush_persons_and_events()

        result = self._run_metric(experiment, self._build_single_step_metric())

        assert result.hogql is not None
        # CUPED reuses the existing base_events scan; no separate pre-window CTE.
        self.assertNotIn("pre_metric_events", result.hogql)
        self.assertNotIn("pre_base_events", result.hogql)

    @freeze_time("2020-01-15T12:00:00Z")
    def test_cuped_unordered_funnel_disables_cuped(self):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(
            feature_flag=feature_flag,
            start_date=datetime(2020, 1, 10, 0, 0, 0),
            end_date=datetime(2020, 1, 15, 0, 0, 0),
        )
        experiment.stats_config = {"method": "frequentist", "cuped": {"enabled": True, "lookback_days": 7}}
        experiment.save()

        for distinct_id, variant in [("control_1", "control"), ("test_1", "test")]:
            _create_person(distinct_ids=[distinct_id], team_id=self.team.pk)
            self._create_checkout(feature_flag, distinct_id, "2020-01-08T12:00:00Z")
            self._create_exposure(feature_flag, distinct_id, variant, "2020-01-10T12:00:00Z")
            self._create_checkout(feature_flag, distinct_id, "2020-01-10T13:00:00Z")

        flush_persons_and_events()

        metric = ExperimentFunnelMetric(
            series=[EventsNode(event="checkout completed")],
            funnel_order_type=StepOrderValue.UNORDERED,
        )
        result = self._run_metric(experiment, metric)

        assert result.baseline is not None
        assert result.variant_results is not None
        self.assertIsNone(result.baseline.covariate_sum)
        self.assertIsNone(result.variant_results[0].covariate_sum)

    @freeze_time("2020-01-15T12:00:00Z")
    def test_cuped_handles_zero_pre_exposure_data(self):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(
            feature_flag=feature_flag,
            start_date=datetime(2020, 1, 10, 0, 0, 0),
            end_date=datetime(2020, 1, 15, 0, 0, 0),
        )
        experiment.stats_config = {"method": "frequentist", "cuped": {"enabled": True, "lookback_days": 7}}
        experiment.save()

        self._create_correlated_funnel_data(feature_flag, create_pre_exposure_events=False)
        flush_persons_and_events()

        result = self._run_metric(experiment, self._build_single_step_metric())

        assert result.baseline is not None
        assert result.variant_results is not None
        self.assertEqual(result.baseline.covariate_sum, 0)
        self.assertEqual(result.baseline.covariate_sum_squares, 0)
        self.assertEqual(result.baseline.covariate_sum_product, 0)

        variant = cast(ExperimentVariantResultFrequentist, result.variant_results[0])
        self.assertEqual(variant.covariate_sum, 0)
        self.assertEqual(variant.covariate_sum_product, 0)
        # With θ pinned to zero (no pre variance), the test still produces a p-value.
        assert variant.p_value is not None

    @parameterized.expand(
        [
            ("frequentist", "frequentist", "confidence_interval"),
            ("bayesian", "bayesian", "credible_interval"),
        ]
    )
    @freeze_time("2020-01-15T12:00:00Z")
    def test_cuped_adjusts_statistical_result(self, name, method, interval_attr):
        metric = self._build_single_step_metric()

        no_cuped_feature_flag = self.create_feature_flag(f"no-cuped-{name}-funnel-experiment")
        no_cuped_experiment = self.create_experiment(
            name=f"no-cuped-{name}-funnel-experiment",
            feature_flag=no_cuped_feature_flag,
            start_date=datetime(2020, 1, 10, 0, 0, 0),
            end_date=datetime(2020, 1, 15, 0, 0, 0),
        )
        no_cuped_experiment.stats_config = {"method": method}
        no_cuped_experiment.save()

        cuped_feature_flag = self.create_feature_flag(f"cuped-{name}-funnel-experiment")
        cuped_experiment = self.create_experiment(
            name=f"cuped-{name}-funnel-experiment",
            feature_flag=cuped_feature_flag,
            start_date=datetime(2020, 1, 10, 0, 0, 0),
            end_date=datetime(2020, 1, 15, 0, 0, 0),
        )
        cuped_experiment.stats_config = {
            "method": method,
            "cuped": {"enabled": True, "lookback_days": 7},
        }
        cuped_experiment.save()

        self._create_correlated_funnel_data(no_cuped_feature_flag)
        self._create_correlated_funnel_data(cuped_feature_flag)
        flush_persons_and_events()

        no_cuped_result = self._run_metric(no_cuped_experiment, metric)
        cuped_result = self._run_metric(cuped_experiment, metric)

        assert no_cuped_result.variant_results is not None
        assert cuped_result.variant_results is not None
        no_cuped_interval = getattr(no_cuped_result.variant_results[0], interval_attr)
        cuped_interval = getattr(cuped_result.variant_results[0], interval_attr)
        assert no_cuped_interval is not None
        assert cuped_interval is not None
        # Variance reduction shrinks the interval; equality only happens when θ = 0.
        self.assertLess(cuped_interval[1] - cuped_interval[0], no_cuped_interval[1] - no_cuped_interval[0])
