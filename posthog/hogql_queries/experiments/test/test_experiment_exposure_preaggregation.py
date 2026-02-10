from datetime import UTC, datetime

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, _create_person, flush_persons_and_events

from django.test import override_settings

from posthog.schema import (
    DateRange,
    EventsNode,
    ExperimentEventExposureConfig,
    ExperimentMeanMetric,
    ExperimentMetricMathType,
    IntervalType,
    MultipleVariantHandling,
)

from posthog.hogql.query import execute_hogql_query

from posthog.hogql_queries.experiments.experiment_query_builder import ExperimentQueryBuilder
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.models.feature_flag.feature_flag import FeatureFlag

from products.analytics_platform.backend.lazy_preaggregation.lazy_preaggregation_executor import (
    PreaggregationTable,
    ensure_preaggregated,
)


@override_settings(IN_UNIT_TESTING=True)
class TestExperimentExposurePreaggregation(ClickhouseTestMixin, APIBaseTest):
    def _create_feature_flag(self, key="test-experiment"):
        return FeatureFlag.objects.create(
            name=f"Test experiment flag: {key}",
            key=key,
            team=self.team,
            filters={
                "groups": [{"properties": [], "rollout_percentage": None}],
                "multivariate": {
                    "variants": [
                        {"key": "control", "name": "Control", "rollout_percentage": 50},
                        {"key": "test", "name": "Test", "rollout_percentage": 50},
                    ]
                },
            },
            created_by=self.user,
        )

    def _create_builder(self, feature_flag) -> ExperimentQueryBuilder:
        return ExperimentQueryBuilder(
            team=self.team,
            feature_flag_key=feature_flag.key,
            exposure_config=ExperimentEventExposureConfig(event="$feature_flag_called", properties=[]),
            filter_test_accounts=False,
            multiple_variant_handling=MultipleVariantHandling.EXCLUDE,
            variants=["control", "test"],
            date_range_query=QueryDateRange(
                date_range=DateRange(date_from="2024-01-01", date_to="2024-01-05"),
                team=self.team,
                interval=IntervalType.DAY,
                now=datetime.now(),
            ),
            entity_key="person_id",
            metric=ExperimentMeanMetric(
                source=EventsNode(event="purchase", math=ExperimentMetricMathType.TOTAL),
            ),
        )

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

    def _preaggregated_and_compare(self, builder, result):
        direct_query = builder._build_exposure_select_query()
        direct_response = execute_hogql_query(query_type="test", query=direct_query, team=self.team)

        job_id_strs = [str(job_id) for job_id in result.job_ids]
        preagg_query = builder._build_exposure_from_preaggregated(job_id_strs)
        preagg_response = execute_hogql_query(query_type="test", query=preagg_query, team=self.team)

        direct_rows = sorted(direct_response.results, key=lambda r: str(r[0]))
        preagg_rows = sorted(preagg_response.results, key=lambda r: str(r[0]))

        assert len(direct_rows) == len(preagg_rows)

        for direct, preagg in zip(direct_rows, preagg_rows):
            assert str(direct[0]) == str(preagg[0])
            assert direct[1] == preagg[1]
            assert direct[2] == preagg[2]
            assert direct[3] == preagg[3]

        return direct_rows

    def test_preaggregated_results_match_direct_scan_single_job(self):
        feature_flag = self._create_feature_flag()

        for i in range(5):
            _create_person(distinct_ids=[f"user_control_{i}"], team_id=self.team.pk)
            self._create_exposure_event(
                f"user_control_{i}", feature_flag, "control", datetime(2024, 1, 2, 12, 0, 0, tzinfo=UTC)
            )

        for i in range(7):
            _create_person(distinct_ids=[f"user_test_{i}"], team_id=self.team.pk)
            self._create_exposure_event(
                f"user_test_{i}", feature_flag, "test", datetime(2024, 1, 2, 14, 0, 0, tzinfo=UTC)
            )

        flush_persons_and_events()

        builder = self._create_builder(feature_flag)
        query_string, placeholders = builder.get_exposure_query_for_preaggregation()

        result = ensure_preaggregated(
            team=self.team,
            insert_query=query_string,
            time_range_start=datetime(2024, 1, 1, tzinfo=UTC),
            time_range_end=datetime(2024, 1, 5, tzinfo=UTC),
            table=PreaggregationTable.EXPERIMENT_EXPOSURES_PREAGGREGATED,
            placeholders=placeholders,
        )

        rows = self._preaggregated_and_compare(builder, result)
        assert len(rows) == 12  # 5 control + 7 test

    def test_preaggregated_results_match_direct_scan_multiple_jobs(self):
        feature_flag = self._create_feature_flag(key="multi-job-test")

        # 3 control users on Jan 2 only
        for i in range(3):
            _create_person(distinct_ids=[f"mj_control_{i}"], team_id=self.team.pk)
            self._create_exposure_event(
                f"mj_control_{i}", feature_flag, "control", datetime(2024, 1, 2, 12, 0, 0, tzinfo=UTC)
            )

        # 3 test users on Jan 4 only
        for i in range(3):
            _create_person(distinct_ids=[f"mj_test_{i}"], team_id=self.team.pk)
            self._create_exposure_event(
                f"mj_test_{i}", feature_flag, "test", datetime(2024, 1, 4, 14, 0, 0, tzinfo=UTC)
            )

        # 1 user with exposure events on BOTH Jan 2 and Jan 4
        _create_person(distinct_ids=["mj_both_days"], team_id=self.team.pk)
        self._create_exposure_event("mj_both_days", feature_flag, "control", datetime(2024, 1, 2, 10, 0, 0, tzinfo=UTC))
        self._create_exposure_event("mj_both_days", feature_flag, "control", datetime(2024, 1, 4, 10, 0, 0, tzinfo=UTC))

        flush_persons_and_events()

        builder = self._create_builder(feature_flag)
        query_string, placeholders = builder.get_exposure_query_for_preaggregation()

        # Phase 1: preagg Jan 1-3 (covers the Jan 2 events)
        ensure_preaggregated(
            team=self.team,
            insert_query=query_string,
            time_range_start=datetime(2024, 1, 1, tzinfo=UTC),
            time_range_end=datetime(2024, 1, 3, tzinfo=UTC),
            table=PreaggregationTable.EXPERIMENT_EXPOSURES_PREAGGREGATED,
            placeholders=placeholders,
        )

        # Phase 2: preagg Jan 1-5 (finds Jan 1-3 covered, creates new job for Jan 3-5)
        result = ensure_preaggregated(
            team=self.team,
            insert_query=query_string,
            time_range_start=datetime(2024, 1, 1, tzinfo=UTC),
            time_range_end=datetime(2024, 1, 5, tzinfo=UTC),
            table=PreaggregationTable.EXPERIMENT_EXPOSURES_PREAGGREGATED,
            placeholders=placeholders,
        )

        assert len(result.job_ids) == 2

        rows = self._preaggregated_and_compare(builder, result)
        assert len(rows) == 7  # 3 control + 3 test + 1 both
