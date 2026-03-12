from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.models.experiment import Experiment, ExperimentMetricResult
from posthog.models.feature_flag import FeatureFlag
from posthog.temporal.experiments.activities import _check_significance_transition


@pytest.mark.django_db
class TestCheckSignificanceTransition(BaseTest):
    def _create_experiment(self) -> Experiment:
        flag = FeatureFlag.objects.create(
            team=self.team,
            key="test-flag",
            created_by=self.user,
        )
        return Experiment.objects.create(
            team=self.team,
            name="Test Experiment",
            feature_flag=flag,
            start_date=datetime(2024, 1, 1, tzinfo=ZoneInfo("UTC")),
        )

    @parameterized.expand(
        [
            ("no_previous_significant", None, True, True),
            ("no_previous_not_significant", None, False, False),
            ("previous_not_significant_new_significant", False, True, True),
            ("previous_significant_new_significant", True, True, False),
            ("previous_failed_new_significant", "no_result", True, True),
            ("previous_significant_new_not_significant", True, False, False),
        ]
    )
    @patch("posthog.temporal.experiments.activities.produce_internal_event")
    def test_significance_transition(
        self,
        _name: str,
        previous_significant: object,
        new_significant: bool,
        expect_event: bool,
        mock_produce: MagicMock,
    ) -> None:
        experiment = self._create_experiment()
        metric_uuid = "metric-123"
        fingerprint = "abc123"
        query_to_utc = datetime(2024, 1, 10, tzinfo=ZoneInfo("UTC"))

        if previous_significant is not None:
            if previous_significant == "no_result":
                # Previous result failed — no result dict
                ExperimentMetricResult.objects.create(
                    experiment=experiment,
                    metric_uuid=metric_uuid,
                    fingerprint=fingerprint,
                    query_from=datetime(2024, 1, 1, tzinfo=ZoneInfo("UTC")),
                    query_to=query_to_utc - timedelta(days=1),
                    status=ExperimentMetricResult.Status.FAILED,
                    result=None,
                )
            else:
                ExperimentMetricResult.objects.create(
                    experiment=experiment,
                    metric_uuid=metric_uuid,
                    fingerprint=fingerprint,
                    query_from=datetime(2024, 1, 1, tzinfo=ZoneInfo("UTC")),
                    query_to=query_to_utc - timedelta(days=1),
                    status=ExperimentMetricResult.Status.COMPLETED,
                    result={"significant": previous_significant, "significance_code": "significant"},
                )

        result_dict = {
            "significant": new_significant,
            "significance_code": "significant" if new_significant else "low_win_probability",
        }

        _check_significance_transition(experiment, metric_uuid, fingerprint, result_dict, query_to_utc)

        if expect_event:
            mock_produce.assert_called_once()
            call_kwargs = mock_produce.call_args
            event = call_kwargs.kwargs.get("event") or call_kwargs[1].get("event") or call_kwargs[0][1]
            assert event.event == "$experiment_metric_significant"
            assert event.properties["experiment_id"] == experiment.id
            assert event.properties["experiment_name"] == "Test Experiment"
            assert event.properties["metric_uuid"] == metric_uuid
            assert event.properties["experiment_url"] == f"/project/{self.team.pk}/experiments/{experiment.id}"
        else:
            mock_produce.assert_not_called()
