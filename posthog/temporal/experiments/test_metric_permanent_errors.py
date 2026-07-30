from datetime import timedelta
from uuid import uuid4

from freezegun import freeze_time
from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.test import override_settings
from django.utils import timezone

from parameterized import parameterized

from posthog.schema import EventsNode, ExperimentMeanMetric

from posthog.hogql.errors import SyntaxError as HogQLSyntaxError

from posthog.temporal.experiments.activities import (
    _calculate_experiment_regular_metric_sync,
    _calculate_experiment_saved_metric_sync,
)

from products.experiments.backend.models.experiment import (
    Experiment,
    ExperimentMetricResult,
    ExperimentSavedMetric,
    ExperimentToSavedMetric,
)
from products.feature_flags.backend.models.feature_flag import FeatureFlag

HOGQL_ERROR_MESSAGE = "trailing tokens after expression: 'NOT'"


@override_settings(IN_UNIT_TESTING=True)
class TestPermanentMetricErrors(APIBaseTest):
    def _create_experiment_with_metric(self, saved: bool) -> tuple[int, dict]:
        feature_flag = FeatureFlag.objects.create(
            name="Test experiment flag",
            key="test-experiment",
            team=self.team,
            filters={
                "groups": [{"properties": [], "rollout_percentage": None}],
                "multivariate": {
                    "variants": [
                        {"key": "control", "rollout_percentage": 50},
                        {"key": "test", "rollout_percentage": 50},
                    ]
                },
            },
            created_by=self.user,
        )
        experiment = Experiment.objects.create(
            name="test-experiment",
            team=self.team,
            feature_flag=feature_flag,
            start_date=timezone.now() - timedelta(days=5),
        )
        metric_dict = ExperimentMeanMetric(uuid=str(uuid4()), source=EventsNode(event="purchase")).model_dump(
            mode="json"
        )

        if saved:
            saved_metric = ExperimentSavedMetric.objects.create(
                name="test saved metric",
                team=self.team,
                query=metric_dict,
                created_by=self.user,
            )
            ExperimentToSavedMetric.objects.create(
                experiment=experiment,
                saved_metric=saved_metric,
                metadata={"type": "primary"},
            )
        else:
            experiment.metrics = [metric_dict]
            experiment.save()

        return experiment.id, metric_dict

    @parameterized.expand(
        [
            ("regular", False, _calculate_experiment_regular_metric_sync),
            ("saved", True, _calculate_experiment_saved_metric_sync),
        ]
    )
    @freeze_time("2020-01-10T12:00:00Z")
    def test_invalid_user_hogql_is_terminal_and_not_retried(self, _name, saved, activity):
        experiment_id, metric_dict = self._create_experiment_with_metric(saved)

        with (
            patch("posthog.temporal.experiments.activities.close_old_connections"),
            patch("posthog.temporal.experiments.activities.ExperimentQueryRunner") as mock_runner_class,
            patch(
                "posthog.temporal.experiments.activities.capture_experiment_metric_error_event"
            ) as mock_capture_error,
        ):
            mock_runner_class.return_value.run.side_effect = HogQLSyntaxError(HOGQL_ERROR_MESSAGE)

            result = activity.func(experiment_id, metric_dict["uuid"], "fingerprint")

        # Returned, not raised — a permanent user-config error must not burn Temporal retries.
        assert result.success is False
        assert result.error_message == HOGQL_ERROR_MESSAGE

        result_row = ExperimentMetricResult.objects.get(experiment_id=experiment_id, metric_uuid=metric_dict["uuid"])
        assert result_row.status == ExperimentMetricResult.Status.FAILED
        assert result_row.error_message == HOGQL_ERROR_MESSAGE

        # Terminal on the first attempt, so the error event is emitted right away.
        assert mock_capture_error.call_count == 1
