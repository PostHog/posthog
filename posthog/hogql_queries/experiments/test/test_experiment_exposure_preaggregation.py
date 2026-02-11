from datetime import UTC, datetime
from typing import cast

from freezegun import freeze_time
from posthog.test.base import _create_event, _create_person, flush_persons_and_events
from unittest.mock import patch

from django.test import override_settings

from posthog.schema import (
    EventsNode,
    ExperimentMeanMetric,
    ExperimentMetricMathType,
    ExperimentQuery,
    ExperimentQueryResponse,
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

from products.analytics_platform.backend.lazy_preaggregation.lazy_preaggregation_executor import (
    PreaggregationTable,
    ensure_preaggregated,
)


@override_settings(IN_UNIT_TESTING=True)
class TestExperimentExposurePreaggregation(ExperimentQueryRunnerBaseTest):
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

    def _build_preaggregation_builder(self, experiment, feature_flag, metric) -> ExperimentQueryBuilder:
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

    def _preaggregated_and_compare(
        self, experiment, feature_flag, metric
    ) -> tuple[ExperimentQueryResponse, ExperimentQueryResponse]:
        """Run the same experiment through both paths and assert identical results."""
        # Path A: direct events scan
        experiment.exposure_preaggregation_enabled = False
        experiment.save()
        direct_result = self._run_experiment(experiment, metric)

        # Preaggreggate exposures
        builder = self._build_preaggregation_builder(experiment, feature_flag, metric)
        query_string, placeholders = builder.get_exposure_query_for_preaggregation()
        ensure_preaggregated(
            team=self.team,
            insert_query=query_string,
            time_range_start=experiment.start_date,
            time_range_end=experiment.end_date,
            table=PreaggregationTable.EXPERIMENT_EXPOSURES_PREAGGREGATED,
            placeholders=placeholders,
        )

        # Path B: preaggregated
        experiment.exposure_preaggregation_enabled = True
        experiment.save()
        preagg_result = self._run_experiment(experiment, metric)

        assert direct_result.baseline is not None
        assert preagg_result.baseline is not None
        assert direct_result.baseline.key == preagg_result.baseline.key
        assert direct_result.baseline.number_of_samples == preagg_result.baseline.number_of_samples
        assert direct_result.baseline.sum == preagg_result.baseline.sum

        assert direct_result.variant_results is not None
        assert preagg_result.variant_results is not None
        assert len(direct_result.variant_results) == len(preagg_result.variant_results)
        for i in range(len(direct_result.variant_results)):
            assert direct_result.variant_results[i].key == preagg_result.variant_results[i].key
            assert (
                direct_result.variant_results[i].number_of_samples == preagg_result.variant_results[i].number_of_samples
            )
            assert direct_result.variant_results[i].sum == preagg_result.variant_results[i].sum

        return direct_result, preagg_result

    @freeze_time("2024-01-10T12:00:00Z")
    def test_preaggregated_results_match_direct_scan(self):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(
            feature_flag=feature_flag,
            start_date=datetime(2024, 1, 1),
            end_date=datetime(2024, 1, 5),
        )

        metric = ExperimentMeanMetric(
            source=EventsNode(event="purchase", math=ExperimentMetricMathType.TOTAL),
        )
        experiment.metrics = [metric.model_dump(mode="json")]
        experiment.save()

        feature_flag_property = f"$feature/{feature_flag.key}"

        for i in range(5):
            _create_person(distinct_ids=[f"user_control_{i}"], team_id=self.team.pk)
            self._create_exposure_event(
                f"user_control_{i}", feature_flag, "control", datetime(2024, 1, 2, 12, 0, 0, tzinfo=UTC)
            )
            _create_event(
                team=self.team,
                event="purchase",
                distinct_id=f"user_control_{i}",
                timestamp=datetime(2024, 1, 2, 13, 0, 0, tzinfo=UTC),
                properties={feature_flag_property: "control"},
            )

        for i in range(7):
            _create_person(distinct_ids=[f"user_test_{i}"], team_id=self.team.pk)
            self._create_exposure_event(
                f"user_test_{i}", feature_flag, "test", datetime(2024, 1, 2, 14, 0, 0, tzinfo=UTC)
            )
            _create_event(
                team=self.team,
                event="purchase",
                distinct_id=f"user_test_{i}",
                timestamp=datetime(2024, 1, 2, 15, 0, 0, tzinfo=UTC),
                properties={feature_flag_property: "test"},
            )

        flush_persons_and_events()

        direct_result, preagg_result = self._preaggregated_and_compare(experiment, feature_flag, metric)
        assert direct_result.baseline is not None
        assert direct_result.baseline.number_of_samples == 5
        assert direct_result.variant_results is not None
        assert direct_result.variant_results[0].number_of_samples == 7

    @freeze_time("2024-01-10T12:00:00Z")
    def test_preaggregated_results_match_direct_scan_multiple_jobs(self):
        feature_flag = self.create_feature_flag(key="multi-job-test")
        experiment = self.create_experiment(
            feature_flag=feature_flag,
            start_date=datetime(2024, 1, 1),
            end_date=datetime(2024, 1, 5),
        )

        metric = ExperimentMeanMetric(
            source=EventsNode(event="purchase", math=ExperimentMetricMathType.TOTAL),
        )
        experiment.metrics = [metric.model_dump(mode="json")]
        experiment.save()

        feature_flag_property = f"$feature/{feature_flag.key}"

        # 3 control users on Jan 2
        for i in range(3):
            _create_person(distinct_ids=[f"mj_control_{i}"], team_id=self.team.pk)
            self._create_exposure_event(
                f"mj_control_{i}", feature_flag, "control", datetime(2024, 1, 2, 12, 0, 0, tzinfo=UTC)
            )
            _create_event(
                team=self.team,
                event="purchase",
                distinct_id=f"mj_control_{i}",
                timestamp=datetime(2024, 1, 2, 13, 0, 0, tzinfo=UTC),
                properties={feature_flag_property: "control"},
            )

        # 3 test users on Jan 4
        for i in range(3):
            _create_person(distinct_ids=[f"mj_test_{i}"], team_id=self.team.pk)
            self._create_exposure_event(
                f"mj_test_{i}", feature_flag, "test", datetime(2024, 1, 4, 14, 0, 0, tzinfo=UTC)
            )
            _create_event(
                team=self.team,
                event="purchase",
                distinct_id=f"mj_test_{i}",
                timestamp=datetime(2024, 1, 4, 15, 0, 0, tzinfo=UTC),
                properties={feature_flag_property: "test"},
            )

        # 1 user with exposures on BOTH Jan 2 and Jan 4 (spans two jobs)
        _create_person(distinct_ids=["mj_both_days"], team_id=self.team.pk)
        self._create_exposure_event("mj_both_days", feature_flag, "control", datetime(2024, 1, 2, 10, 0, 0, tzinfo=UTC))
        self._create_exposure_event("mj_both_days", feature_flag, "control", datetime(2024, 1, 4, 10, 0, 0, tzinfo=UTC))
        _create_event(
            team=self.team,
            event="purchase",
            distinct_id="mj_both_days",
            timestamp=datetime(2024, 1, 2, 11, 0, 0, tzinfo=UTC),
            properties={feature_flag_property: "control"},
        )

        flush_persons_and_events()

        # Preaggregating in two phases forces multiple jobs
        builder = self._build_preaggregation_builder(experiment, feature_flag, metric)
        query_string, placeholders = builder.get_exposure_query_for_preaggregation()

        # Phase 1: preagg Jan 1-3
        ensure_preaggregated(
            team=self.team,
            insert_query=query_string,
            time_range_start=datetime(2024, 1, 1, tzinfo=UTC),
            time_range_end=datetime(2024, 1, 3, tzinfo=UTC),
            table=PreaggregationTable.EXPERIMENT_EXPOSURES_PREAGGREGATED,
            placeholders=placeholders,
        )

        # Phase 2: preagg Jan 1-5 (finds Jan 1-3 already covered, creates second job for Jan 3-5)
        ensure_preaggregated(
            team=self.team,
            insert_query=query_string,
            time_range_start=datetime(2024, 1, 1, tzinfo=UTC),
            time_range_end=datetime(2024, 1, 5, tzinfo=UTC),
            table=PreaggregationTable.EXPERIMENT_EXPOSURES_PREAGGREGATED,
            placeholders=placeholders,
        )

        # Run through runner with preaggregation enabled
        experiment.exposure_preaggregation_enabled = True
        experiment.save()
        preagg_result = self._run_experiment(experiment, metric)

        # Run through runner without preaggregation
        experiment.exposure_preaggregation_enabled = False
        experiment.save()
        direct_result = self._run_experiment(experiment, metric)

        # Both paths should produce identical results
        assert direct_result.baseline is not None
        assert preagg_result.baseline is not None
        assert direct_result.baseline.number_of_samples == preagg_result.baseline.number_of_samples
        assert direct_result.baseline.sum == preagg_result.baseline.sum

        assert direct_result.variant_results is not None
        assert preagg_result.variant_results is not None
        for i in range(len(direct_result.variant_results)):
            assert (
                direct_result.variant_results[i].number_of_samples == preagg_result.variant_results[i].number_of_samples
            )
            assert direct_result.variant_results[i].sum == preagg_result.variant_results[i].sum

        # 4 control (3 + 1 both_days) and 3 test
        assert direct_result.baseline.number_of_samples == 4
        assert direct_result.variant_results[0].number_of_samples == 3

    @freeze_time("2024-01-10T12:00:00Z")
    def test_falls_back_to_events_scan_on_preaggregation_failure(self):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(
            feature_flag=feature_flag,
            start_date=datetime(2024, 1, 1),
            end_date=datetime(2024, 1, 5),
        )
        experiment.exposure_preaggregation_enabled = True

        metric = ExperimentMeanMetric(
            source=EventsNode(event="purchase", math=ExperimentMetricMathType.TOTAL),
        )
        experiment.metrics = [metric.model_dump(mode="json")]
        experiment.save()

        feature_flag_property = f"$feature/{feature_flag.key}"

        for i in range(3):
            _create_person(distinct_ids=[f"user_control_{i}"], team_id=self.team.pk)
            self._create_exposure_event(
                f"user_control_{i}", feature_flag, "control", datetime(2024, 1, 2, 12, 0, 0, tzinfo=UTC)
            )
            _create_event(
                team=self.team,
                event="purchase",
                distinct_id=f"user_control_{i}",
                timestamp=datetime(2024, 1, 2, 13, 0, 0, tzinfo=UTC),
                properties={feature_flag_property: "control"},
            )

        for i in range(3):
            _create_person(distinct_ids=[f"user_test_{i}"], team_id=self.team.pk)
            self._create_exposure_event(
                f"user_test_{i}", feature_flag, "test", datetime(2024, 1, 2, 14, 0, 0, tzinfo=UTC)
            )
            _create_event(
                team=self.team,
                event="purchase",
                distinct_id=f"user_test_{i}",
                timestamp=datetime(2024, 1, 2, 15, 0, 0, tzinfo=UTC),
                properties={feature_flag_property: "test"},
            )

        flush_persons_and_events()

        with patch.object(ExperimentQueryRunner, "_ensure_exposures_preaggregated", side_effect=Exception("boom")):
            result = self._run_experiment(experiment, metric)

        assert result.baseline is not None
        assert result.baseline.number_of_samples == 3
        assert result.variant_results is not None
        assert result.variant_results[0].number_of_samples == 3
