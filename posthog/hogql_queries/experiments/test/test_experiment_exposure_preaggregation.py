from datetime import UTC, datetime

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, _create_person, flush_persons_and_events

from django.test import override_settings
from django.utils import timezone

from posthog.schema import (
    EventsNode,
    ExperimentEventExposureConfig,
    ExperimentMeanMetric,
    ExperimentMetricMathType,
    ExperimentQuery,
    IntervalType,
    MultipleVariantHandling,
)

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.preaggregation.experiment_exposures_sql import DISTRIBUTED_EXPERIMENT_EXPOSURES_TABLE
from posthog.hogql_queries.experiments.experiment_query_builder import ExperimentQueryBuilder
from posthog.hogql_queries.experiments.experiment_query_runner import ExperimentQueryRunner
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.models.experiment import Experiment
from posthog.models.feature_flag.feature_flag import FeatureFlag


@override_settings(IN_UNIT_TESTING=True)
class TestExperimentExposurePreaggregation(ClickhouseTestMixin, APIBaseTest):
    """
    Tests the integration between ExperimentQueryRunner and the lazy preaggregation system.

    When an experiment query runs, we preaggregate exposure data (which users saw which variant)
    into a ClickHouse table. This avoids re-scanning events on every query. The preaggregation
    is tracked via PostgreSQL jobs that record what's been computed.
    """

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

    def create_experiment(self, feature_flag, start_date: datetime, end_date: datetime):
        return Experiment.objects.create(
            name="test-experiment",
            team=self.team,
            feature_flag=feature_flag,
            start_date=timezone.make_aware(start_date),
            end_date=timezone.make_aware(end_date),
            exposure_criteria=None,
        )

    def _create_exposure_events(self, feature_flag):
        feature_flag_property = f"$feature/{feature_flag.key}"

        for i in range(5):
            _create_person(distinct_ids=[f"user_control_{i}"], team_id=self.team.pk)
            _create_event(
                team=self.team,
                event="$feature_flag_called",
                distinct_id=f"user_control_{i}",
                timestamp=datetime(2024, 1, 2, 12, 0, 0, tzinfo=UTC),
                properties={
                    feature_flag_property: "control",
                    "$feature_flag_response": "control",
                    "$feature_flag": feature_flag.key,
                },
            )

        for i in range(7):
            _create_person(distinct_ids=[f"user_test_{i}"], team_id=self.team.pk)
            _create_event(
                team=self.team,
                event="$feature_flag_called",
                distinct_id=f"user_test_{i}",
                timestamp=datetime(2024, 1, 2, 14, 0, 0, tzinfo=UTC),
                properties={
                    feature_flag_property: "test",
                    "$feature_flag_response": "test",
                    "$feature_flag": feature_flag.key,
                },
            )

        flush_persons_and_events()

    def _create_query_builder(self, feature_flag) -> ExperimentQueryBuilder:
        """Create a query builder for testing."""
        date_range_query = QueryDateRange(
            date_range={"date_from": "2024-01-01", "date_to": "2024-01-05"},
            team=self.team,
            interval=IntervalType.DAY,
            now=datetime.now(),
        )

        return ExperimentQueryBuilder(
            team=self.team,
            feature_flag_key=feature_flag.key,
            exposure_config=ExperimentEventExposureConfig(event="$feature_flag_called", properties=[]),
            filter_test_accounts=False,
            multiple_variant_handling=MultipleVariantHandling.EXCLUDE,
            variants=["control", "test"],
            date_range_query=date_range_query,
            entity_key="person_id",
            metric=ExperimentMeanMetric(
                source=EventsNode(event="purchase", math=ExperimentMetricMathType.TOTAL),
            ),
        )

    def test_ensure_exposures_preaggregated_creates_jobs_and_data(self):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag, datetime(2024, 1, 1), datetime(2024, 1, 5))
        self._create_exposure_events(feature_flag)

        builder = self._create_query_builder(feature_flag)
        query = ExperimentQuery(
            experiment_id=experiment.id,
            metric=ExperimentMeanMetric(
                source=EventsNode(event="purchase", math=ExperimentMetricMathType.TOTAL),
            ),
        )
        runner = ExperimentQueryRunner(team=self.team, query=query)

        result = runner._ensure_exposures_preaggregated(builder)

        assert result.ready is True

        # ClickHouse has the computed exposure data
        job_id_strs = [str(job_id) for job_id in result.job_ids]
        row_count = sync_execute(
            f"SELECT COUNT(*) FROM {DISTRIBUTED_EXPERIMENT_EXPOSURES_TABLE()} WHERE team_id = %(team_id)s AND job_id IN %(job_ids)s",
            {"team_id": self.team.id, "job_ids": job_id_strs},
        )[0][0]
        assert row_count == 12  # 5 control + 7 test users
