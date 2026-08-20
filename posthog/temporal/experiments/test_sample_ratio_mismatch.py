from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.schema import SampleRatioMismatch

from posthog.temporal.experiments.utils import check_sample_ratio_mismatch

from products.experiments.backend.models.experiment import Experiment
from products.feature_flags.backend.models.feature_flag import FeatureFlag

METRIC_UUID = "metric-1"
METRIC = {"uuid": METRIC_UUID, "metric_type": "mean", "source": {"kind": "EventsNode", "event": "$pageview"}}

# Total 10,000 exposures, 6000/4000 against a 50/50 split — well past the 3σ band with a tiny p-value.
SKEWED = SimpleNamespace(
    sample_ratio_mismatch=SampleRatioMismatch(expected={"control": 5000.0, "test": 5000.0}, p_value=1e-9),
    total_exposures={"control": 6000, "test": 4000},
)
# Balanced at the same volume — nothing to alert on.
BALANCED = SimpleNamespace(
    sample_ratio_mismatch=SampleRatioMismatch(expected={"control": 5000.0, "test": 5000.0}, p_value=1.0),
    total_exposures={"control": 5000, "test": 5000},
)


@pytest.mark.django_db
class TestCheckSampleRatioMismatch(BaseTest):
    def _create_experiment(self, *, key: str = "srm-flag", end_date: datetime | None = None) -> Experiment:
        flag = FeatureFlag.objects.create(
            team=self.team,
            key=key,
            created_by=self.user,
            filters={
                "multivariate": {
                    "variants": [
                        {"key": "control", "rollout_percentage": 50},
                        {"key": "test", "rollout_percentage": 50},
                    ]
                }
            },
        )
        return Experiment.objects.create(
            team=self.team,
            name="SRM Experiment",
            feature_flag=flag,
            created_by=self.user,
            start_date=datetime(2024, 1, 1, tzinfo=ZoneInfo("UTC")),
            end_date=end_date,
            metrics=[METRIC],
        )

    @parameterized.expand([("skewed_fires", SKEWED, True), ("balanced_quiet", BALANCED, False)])
    @patch("posthog.temporal.experiments.utils.create_notification")
    @patch("posthog.temporal.experiments.utils.ExperimentExposuresQueryRunner")
    def test_fires_only_when_gate_crosses(
        self,
        _name: str,
        exposure_result: SimpleNamespace,
        expect_notification: bool,
        mock_runner: MagicMock,
        mock_create: MagicMock,
    ) -> None:
        mock_runner.return_value.run.return_value = exposure_result
        experiment = self._create_experiment()

        check_sample_ratio_mismatch(experiment, METRIC_UUID)

        if expect_notification:
            mock_create.assert_called_once()
            data = mock_create.call_args.args[0]
            assert data.notification_type.value == "experiment_sample_ratio_mismatch"
            assert data.target_id == str(self.user.id)
            assert data.resource_id == str(experiment.id)
            # The run marker keeps a relaunch (new version) from being blocked by the prior run's alert.
            assert data.idempotency_key == f"experiment_srm:{experiment.id}:{experiment.version}"
        else:
            mock_create.assert_not_called()

    @patch("posthog.temporal.experiments.utils.create_notification")
    @patch("posthog.temporal.experiments.utils.ExperimentExposuresQueryRunner")
    def test_skips_non_owning_metric(self, mock_runner: MagicMock, mock_create: MagicMock) -> None:
        experiment = self._create_experiment()

        check_sample_ratio_mismatch(experiment, "some-other-metric")

        # Only the owning metric runs the exposures query, so the experiment's other metrics skip.
        mock_runner.assert_not_called()
        mock_create.assert_not_called()

    @patch("posthog.temporal.experiments.utils.create_notification")
    @patch("posthog.temporal.experiments.utils.ExperimentExposuresQueryRunner")
    def test_skips_stopped_experiment(self, mock_runner: MagicMock, mock_create: MagicMock) -> None:
        experiment = self._create_experiment(end_date=datetime(2024, 2, 1, tzinfo=ZoneInfo("UTC")))

        check_sample_ratio_mismatch(experiment, METRIC_UUID)

        # A stopped experiment must not even run the exposure query.
        mock_runner.assert_not_called()
        mock_create.assert_not_called()
