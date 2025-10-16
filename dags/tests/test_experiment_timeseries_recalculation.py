import datetime
from typing import cast
from zoneinfo import ZoneInfo

import pytest
from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

import dagster

from posthog.schema import ExperimentQueryResponse, ExperimentStatsBaseValidated, ExperimentVariantResultFrequentist

from posthog.models import Organization, Team, User
from posthog.models.experiment import Experiment, ExperimentMetricResult, ExperimentTimeseriesRecalculation
from posthog.models.feature_flag import FeatureFlag

from dags.experiment_timeseries_recalculation import experiment_timeseries_recalculation


@pytest.mark.django_db
class TestExperimentRecalculation(BaseTest):
    def test_experiment_timeseries_recalculation_asset(self):
        """Test that the recalculation asset processes all days and creates correct records."""
        org = Organization.objects.create(name="Test Org")
        team = Team.objects.create(organization=org, name="Test Team", timezone="America/New_York")
        user = User.objects.create(email="test@example.com")

        flag = FeatureFlag.objects.create(team=team, key="test-flag", created_by=user)
        experiment = Experiment.objects.create(
            name="Test Experiment",
            team=team,
            feature_flag=flag,
            start_date=datetime.datetime(2024, 12, 25, 10, 0, 0, tzinfo=ZoneInfo("UTC")),
            end_date=datetime.datetime(2024, 12, 27, 10, 0, 0, tzinfo=ZoneInfo("UTC")),  # 3 days in NYC timezone
        )

        metric_data = {
            "metric_type": "mean",
            "uuid": "test-metric-uuid",
            "source": {"kind": "EventsNode", "event": "test_event"},
        }
        recalculation_request = ExperimentTimeseriesRecalculation.objects.create(
            team=team,
            experiment=experiment,
            metric=metric_data,
            fingerprint="test-fingerprint",
            status=ExperimentTimeseriesRecalculation.Status.PENDING,
        )

        # Partition key format must match what the sensor creates
        partition_key = (
            f"recalculation_{recalculation_request.id}_"
            f"experiment_{experiment.id}_"
            f"metric_test-metric-uuid_test-fingerprint"
        )
        context = dagster.build_asset_context(partition_key=partition_key)

        mock_result = ExperimentQueryResponse(
            baseline=ExperimentStatsBaseValidated(key="control", number_of_samples=100, sum=1000, sum_squares=10000),
            variant_results=[
                ExperimentVariantResultFrequentist(
                    key="test", number_of_samples=110, sum=1100, sum_squares=11000, significant=False
                )
            ],
        )

        # Mock ClickHouse query results since we're only testing the recalculation processing logic
        with patch("dags.experiment_timeseries_recalculation.ExperimentQueryRunner") as mock_query_runner_class:
            mock_query_runner = MagicMock()
            mock_query_runner._calculate.return_value = mock_result
            mock_query_runner_class.return_value = mock_query_runner

            with patch(
                "dags.experiment_timeseries_recalculation.remove_step_sessions_from_experiment_result"
            ) as mock_remove_sessions:
                mock_remove_sessions.return_value = mock_result

                result = cast(dict, experiment_timeseries_recalculation(context))

        recalculation_request.refresh_from_db()
        assert recalculation_request.status == ExperimentTimeseriesRecalculation.Status.COMPLETED
        assert recalculation_request.last_successful_date == datetime.date(2024, 12, 27)

        metric_results = ExperimentMetricResult.objects.filter(
            experiment=experiment, metric_uuid="test-metric-uuid", fingerprint="test-fingerprint"
        ).order_by("query_to")

        assert len(metric_results) == 3

        # NYC is UTC-5 in December, so end-of-day boundaries are shifted
        expected_dates_utc = [
            datetime.datetime(2024, 12, 26, 5, 0, 0, tzinfo=ZoneInfo("UTC")),  # End of Dec 25 in EST
            datetime.datetime(2024, 12, 27, 5, 0, 0, tzinfo=ZoneInfo("UTC")),  # End of Dec 26 in EST
            datetime.datetime(2024, 12, 28, 5, 0, 0, tzinfo=ZoneInfo("UTC")),  # End of Dec 27 in EST
        ]

        for i, metric_result in enumerate(metric_results):
            assert metric_result.query_to == expected_dates_utc[i]
            assert metric_result.query_from == experiment.start_date
            assert metric_result.status == ExperimentMetricResult.Status.COMPLETED
            assert metric_result.result == mock_result.model_dump()

        assert result["recalculation_id"] == str(recalculation_request.id)
        assert result["experiment_id"] == experiment.id
        assert result["metric_uuid"] == "test-metric-uuid"
        assert result["days_processed"] == 3
        assert result["start_date"] == "2024-12-25"
        assert result["end_date"] == "2024-12-27"
