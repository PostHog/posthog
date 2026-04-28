from datetime import datetime
from typing import cast

from freezegun import freeze_time
from posthog.test.base import _create_event, _create_person, flush_persons_and_events

from django.test import override_settings

from parameterized import parameterized

from posthog.schema import (
    EventsNode,
    ExperimentMeanMetric,
    ExperimentMetricMathType,
    ExperimentQuery,
    ExperimentQueryResponse,
    ExperimentVariantResultBayesian,
    ExperimentVariantResultFrequentist,
    FunnelConversionWindowTimeUnit,
)

from posthog.hogql_queries.experiments.experiment_query_runner import ExperimentQueryRunner
from posthog.hogql_queries.experiments.test.experiment_query_runner.base import ExperimentQueryRunnerBaseTest


@override_settings(IN_UNIT_TESTING=True)
class TestExperimentMeanMetricCuped(ExperimentQueryRunnerBaseTest):
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

    def _create_purchase(self, feature_flag, distinct_id: str, timestamp: str, amount: float) -> None:
        _create_event(
            team=self.team,
            event="purchase",
            distinct_id=distinct_id,
            timestamp=timestamp,
            properties={
                f"$feature/{feature_flag.key}": "ignored",
                "amount": amount,
            },
        )

    def _create_pageview(self, feature_flag, distinct_id: str, timestamp: str, session_id: str) -> None:
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id=distinct_id,
            timestamp=timestamp,
            properties={
                f"$feature/{feature_flag.key}": "ignored",
                "$session_id": session_id,
            },
        )

    def _build_sum_metric(
        self,
        conversion_window: int | None = None,
        conversion_window_unit: FunnelConversionWindowTimeUnit | None = None,
    ) -> ExperimentMeanMetric:
        return ExperimentMeanMetric(
            source=EventsNode(
                event="purchase",
                math=ExperimentMetricMathType.SUM,
                math_property="amount",
            ),
            conversion_window=conversion_window,
            conversion_window_unit=conversion_window_unit,
        )

    def _run_metric(self, experiment, metric: ExperimentMeanMetric) -> ExperimentQueryResponse:
        experiment.metrics = [metric.model_dump(mode="json")]
        experiment.save()

        experiment_query = ExperimentQuery(
            experiment_id=experiment.id,
            kind="ExperimentQuery",
            metric=metric,
        )

        query_runner = ExperimentQueryRunner(query=experiment_query, team=self.team)
        return cast(ExperimentQueryResponse, query_runner.calculate())

    def _create_correlated_data(
        self,
        feature_flag,
        samples_per_variant: int = 60,
        create_pre_exposure_events: bool = True,
    ) -> None:
        for variant, treatment_effect in [("control", 0), ("test", 1)]:
            for i in range(samples_per_variant):
                distinct_id = f"{feature_flag.key}_{variant}_{i}"
                pre_amount = i + 1
                post_amount = pre_amount + treatment_effect
                _create_person(distinct_ids=[distinct_id], team_id=self.team.pk)
                if create_pre_exposure_events:
                    self._create_purchase(feature_flag, distinct_id, "2020-01-09T12:00:00Z", pre_amount)
                self._create_exposure(feature_flag, distinct_id, variant, "2020-01-10T12:00:00Z")
                self._create_purchase(feature_flag, distinct_id, "2020-01-10T13:00:00Z", post_amount)

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

        for distinct_id, variant, pre_amount, post_amount in [
            ("control_1", "control", 3, 10),
            ("test_1", "test", 5, 20),
        ]:
            _create_person(distinct_ids=[distinct_id], team_id=self.team.pk)
            self._create_purchase(feature_flag, distinct_id, "2020-01-09T12:00:00Z", pre_amount)
            self._create_exposure(feature_flag, distinct_id, variant, "2020-01-10T12:00:00Z")
            self._create_purchase(feature_flag, distinct_id, "2020-01-10T13:00:00Z", post_amount)

        flush_persons_and_events()

        result = self._run_metric(experiment, self._build_sum_metric())

        assert result.baseline is not None
        assert result.variant_results is not None
        self.assertEqual(result.baseline.sum, 10)
        self.assertEqual(result.variant_results[0].sum, 20)
        self.assertIsNone(result.baseline.covariate_sum)
        self.assertIsNone(result.variant_results[0].covariate_sum)

    @freeze_time("2020-01-15T12:00:00Z")
    def test_cuped_mean_metric_collects_covariate_columns(self):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(
            feature_flag=feature_flag,
            start_date=datetime(2020, 1, 10, 0, 0, 0),
            end_date=datetime(2020, 1, 15, 0, 0, 0),
        )
        experiment.stats_config = {"method": "frequentist", "cuped": {"enabled": True, "lookback_days": 7}}
        experiment.save()

        for distinct_id, variant, pre_amount, post_amount in [
            ("control_1", "control", 3, 10),
            ("control_2", "control", 4, 20),
            ("test_1", "test", 5, 30),
            ("test_2", "test", 6, 40),
        ]:
            _create_person(distinct_ids=[distinct_id], team_id=self.team.pk)
            self._create_purchase(feature_flag, distinct_id, "2020-01-08T12:00:00Z", pre_amount)
            self._create_exposure(feature_flag, distinct_id, variant, "2020-01-10T12:00:00Z")
            self._create_purchase(feature_flag, distinct_id, "2020-01-10T13:00:00Z", post_amount)

        flush_persons_and_events()

        result = self._run_metric(experiment, self._build_sum_metric())

        assert result.baseline is not None
        assert result.variant_results is not None
        control_variant = result.baseline
        test_variant = result.variant_results[0]

        self.assertEqual(control_variant.sum, 30)
        self.assertEqual(control_variant.covariate_sum, 7)
        self.assertEqual(control_variant.covariate_sum_squares, 25)
        self.assertEqual(control_variant.main_covariate_sum_product, 110)

        self.assertEqual(test_variant.sum, 70)
        self.assertEqual(test_variant.covariate_sum, 11)
        self.assertEqual(test_variant.covariate_sum_squares, 61)
        self.assertEqual(test_variant.main_covariate_sum_product, 390)

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

        _create_person(distinct_ids=["control_1"], team_id=self.team.pk)
        self._create_purchase(feature_flag, "control_1", "2020-01-07T12:00:00Z", 100)
        self._create_purchase(feature_flag, "control_1", "2020-01-09T12:00:00Z", 5)
        self._create_exposure(feature_flag, "control_1", "control", "2020-01-10T12:00:00Z")
        self._create_purchase(feature_flag, "control_1", "2020-01-11T12:00:00Z", 7)
        self._create_exposure(feature_flag, "control_1", "control", "2020-01-12T12:00:00Z")

        _create_person(distinct_ids=["test_1"], team_id=self.team.pk)
        self._create_purchase(feature_flag, "test_1", "2020-01-09T12:00:00Z", 6)
        self._create_exposure(feature_flag, "test_1", "test", "2020-01-10T12:00:00Z")
        self._create_purchase(feature_flag, "test_1", "2020-01-11T12:00:00Z", 8)

        flush_persons_and_events()

        result = self._run_metric(experiment, self._build_sum_metric())

        assert result.baseline is not None
        assert result.variant_results is not None
        control_variant = result.baseline
        test_variant = result.variant_results[0]

        self.assertEqual(control_variant.sum, 7)
        self.assertEqual(control_variant.covariate_sum, 5)
        self.assertEqual(control_variant.covariate_sum_squares, 25)
        self.assertEqual(control_variant.main_covariate_sum_product, 35)

        self.assertEqual(test_variant.sum, 8)
        self.assertEqual(test_variant.covariate_sum, 6)
        self.assertEqual(test_variant.main_covariate_sum_product, 48)

    @freeze_time("2020-01-15T12:00:00Z")
    def test_cuped_respects_conversion_window_for_post_values(self):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(
            feature_flag=feature_flag,
            start_date=datetime(2020, 1, 10, 0, 0, 0),
            end_date=datetime(2020, 1, 15, 0, 0, 0),
        )
        experiment.stats_config = {"method": "frequentist", "cuped": {"enabled": True, "lookback_days": 7}}
        experiment.save()

        _create_person(distinct_ids=["control_1"], team_id=self.team.pk)
        self._create_purchase(feature_flag, "control_1", "2020-01-09T12:00:00Z", 4)
        self._create_exposure(feature_flag, "control_1", "control", "2020-01-10T12:00:00Z")
        self._create_purchase(feature_flag, "control_1", "2020-01-10T13:00:00Z", 10)
        self._create_purchase(feature_flag, "control_1", "2020-01-12T13:00:00Z", 100)

        _create_person(distinct_ids=["test_1"], team_id=self.team.pk)
        self._create_purchase(feature_flag, "test_1", "2020-01-09T12:00:00Z", 5)
        self._create_exposure(feature_flag, "test_1", "test", "2020-01-10T12:00:00Z")
        self._create_purchase(feature_flag, "test_1", "2020-01-10T13:00:00Z", 20)
        self._create_purchase(feature_flag, "test_1", "2020-01-12T13:00:00Z", 100)

        flush_persons_and_events()

        metric = self._build_sum_metric(
            conversion_window=1,
            conversion_window_unit=FunnelConversionWindowTimeUnit.DAY,
        )
        result = self._run_metric(experiment, metric)

        assert result.baseline is not None
        assert result.variant_results is not None
        self.assertEqual(result.baseline.sum, 10)
        self.assertEqual(result.baseline.covariate_sum, 4)
        self.assertEqual(result.baseline.main_covariate_sum_product, 40)
        self.assertEqual(result.variant_results[0].sum, 20)
        self.assertEqual(result.variant_results[0].covariate_sum, 5)
        self.assertEqual(result.variant_results[0].main_covariate_sum_product, 100)

    @parameterized.expand(
        [
            ("direct", False),
            ("precomputed", True),
        ]
    )
    @freeze_time("2020-01-15T12:00:00Z")
    def test_cuped_works_with_precomputed_exposures(self, _name, use_precomputation):
        self._setup_precomputation_test(use_precomputation)

        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(
            feature_flag=feature_flag,
            start_date=datetime(2020, 1, 10, 0, 0, 0),
            end_date=datetime(2020, 1, 15, 0, 0, 0),
        )
        experiment.stats_config = {"method": "frequentist", "cuped": {"enabled": True, "lookback_days": 7}}
        experiment.save()

        for distinct_id, variant, pre_amount, post_amount in [
            ("control_1", "control", 3, 10),
            ("test_1", "test", 5, 20),
        ]:
            _create_person(distinct_ids=[distinct_id], team_id=self.team.pk)
            self._create_purchase(feature_flag, distinct_id, "2020-01-09T12:00:00Z", pre_amount)
            self._create_exposure(feature_flag, distinct_id, variant, "2020-01-10T12:00:00Z")
            self._create_purchase(feature_flag, distinct_id, "2020-01-10T13:00:00Z", post_amount)

        flush_persons_and_events()

        metric = self._build_sum_metric()
        experiment.metrics = [metric.model_dump(mode="json")]
        self._save_experiment_with_precomputation(experiment, use_precomputation)

        experiment_query = ExperimentQuery(
            experiment_id=experiment.id,
            kind="ExperimentQuery",
            metric=metric,
        )
        query_runner = ExperimentQueryRunner(query=experiment_query, team=self.team)
        result = cast(ExperimentQueryResponse, query_runner.calculate())

        assert result.baseline is not None
        assert result.variant_results is not None
        self.assertEqual(result.baseline.covariate_sum, 3)
        self.assertEqual(result.variant_results[0].covariate_sum, 5)

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

        result = self._run_metric(experiment, self._build_sum_metric())

        assert result.hogql is not None
        self.assertNotIn("pre_metric_events", result.hogql)
        self.assertEqual(result.hogql.count("metric_events AS"), 1)

    @freeze_time("2020-01-15T12:00:00Z")
    def test_cuped_adjusts_statistical_result(self):
        metric = self._build_sum_metric()

        no_cuped_feature_flag = self.create_feature_flag("no-cuped-experiment")
        no_cuped_experiment = self.create_experiment(
            name="no-cuped-experiment",
            feature_flag=no_cuped_feature_flag,
            start_date=datetime(2020, 1, 10, 0, 0, 0),
            end_date=datetime(2020, 1, 15, 0, 0, 0),
        )
        no_cuped_experiment.stats_config = {"method": "frequentist"}
        no_cuped_experiment.save()

        cuped_feature_flag = self.create_feature_flag("cuped-experiment")
        cuped_experiment = self.create_experiment(
            name="cuped-experiment",
            feature_flag=cuped_feature_flag,
            start_date=datetime(2020, 1, 10, 0, 0, 0),
            end_date=datetime(2020, 1, 15, 0, 0, 0),
        )
        cuped_experiment.stats_config = {
            "method": "frequentist",
            "cuped": {"enabled": True, "lookback_days": 7},
        }
        cuped_experiment.save()

        self._create_correlated_data(no_cuped_feature_flag)
        self._create_correlated_data(cuped_feature_flag)
        flush_persons_and_events()

        no_cuped_result = self._run_metric(no_cuped_experiment, metric)
        cuped_result = self._run_metric(cuped_experiment, metric)

        assert no_cuped_result.variant_results is not None
        assert cuped_result.variant_results is not None
        no_cuped_variant = cast(ExperimentVariantResultFrequentist, no_cuped_result.variant_results[0])
        cuped_variant = cast(ExperimentVariantResultFrequentist, cuped_result.variant_results[0])

        assert no_cuped_variant.p_value is not None
        assert cuped_variant.p_value is not None
        self.assertLess(cuped_variant.p_value, no_cuped_variant.p_value)
        assert no_cuped_variant.confidence_interval is not None
        assert cuped_variant.confidence_interval is not None
        no_cuped_interval_width = no_cuped_variant.confidence_interval[1] - no_cuped_variant.confidence_interval[0]
        cuped_interval_width = cuped_variant.confidence_interval[1] - cuped_variant.confidence_interval[0]
        self.assertLess(cuped_interval_width, no_cuped_interval_width)

    @freeze_time("2020-01-15T12:00:00Z")
    def test_cuped_adjusts_bayesian_statistical_result(self):
        metric = self._build_sum_metric()

        no_cuped_feature_flag = self.create_feature_flag("no-cuped-bayesian-experiment")
        no_cuped_experiment = self.create_experiment(
            name="no-cuped-bayesian-experiment",
            feature_flag=no_cuped_feature_flag,
            start_date=datetime(2020, 1, 10, 0, 0, 0),
            end_date=datetime(2020, 1, 15, 0, 0, 0),
        )
        no_cuped_experiment.stats_config = {"method": "bayesian"}
        no_cuped_experiment.save()

        cuped_feature_flag = self.create_feature_flag("cuped-bayesian-experiment")
        cuped_experiment = self.create_experiment(
            name="cuped-bayesian-experiment",
            feature_flag=cuped_feature_flag,
            start_date=datetime(2020, 1, 10, 0, 0, 0),
            end_date=datetime(2020, 1, 15, 0, 0, 0),
        )
        cuped_experiment.stats_config = {
            "method": "bayesian",
            "cuped": {"enabled": True, "lookback_days": 7},
        }
        cuped_experiment.save()

        self._create_correlated_data(no_cuped_feature_flag)
        self._create_correlated_data(cuped_feature_flag)
        flush_persons_and_events()

        no_cuped_result = self._run_metric(no_cuped_experiment, metric)
        cuped_result = self._run_metric(cuped_experiment, metric)

        assert cuped_result.baseline is not None
        assert no_cuped_result.variant_results is not None
        assert cuped_result.variant_results is not None
        no_cuped_variant = cast(ExperimentVariantResultBayesian, no_cuped_result.variant_results[0])
        cuped_variant = cast(ExperimentVariantResultBayesian, cuped_result.variant_results[0])

        self.assertEqual(cuped_result.baseline.covariate_sum, 1830)
        self.assertEqual(cuped_variant.covariate_sum, 1830)
        assert no_cuped_variant.credible_interval is not None
        assert cuped_variant.credible_interval is not None
        no_cuped_interval_width = no_cuped_variant.credible_interval[1] - no_cuped_variant.credible_interval[0]
        cuped_interval_width = cuped_variant.credible_interval[1] - cuped_variant.credible_interval[0]
        self.assertLess(cuped_interval_width, no_cuped_interval_width)

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

        self._create_correlated_data(feature_flag, create_pre_exposure_events=False)
        flush_persons_and_events()

        result = self._run_metric(experiment, self._build_sum_metric())

        assert result.baseline is not None
        assert result.variant_results is not None
        variant = cast(ExperimentVariantResultFrequentist, result.variant_results[0])
        self.assertEqual(result.baseline.covariate_sum, 0)
        self.assertEqual(result.baseline.covariate_sum_squares, 0)
        self.assertEqual(result.baseline.main_covariate_sum_product, 0)
        self.assertEqual(variant.covariate_sum, 0)
        self.assertEqual(variant.covariate_sum_squares, 0)
        self.assertEqual(variant.main_covariate_sum_product, 0)
        assert variant.p_value is not None

    @freeze_time("2020-01-15T12:00:00Z")
    def test_cuped_unique_session_metric_collects_distinct_covariates(self):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(
            feature_flag=feature_flag,
            start_date=datetime(2020, 1, 10, 0, 0, 0),
            end_date=datetime(2020, 1, 15, 0, 0, 0),
        )
        experiment.stats_config = {"method": "frequentist", "cuped": {"enabled": True, "lookback_days": 7}}
        experiment.save()

        _create_person(distinct_ids=["control_1"], team_id=self.team.pk)
        self._create_pageview(feature_flag, "control_1", "2020-01-09T12:00:00Z", "c_1_pre_a")
        self._create_pageview(feature_flag, "control_1", "2020-01-09T12:05:00Z", "c_1_pre_b")
        self._create_exposure(feature_flag, "control_1", "control", "2020-01-10T12:00:00Z")
        self._create_pageview(feature_flag, "control_1", "2020-01-10T13:00:00Z", "c_1_post")

        _create_person(distinct_ids=["control_2"], team_id=self.team.pk)
        self._create_exposure(feature_flag, "control_2", "control", "2020-01-10T12:00:00Z")
        self._create_pageview(feature_flag, "control_2", "2020-01-10T13:00:00Z", "c_2_post")

        _create_person(distinct_ids=["test_1"], team_id=self.team.pk)
        self._create_pageview(feature_flag, "test_1", "2020-01-09T12:00:00Z", "t_1_pre")
        self._create_exposure(feature_flag, "test_1", "test", "2020-01-10T12:00:00Z")
        self._create_pageview(feature_flag, "test_1", "2020-01-10T13:00:00Z", "t_1_post_a")
        self._create_pageview(feature_flag, "test_1", "2020-01-10T13:05:00Z", "t_1_post_b")

        _create_person(distinct_ids=["test_2"], team_id=self.team.pk)
        self._create_pageview(feature_flag, "test_2", "2020-01-09T12:00:00Z", "t_2_pre_a")
        self._create_pageview(feature_flag, "test_2", "2020-01-09T12:05:00Z", "t_2_pre_b")
        self._create_exposure(feature_flag, "test_2", "test", "2020-01-10T12:00:00Z")
        self._create_pageview(feature_flag, "test_2", "2020-01-10T13:00:00Z", "t_2_post")

        flush_persons_and_events()

        metric = ExperimentMeanMetric(
            source=EventsNode(
                event="$pageview",
                math=ExperimentMetricMathType.UNIQUE_SESSION,
            ),
        )
        result = self._run_metric(experiment, metric)

        assert result.baseline is not None
        assert result.variant_results is not None
        control_variant = result.baseline
        test_variant = result.variant_results[0]

        self.assertEqual(control_variant.sum, 2)
        self.assertEqual(control_variant.covariate_sum, 2)
        self.assertEqual(control_variant.covariate_sum_squares, 4)
        self.assertEqual(control_variant.main_covariate_sum_product, 2)

        self.assertEqual(test_variant.sum, 3)
        self.assertEqual(test_variant.covariate_sum, 3)
        self.assertEqual(test_variant.covariate_sum_squares, 5)
        self.assertEqual(test_variant.main_covariate_sum_product, 4)
