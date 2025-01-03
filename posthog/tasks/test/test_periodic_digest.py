from datetime import datetime, timedelta
from unittest.mock import ANY, MagicMock, patch
from uuid import uuid4

from django.utils.timezone import now
from freezegun import freeze_time

from posthog.models import Dashboard, EventDefinition, Experiment, FeatureFlag, Survey
from posthog.models.messaging import MessagingRecord
from posthog.session_recordings.models.session_recording_playlist import (
    SessionRecordingPlaylist,
)
from posthog.tasks.periodic_digest import send_all_periodic_digest_reports
from posthog.test.base import APIBaseTest
from posthog.warehouse.models import ExternalDataSource


@freeze_time("2024-01-01T00:01:00Z")  # A Monday
class TestPeriodicDigestReport(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.distinct_id = str(uuid4())

    @freeze_time("2024-01-20T00:01:00Z")
    @patch("posthog.tasks.periodic_digest.capture_report")
    def test_periodic_digest_report(self, mock_capture: MagicMock) -> None:
        # Create test data from "last week"
        with freeze_time("2024-01-15T00:01:00Z"):
            # Create a dashboard
            dashboard = Dashboard.objects.create(
                team=self.team,
                name="Test Dashboard",
            )

            #  create a dashboard that is generated for a feature flag, should be excluded from the digest
            Dashboard.objects.create(
                team=self.team,
                name="Generated Dashboard: test-flag Usage",
            )

            # Create an event definition
            event_definition = EventDefinition.objects.create(
                team=self.team,
                name="Test Event",
            )

            # Create playlists - one with name, one without name, one with empty string name
            playlist = SessionRecordingPlaylist.objects.create(
                team=self.team,
                name="Test Playlist",
            )
            # These should be excluded from the digest
            SessionRecordingPlaylist.objects.create(
                team=self.team,
                name=None,
            )
            SessionRecordingPlaylist.objects.create(
                team=self.team,
                name="",
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
                start_date=now() + timedelta(days=6),
                end_date=now() + timedelta(days=7),
                feature_flag=flag_for_completed_experiment,
            )

        # Run the periodic digest report task
        send_all_periodic_digest_reports()

        # Check that the capture event was called with the correct data
        expected_properties = {
            "team_id": self.team.id,
            "team_name": self.team.name,
            "template_name": "periodic_digest_report",
            "users_who_logged_in": [],
            "users_who_logged_in_count": 0,
            "users_who_signed_up": [],
            "users_who_signed_up_count": 0,
            "period": {
                "end_inclusive": "2024-01-20T00:00:00+00:00",
                "start_inclusive": "2024-01-13T00:00:00+00:00",
            },
            "plugins_enabled": {},
            "plugins_installed": {},
            "product": "open source",
            "realm": "hosted-clickhouse",
            "site_url": "http://localhost:8010",
            "table_sizes": ANY,
            "clickhouse_version": ANY,
            "deployment_infrastructure": "unknown",
            "helm": {},
            "instance_tag": "none",
            "new_dashboards": [
                {
                    "name": "Test Dashboard",
                    "id": dashboard.id,
                }
            ],
            "new_event_definitions": [
                {
                    "name": "Test Event",
                    "id": event_definition.id,
                }
            ],
            "new_playlists": [
                {
                    "name": "Test Playlist",
                    "id": playlist.short_id,
                }
            ],
            "new_experiments_launched": [
                {
                    "name": "Launched Experiment",
                    "id": launched_experiment.id,
                    "start_date": launched_experiment.start_date.isoformat(),  # type: ignore
                }
            ],
            "new_experiments_completed": [
                {
                    "name": "Completed Experiment",
                    "id": completed_experiment.id,
                    "start_date": completed_experiment.start_date.isoformat(),  # type: ignore
                    "end_date": completed_experiment.end_date.isoformat(),  # type: ignore
                }
            ],
            "new_external_data_sources": [
                {
                    "source_type": "Stripe",
                    "id": external_data_source.id,
                }
            ],
            "new_surveys_launched": [
                {
                    "name": "Test Survey",
                    "id": survey.id,
                    "start_date": survey.start_date.isoformat(),  # type: ignore
                    "description": "Test Description",
                }
            ],
            "new_feature_flags": [
                {
                    "name": "Test Flag",
                    "id": feature_flag.id,
                    "key": "test-flag",
                }
            ],
            "digest_items_with_data": 8,
        }

        mock_capture.delay.assert_called_once_with(
            capture_event_name="transactional email",
            team_id=self.team.id,
            full_report_dict=expected_properties,
            send_for_all_members=True,
        )

    @patch("posthog.tasks.periodic_digest.capture_report")
    def test_periodic_digest_report_dry_run(self, mock_capture: MagicMock) -> None:
        send_all_periodic_digest_reports(dry_run=True)
        mock_capture.delay.assert_not_called()

    @patch("posthog.tasks.periodic_digest.capture_report")
    def test_periodic_digest_report_custom_dates(self, mock_capture: MagicMock) -> None:
        # Create test data
        with freeze_time("2024-01-15T00:01:00Z"):
            dashboard = Dashboard.objects.create(
                team=self.team,
                name="Test Dashboard",
            )
        with freeze_time("2024-01-13T00:01:00Z"):
            # outside the range, should be excluded
            Dashboard.objects.create(
                team=self.team,
                name="Test Dashboard",
            )

        with freeze_time("2024-01-16T00:01:00Z"):
            end_date = datetime.now()
            begin_date = end_date - timedelta(days=2)

        # Run the periodic digest report task with custom dates
        send_all_periodic_digest_reports(begin_date=begin_date.isoformat(), end_date=end_date.isoformat())

        # Check that the capture event was called with the correct data
        expected_properties = {
            "team_id": self.team.id,
            "team_name": self.team.name,
            "template_name": "periodic_digest_report",
            "users_who_logged_in": [],
            "users_who_logged_in_count": 0,
            "users_who_signed_up": [],
            "users_who_signed_up_count": 0,
            "period": {
                "end_inclusive": "2024-01-16T00:01:00",
                "start_inclusive": "2024-01-14T00:01:00",
            },
            "plugins_enabled": {},
            "plugins_installed": {},
            "product": "open source",
            "realm": "hosted-clickhouse",
            "site_url": "http://localhost:8010",
            "table_sizes": ANY,
            "clickhouse_version": ANY,
            "deployment_infrastructure": "unknown",
            "helm": {},
            "instance_tag": "none",
            "new_dashboards": [
                {
                    "name": "Test Dashboard",
                    "id": dashboard.id,
                }
            ],
            "new_event_definitions": [],
            "new_playlists": [],
            "new_experiments_launched": [],
            "new_experiments_completed": [],
            "new_external_data_sources": [],
            "new_surveys_launched": [],
            "new_feature_flags": [],
            "digest_items_with_data": 1,
        }

        mock_capture.delay.assert_called_once_with(
            capture_event_name="transactional email",
            team_id=self.team.id,
            full_report_dict=expected_properties,
            send_for_all_members=True,
        )

    @freeze_time("2024-01-20T00:01:00Z")
    @patch("posthog.tasks.periodic_digest.capture_report")
    def test_periodic_digest_report_idempotency(self, mock_capture: MagicMock) -> None:
        # Create test data
        with freeze_time("2024-01-15T00:01:00Z"):
            Dashboard.objects.create(
                team=self.team,
                name="Test Dashboard",
            )

        # First run - should send the digest
        send_all_periodic_digest_reports()

        # Verify first call
        mock_capture.delay.assert_called_once()
        mock_capture.delay.reset_mock()

        # Check that messaging record was created
        record = MessagingRecord.objects.get(  # type: ignore
            raw_email=f"team_{self.team.id}", campaign_key="periodic_digest_2024-01-20_7d"
        )
        self.assertIsNotNone(record.sent_at)

        # Second run - should not send the digest again
        send_all_periodic_digest_reports()
        mock_capture.delay.assert_not_called()

        # Verify only one record exists
        self.assertEqual(MessagingRecord.objects.count(), 1)

    @freeze_time("2024-01-20T00:01:00Z")
    @patch("posthog.tasks.periodic_digest.capture_report")
    def test_periodic_digest_different_periods(self, mock_capture: MagicMock) -> None:
        # Create test data
        with freeze_time("2024-01-15T00:01:00Z"):
            Dashboard.objects.create(
                team=self.team,
                name="Test Dashboard",
            )

        # Send weekly digest
        send_all_periodic_digest_reports()
        mock_capture.delay.assert_called_once()
        mock_capture.delay.reset_mock()

        # Send monthly digest (different period length)
        send_all_periodic_digest_reports(
            begin_date=(datetime.now() - timedelta(days=30)).isoformat(), end_date=datetime.now().isoformat()
        )
        mock_capture.delay.assert_called_once()

        # Verify two different records exist
        records = MessagingRecord.objects.filter(raw_email=f"team_{self.team.id}")  # type: ignore
        self.assertEqual(records.count(), 2)
        campaign_keys = sorted([r.campaign_key for r in records])
        self.assertEqual(campaign_keys, ["periodic_digest_2024-01-20_30d", "periodic_digest_2024-01-20_7d"])

    @freeze_time("2024-01-20T00:01:00Z")
    @patch("posthog.tasks.periodic_digest.capture_report")
    def test_periodic_digest_empty_report_no_record(self, mock_capture: MagicMock) -> None:
        # Run without any data (empty digest)
        send_all_periodic_digest_reports()

        # Verify no capture call and no messaging record
        mock_capture.delay.assert_not_called()
        self.assertEqual(MessagingRecord.objects.count(), 0)

    @freeze_time("2024-01-20T00:01:00Z")
    @patch("posthog.tasks.periodic_digest.capture_report")
    def test_periodic_digest_dry_run_no_record(self, mock_capture: MagicMock) -> None:
        # Create test data
        Dashboard.objects.create(
            team=self.team,
            name="Test Dashboard",
        )

        # Run in dry_run mode
        send_all_periodic_digest_reports(dry_run=True)

        # Verify no capture call and no messaging record
        mock_capture.delay.assert_not_called()
        self.assertEqual(MessagingRecord.objects.count(), 0)

    @freeze_time("2024-01-20T00:01:00Z")
    @patch("posthog.tasks.periodic_digest.capture_report")
    def test_periodic_digest_excludes_playlists_without_names(self, mock_capture: MagicMock) -> None:
        # Create test data from "last week"
        with freeze_time("2024-01-15T00:01:00Z"):
            # Create playlists with various name states
            valid_playlist = SessionRecordingPlaylist.objects.create(
                team=self.team,
                name="Valid Playlist",
            )
            SessionRecordingPlaylist.objects.create(
                team=self.team,
                name=None,  # Null name should be excluded
            )
            SessionRecordingPlaylist.objects.create(
                team=self.team,
                name="",  # Empty string name should be excluded
            )

        # Run the periodic digest report task
        send_all_periodic_digest_reports()

        # Extract the playlists from the capture call
        call_args = mock_capture.delay.call_args
        self.assertIsNotNone(call_args)
        full_report_dict = call_args[1]["full_report_dict"]
        playlists = full_report_dict["new_playlists"]

        # Verify only the valid playlist is included
        self.assertEqual(len(playlists), 1)
        self.assertEqual(playlists[0]["name"], "Valid Playlist")
        self.assertEqual(playlists[0]["id"], valid_playlist.short_id)
