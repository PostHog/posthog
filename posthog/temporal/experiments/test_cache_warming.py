from datetime import datetime
from uuid import uuid4

from freezegun import freeze_time
from posthog.test.base import _create_event, _create_person, flush_persons_and_events
from unittest.mock import patch

from django.core.cache import cache
from django.test import override_settings

from posthog.schema import CachedExperimentQueryResponse, EventsNode, ExperimentMeanMetric, ExperimentQuery

from posthog.hogql_queries.experiments.experiment_metric_fingerprint import compute_metric_fingerprint
from posthog.hogql_queries.experiments.experiment_query_runner import ExperimentQueryRunner
from posthog.hogql_queries.experiments.test.experiment_query_runner.base import ExperimentQueryRunnerBaseTest
from posthog.hogql_queries.experiments.utils import get_experiment_stats_method
from posthog.hogql_queries.query_runner import ExecutionMode
from posthog.temporal.experiments.activities import _calculate_experiment_regular_metric_sync


@override_settings(IN_UNIT_TESTING=True)
class TestTemporalRecalcWarmsResponseCache(ExperimentQueryRunnerBaseTest):
    @freeze_time("2020-01-10T12:00:00Z")
    def test_temporal_activity_warms_query_cache(self):
        """
        After the daily Temporal recalc activity runs, a frontend /query
        request for the same experiment+metric should be served from cache
        instead of recomputing.
        """
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(
            feature_flag=feature_flag,
            start_date=datetime(2020, 1, 1, 0, 0, 0),
        )

        metric = ExperimentMeanMetric(uuid=str(uuid4()), source=EventsNode(event="purchase"))
        metric_dict = metric.model_dump(mode="json")
        experiment.metrics = [metric_dict]
        experiment.save()

        feature_flag_property = f"$feature/{feature_flag.key}"
        for variant in ("control", "test"):
            for i in range(5):
                distinct_id = f"user_{variant}_{i}"
                _create_person(distinct_ids=[distinct_id], team_id=self.team.pk)
                _create_event(
                    team=self.team,
                    event="$feature_flag_called",
                    distinct_id=distinct_id,
                    timestamp="2020-01-02T12:00:00Z",
                    properties={
                        feature_flag_property: variant,
                        "$feature_flag_response": variant,
                        "$feature_flag": feature_flag.key,
                    },
                )
                _create_event(
                    team=self.team,
                    event="purchase",
                    distinct_id=distinct_id,
                    timestamp="2020-01-02T12:01:00Z",
                    properties={feature_flag_property: variant},
                )
        flush_persons_and_events()

        # Build the ExperimentQuery exactly the way /query does, so the
        # cache key matches.
        frontend_query = ExperimentQuery.model_validate(
            {
                "kind": "ExperimentQuery",
                "experiment_id": experiment.id,
                "metric": metric_dict,
            }
        )

        cache.clear()

        # Two test-only workarounds: .func skips the @database_sync_to_async
        # wrapper, and patch stops the activity from closing the test's DB
        # connection mid-run. Same pattern as test_backfill.py.
        fingerprint = compute_metric_fingerprint(
            metric_dict,
            experiment.start_date,
            get_experiment_stats_method(experiment),
            experiment.exposure_criteria,
            only_count_matured_users=experiment.only_count_matured_users,
        )
        with patch("posthog.temporal.experiments.activities.close_old_connections"):
            activity_result = _calculate_experiment_regular_metric_sync.func(  # type: ignore[attr-defined]
                experiment.id, metric_dict["uuid"], fingerprint
            )
        self.assertTrue(activity_result.success, msg=activity_result.error_message)

        warm_response = ExperimentQueryRunner(query=frontend_query, team=self.team).run(
            execution_mode=ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE,
        )
        assert isinstance(warm_response, CachedExperimentQueryResponse)
        self.assertTrue(warm_response.is_cached)
