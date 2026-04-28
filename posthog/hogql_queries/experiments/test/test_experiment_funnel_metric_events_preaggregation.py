from datetime import UTC, datetime, timedelta
from typing import cast

from posthog.test.base import _create_event, _create_person

from django.test import override_settings

from posthog.schema import (
    EventsNode,
    ExperimentFunnelMetric,
    ExperimentQuery,
    ExperimentQueryResponse,
    FunnelConversionWindowTimeUnit,
    IntervalType,
)

from posthog.hogql_queries.experiments.base_query_utils import get_experiment_date_range
from posthog.hogql_queries.experiments.experiment_query_builder import (
    ExperimentQueryBuilder,
    get_exposure_config_params_for_builder,
)
from posthog.hogql_queries.experiments.experiment_query_runner import ExperimentQueryRunner
from posthog.hogql_queries.experiments.exposure_query_logic import get_entity_key
from posthog.hogql_queries.experiments.test.experiment_query_runner.base import ExperimentQueryRunnerBaseTest
from posthog.hogql_queries.utils.query_date_range import QueryDateRange

from products.analytics_platform.backend.lazy_computation.lazy_computation_executor import (
    LazyComputationTable,
    ensure_precomputed,
)


@override_settings(IN_UNIT_TESTING=True)
class TestExperimentFunnelMetricEventsPreaggregation(ExperimentQueryRunnerBaseTest):
    def _create_exposure_event(self, distinct_id, feature_flag, variant, timestamp):
        _create_event(
            team=self.team,
            event="$feature_flag_called",
            distinct_id=distinct_id,
            timestamp=timestamp,
            properties={
                f"$feature/{feature_flag.key}": variant,
                "$feature_flag_response": variant,
                "$feature_flag": feature_flag.key,
            },
        )

    def _run_experiment(self, experiment, metric) -> ExperimentQueryResponse:
        query = ExperimentQuery(experiment_id=experiment.id, kind="ExperimentQuery", metric=metric)
        runner = ExperimentQueryRunner(query=query, team=self.team)
        return cast(ExperimentQueryResponse, runner.calculate())

    def _build_lazy_computation_builder(self, experiment, feature_flag, metric) -> ExperimentQueryBuilder:
        exposure_config, multiple_variant_handling, filter_test_accounts = get_exposure_config_params_for_builder(
            experiment.exposure_criteria
        )
        date_range = get_experiment_date_range(experiment, self.team, None)
        return ExperimentQueryBuilder(
            team=self.team,
            feature_flag_key=feature_flag.key,
            exposure_config=exposure_config,
            filter_test_accounts=filter_test_accounts,
            multiple_variant_handling=multiple_variant_handling,
            variants=[v["key"] for v in feature_flag.variants],
            date_range_query=QueryDateRange(
                date_range=date_range, team=self.team, interval=IntervalType.DAY, now=datetime.now()
            ),
            entity_key=get_entity_key(feature_flag.filters.get("aggregation_group_type_index")),
            metric=metric,
        )

    def _precompute_and_compare(
        self, experiment, feature_flag, metric
    ) -> tuple[ExperimentQueryResponse, ExperimentQueryResponse]:
        """Run the same experiment through both paths and assert identical results."""
        # Path A: direct events scan
        self._disable_precomputation()
        experiment.save()
        direct_result = self._run_experiment(experiment, metric)

        builder = self._build_lazy_computation_builder(experiment, feature_flag, metric)

        # Precompute exposures
        exposure_query_string, exposure_placeholders = builder.get_exposure_query_for_precomputation()
        ensure_precomputed(
            team=self.team,
            insert_query=exposure_query_string,
            time_range_start=experiment.start_date,
            time_range_end=experiment.end_date,
            table=LazyComputationTable.EXPERIMENT_EXPOSURES_PREAGGREGATED,
            placeholders=exposure_placeholders,
        )

        # Precompute metric events
        metric_query_string, metric_placeholders = builder.get_funnel_metric_events_query_for_precomputation()
        ensure_precomputed(
            team=self.team,
            insert_query=metric_query_string,
            time_range_start=experiment.start_date,
            time_range_end=experiment.end_date,
            table=LazyComputationTable.EXPERIMENT_METRIC_EVENTS_PREAGGREGATED,
            placeholders=metric_placeholders,
        )

        # Path B: precomputed
        self._enable_precomputation()
        experiment.save()
        precomputed_result = self._run_experiment(experiment, metric)

        assert direct_result.baseline is not None
        assert precomputed_result.baseline is not None
        assert direct_result.baseline.key == precomputed_result.baseline.key
        assert direct_result.baseline.number_of_samples == precomputed_result.baseline.number_of_samples
        assert direct_result.baseline.sum == precomputed_result.baseline.sum

        assert direct_result.variant_results is not None
        assert precomputed_result.variant_results is not None
        assert len(direct_result.variant_results) == len(precomputed_result.variant_results)
        for i in range(len(direct_result.variant_results)):
            assert direct_result.variant_results[i].key == precomputed_result.variant_results[i].key
            assert (
                direct_result.variant_results[i].number_of_samples
                == precomputed_result.variant_results[i].number_of_samples
            )
            assert direct_result.variant_results[i].sum == precomputed_result.variant_results[i].sum

        return direct_result, precomputed_result

    def test_basic_two_step_funnel(self):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(
            feature_flag=feature_flag,
            start_date=datetime(2024, 1, 1),
            end_date=datetime(2024, 1, 10),
        )

        metric = ExperimentFunnelMetric(series=[EventsNode(event="purchase")])
        experiment.metrics = [metric.model_dump(mode="json")]
        experiment.save()

        # Control: 3 exposed, 2 convert
        for i in range(3):
            _create_person(distinct_ids=[f"control_{i}"], team_id=self.team.pk)
            self._create_exposure_event(
                f"control_{i}", feature_flag, "control", datetime(2024, 1, 2, 12, 0, tzinfo=UTC)
            )
            if i < 2:
                _create_event(
                    team=self.team,
                    event="purchase",
                    distinct_id=f"control_{i}",
                    timestamp=datetime(2024, 1, 3, 12, 0, tzinfo=UTC),
                )

        # Test: 4 exposed, 3 convert
        for i in range(4):
            _create_person(distinct_ids=[f"test_{i}"], team_id=self.team.pk)
            self._create_exposure_event(f"test_{i}", feature_flag, "test", datetime(2024, 1, 2, 14, 0, tzinfo=UTC))
            if i < 3:
                _create_event(
                    team=self.team,
                    event="purchase",
                    distinct_id=f"test_{i}",
                    timestamp=datetime(2024, 1, 3, 14, 0, tzinfo=UTC),
                )

        direct_result, precomputed_result = self._precompute_and_compare(experiment, feature_flag, metric)
        assert direct_result.baseline is not None
        assert direct_result.baseline.number_of_samples == 3
        assert direct_result.baseline.sum == 2.0

    def test_three_step_funnel(self):
        feature_flag = self.create_feature_flag(key="three-step-test")
        experiment = self.create_experiment(
            feature_flag=feature_flag,
            start_date=datetime(2024, 1, 1),
            end_date=datetime(2024, 1, 10),
        )

        metric = ExperimentFunnelMetric(
            series=[
                EventsNode(event="pageview"),
                EventsNode(event="purchase"),
            ],
        )
        experiment.metrics = [metric.model_dump(mode="json")]
        experiment.save()

        # Control: 4 exposed, 3 reach pageview, 2 reach purchase
        for i in range(4):
            _create_person(distinct_ids=[f"control_{i}"], team_id=self.team.pk)
            self._create_exposure_event(
                f"control_{i}", feature_flag, "control", datetime(2024, 1, 2, 10, 0, tzinfo=UTC)
            )
            if i < 3:
                _create_event(
                    team=self.team,
                    event="pageview",
                    distinct_id=f"control_{i}",
                    timestamp=datetime(2024, 1, 2, 11, 0, tzinfo=UTC),
                )
            if i < 2:
                _create_event(
                    team=self.team,
                    event="purchase",
                    distinct_id=f"control_{i}",
                    timestamp=datetime(2024, 1, 2, 12, 0, tzinfo=UTC),
                )

        # Test: 5 exposed, 4 reach pageview, 3 reach purchase
        for i in range(5):
            _create_person(distinct_ids=[f"test_{i}"], team_id=self.team.pk)
            self._create_exposure_event(f"test_{i}", feature_flag, "test", datetime(2024, 1, 2, 14, 0, tzinfo=UTC))
            if i < 4:
                _create_event(
                    team=self.team,
                    event="pageview",
                    distinct_id=f"test_{i}",
                    timestamp=datetime(2024, 1, 2, 15, 0, tzinfo=UTC),
                )
            if i < 3:
                _create_event(
                    team=self.team,
                    event="purchase",
                    distinct_id=f"test_{i}",
                    timestamp=datetime(2024, 1, 2, 16, 0, tzinfo=UTC),
                )

        direct_result, precomputed_result = self._precompute_and_compare(experiment, feature_flag, metric)
        assert direct_result.baseline is not None
        assert direct_result.baseline.number_of_samples == 4
        assert direct_result.baseline.sum == 2.0

    def test_funnel_with_conversion_window(self):
        feature_flag = self.create_feature_flag(key="conv-window-test")
        experiment = self.create_experiment(
            feature_flag=feature_flag,
            start_date=datetime(2024, 1, 1),
            end_date=datetime(2024, 1, 5),
        )

        metric = ExperimentFunnelMetric(
            series=[EventsNode(event="purchase")],
            conversion_window=7,
            conversion_window_unit=FunnelConversionWindowTimeUnit.DAY,
        )
        experiment.metrics = [metric.model_dump(mode="json")]
        experiment.save()

        # User exposed on Jan 3, purchases on Jan 8 (within 7-day window, after experiment end)
        _create_person(distinct_ids=["user_late"], team_id=self.team.pk)
        self._create_exposure_event("user_late", feature_flag, "test", datetime(2024, 1, 3, 12, 0, tzinfo=UTC))
        _create_event(
            team=self.team,
            event="purchase",
            distinct_id="user_late",
            timestamp=datetime(2024, 1, 8, 12, 0, tzinfo=UTC),
        )

        # User exposed on Jan 2, purchases on Jan 3 (within window, within experiment)
        _create_person(distinct_ids=["user_early"], team_id=self.team.pk)
        self._create_exposure_event("user_early", feature_flag, "control", datetime(2024, 1, 2, 12, 0, tzinfo=UTC))
        _create_event(
            team=self.team,
            event="purchase",
            distinct_id="user_early",
            timestamp=datetime(2024, 1, 3, 12, 0, tzinfo=UTC),
        )

        # For precomputation, we need to extend time_range_end by conversion window
        builder = self._build_lazy_computation_builder(experiment, feature_flag, metric)

        # Path A: direct
        self._disable_precomputation()
        experiment.save()
        direct_result = self._run_experiment(experiment, metric)

        # Precompute exposures
        exposure_query_string, exposure_placeholders = builder.get_exposure_query_for_precomputation()
        ensure_precomputed(
            team=self.team,
            insert_query=exposure_query_string,
            time_range_start=experiment.start_date,
            time_range_end=experiment.end_date,
            table=LazyComputationTable.EXPERIMENT_EXPOSURES_PREAGGREGATED,
            placeholders=exposure_placeholders,
        )

        # Precompute metric events — extend end date by conversion window
        metric_query_string, metric_placeholders = builder.get_funnel_metric_events_query_for_precomputation()
        conversion_window_seconds = builder._get_conversion_window_seconds()
        metric_end_date = experiment.end_date + timedelta(seconds=conversion_window_seconds)
        ensure_precomputed(
            team=self.team,
            insert_query=metric_query_string,
            time_range_start=experiment.start_date,
            time_range_end=metric_end_date,
            table=LazyComputationTable.EXPERIMENT_METRIC_EVENTS_PREAGGREGATED,
            placeholders=metric_placeholders,
        )

        # Path B: precomputed
        self._enable_precomputation()
        experiment.save()
        precomputed_result = self._run_experiment(experiment, metric)

        assert direct_result.baseline is not None
        assert precomputed_result.baseline is not None
        assert direct_result.baseline.number_of_samples == precomputed_result.baseline.number_of_samples
        assert direct_result.baseline.sum == precomputed_result.baseline.sum

        assert direct_result.variant_results is not None
        assert precomputed_result.variant_results is not None
        for i in range(len(direct_result.variant_results)):
            assert (
                direct_result.variant_results[i].number_of_samples
                == precomputed_result.variant_results[i].number_of_samples
            )
            assert direct_result.variant_results[i].sum == precomputed_result.variant_results[i].sum
