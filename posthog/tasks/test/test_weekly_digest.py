from datetime import timedelta
from unittest.mock import MagicMock, patch
from uuid import uuid4

from django.utils.timezone import now
from freezegun import freeze_time

from posthog.models import Dashboard, EventDefinition, Experiment, FeatureFlag, Survey
from posthog.session_recordings.models.session_recording_playlist import (
    SessionRecordingPlaylist,
)
from posthog.tasks.weekly_digest import send_all_weekly_digest_reports
from posthog.test.base import APIBaseTest
from posthog.warehouse.models import ExternalDataSource


@freeze_time("2024-01-01T00:01:00Z")  # A Monday
class TestWeeklyDigestReport(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.distinct_id = str(uuid4())

    @freeze_time("2024-01-20T00:01:00Z")
    @patch("posthog.tasks.weekly_digest.capture_report")
    def test_weekly_digest_report(self, mock_capture: MagicMock) -> None:
        # Create test data from "last week"
        with freeze_time("2024-01-15T00:01:00Z"):
            # Create a dashboard
            dashboard = Dashboard.objects.create(
                team=self.team,
                name="Test Dashboard",
            )

            # Create an event definition
            event_definition = EventDefinition.objects.create(
                team=self.team,
                name="Test Event",
            )

            # Create a playlist
            playlist = SessionRecordingPlaylist.objects.create(
                team=self.team,
                name="Test Playlist",
            )

            # Create experiments
            # this flag should not be included in the digest
            flag_for_launched_experiment = FeatureFlag.objects.create(
                team=self.team,
                name="Feature Flag for Experiment My experiment 1",
                key="flag-for-launched-experiment",
            )
            launched_experiment = Experiment.objects.create(
                team=self.team,
                name="Launched Experiment",
                start_date=now(),
                feature_flag=flag_for_launched_experiment,
            )

            # Create external data source
            external_data_source = ExternalDataSource.objects.create(
                team=self.team,
                source_id="test_source",
                connection_id="test_connection",
                status="completed",
                source_type="Stripe",
            )

            # Create a survey
            # this flag should not be included in the digest since it's generated for the survey
            flag_for_survey = FeatureFlag.objects.create(
                team=self.team,
                name="Targeting flag for survey My survey",
                key="feature-flag-for-survey",
            )
            survey = Survey.objects.create(
                team=self.team,
                name="Test Survey",
                description="Test Description",
                start_date=now(),
                targeting_flag=flag_for_survey,
            )

            # Create a feature flag
            feature_flag = FeatureFlag.objects.create(
                team=self.team,
                name="Test Flag",
                key="test-flag",
            )

        with freeze_time("2024-01-10T00:01:00Z"):
            # this flag should not be included in the digest
            flag_for_completed_experiment = FeatureFlag.objects.create(
                team=self.team,
                name="Feature Flag for Experiment My experiment 2",
                key="feature-flag-for-completed-experiment",
            )
            # completed experiment is not included in the list of launched experiments
            # but is included in the list of completed experiments
            completed_experiment = Experiment.objects.create(
                team=self.team,
                name="Completed Experiment",
                start_date=now() + timedelta(days=1),
                end_date=now() + timedelta(days=6),
                feature_flag=flag_for_completed_experiment,
            )

        # Run the weekly digest report task
        send_all_weekly_digest_reports()

        # Check that the capture event was called with the correct data
        expected_properties = {
            "team_id": self.team.id,
            "team_name": self.team.name,
            "template": "weekly_digest_report",
            "new_dashboards_in_last_7_days": [
                {
                    "name": "Test Dashboard",
                    "id": dashboard.id,
                }
            ],
            "new_event_definitions_in_last_7_days": [
                {
                    "name": "Test Event",
                    "id": event_definition.id,
                }
            ],
            "new_playlists_created_in_last_7_days": [
                {
                    "name": "Test Playlist",
                    "id": playlist.short_id,
                }
            ],
            "new_experiments_launched_in_last_7_days": [
                {
                    "name": "Launched Experiment",
                    "id": launched_experiment.id,
                    "start_date": launched_experiment.start_date.isoformat(),
                }
            ],
            "new_experiments_completed_in_last_7_days": [
                {
                    "name": "Completed Experiment",
                    "id": completed_experiment.id,
                    "start_date": completed_experiment.start_date.isoformat(),
                    "end_date": completed_experiment.end_date.isoformat(),
                }
            ],
            "new_external_data_sources_connected_in_last_7_days": [
                {
                    "source_type": "Stripe",
                    "id": external_data_source.id,
                }
            ],
            "new_surveys_launched_in_last_7_days": [
                {
                    "name": "Test Survey",
                    "id": survey.id,
                    "start_date": survey.start_date.isoformat(),
                    "description": "Test Description",
                }
            ],
            "new_feature_flags_created_in_last_7_days": [
                {
                    "name": "Test Flag",
                    "id": feature_flag.id,
                    "key": "test-flag",
                }
            ],
        }

        mock_capture.delay.assert_called_once_with(
            capture_event_name="transactional email",
            team_id=self.team.id,
            full_report_dict=expected_properties,
            send_for_all_members=True,
        )

    @patch("posthog.tasks.weekly_digest.capture_report")
    def test_weekly_digest_report_dry_run(self, mock_capture: MagicMock) -> None:
        send_all_weekly_digest_reports(dry_run=True)
        mock_capture.delay.assert_not_called()
