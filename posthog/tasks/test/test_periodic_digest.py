from datetime import datetime, timedelta
from unittest.mock import ANY, MagicMock, patch
from uuid import uuid4

from django.utils.timezone import now
from freezegun import freeze_time

from posthog.models import (
    Dashboard,
    EventDefinition,
    Experiment,
    FeatureFlag,
    Survey,
    Team,
)
from posthog.models.messaging import MessagingRecord
from posthog.models.organization import OrganizationMembership
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
    @patch("posthog.tasks.periodic_digest.capture_event")
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
            # This should be excluded from the digest because it has no name and no derived name
            SessionRecordingPlaylist.objects.create(
                team=self.team,
                name=None,
                derived_name=None,
            )
            # This should be included in the digest but use the derived name
            derived_playlist = SessionRecordingPlaylist.objects.create(
                team=self.team,
                name="",
                derived_name="Derived Playlist",
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
            "organization_id": str(self.team.organization_id),
            "organization_name": self.organization.name,
            "organization_created_at": self.organization.created_at.isoformat(),
            "teams": [
                {
                    "team_id": self.team.id,
                    "team_name": self.team.name,
                    "report": {
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
                            },
                            {
                                "name": "Derived Playlist",
                                "id": derived_playlist.short_id,
                            },
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
                    },
                    "digest_items_with_data": 8,
                }
            ],
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
            "total_digest_items_with_data": 8,
        }

        mock_capture.assert_called_once_with(
            pha_client=ANY,
            distinct_id=str(self.user.distinct_id),
            organization_id=str(self.team.organization_id),
            name="transactional email",
            team_id=None,
            properties=expected_properties,
            timestamp=None,
        )

    @patch("posthog.tasks.periodic_digest.capture_event")
    def test_periodic_digest_report_dry_run(self, mock_capture: MagicMock) -> None:
        send_all_periodic_digest_reports(dry_run=True)
        mock_capture.assert_not_called()

    @patch("posthog.tasks.periodic_digest.capture_event")
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
            "template_name": "periodic_digest_report",
            "organization_id": str(self.team.organization_id),
            "organization_name": self.organization.name,
            "organization_created_at": self.organization.created_at.isoformat(),
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
            "teams": [
                {
                    "report": {
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
                    },
                    "team_id": self.team.id,
                    "team_name": self.team.name,
                    "digest_items_with_data": 1,
                }
            ],
            "total_digest_items_with_data": 1,
        }

        mock_capture.assert_called_once_with(
            pha_client=ANY,
            distinct_id=str(self.user.distinct_id),
            organization_id=str(self.team.organization_id),
            name="transactional email",
            team_id=None,
            properties=expected_properties,
            timestamp=None,
        )

    @freeze_time("2024-01-20T00:01:00Z")
    @patch("posthog.tasks.periodic_digest.capture_event")
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
        mock_capture.assert_called_once()
        mock_capture.reset_mock()

        # Check that messaging record was created
        record = MessagingRecord.objects.get(  # type: ignore
            raw_email=f"org_{self.organization.id}", campaign_key="periodic_digest_2024-01-20_7d"
        )
        self.assertIsNotNone(record.sent_at)

        # Second run - should not send the digest again
        send_all_periodic_digest_reports()
        mock_capture.assert_not_called()

        # Verify only one record exists
        self.assertEqual(MessagingRecord.objects.count(), 1)

    @freeze_time("2024-01-20T00:01:00Z")
    @patch("posthog.tasks.periodic_digest.capture_event")
    def test_periodic_digest_different_periods(self, mock_capture: MagicMock) -> None:
        # Create test data
        with freeze_time("2024-01-15T00:01:00Z"):
            Dashboard.objects.create(
                team=self.team,
                name="Test Dashboard",
            )

        # Send weekly digest
        send_all_periodic_digest_reports()
        mock_capture.assert_called_once()
        mock_capture.reset_mock()

        # Send monthly digest (different period length)
        send_all_periodic_digest_reports(
            begin_date=(datetime.now() - timedelta(days=30)).isoformat(), end_date=datetime.now().isoformat()
        )
        mock_capture.assert_called_once()

        # Verify two different records exist
        records = MessagingRecord.objects.filter(raw_email=f"org_{self.organization.id}")  # type: ignore
        self.assertEqual(records.count(), 2)
        campaign_keys = sorted([r.campaign_key for r in records])
        self.assertEqual(campaign_keys, ["periodic_digest_2024-01-20_30d", "periodic_digest_2024-01-20_7d"])

    @freeze_time("2024-01-20T00:01:00Z")
    @patch("posthog.tasks.periodic_digest.capture_event")
    def test_periodic_digest_empty_report_no_record(self, mock_capture: MagicMock) -> None:
        # Run without any data (empty digest)
        send_all_periodic_digest_reports()

        # Verify no capture call and no messaging record
        mock_capture.assert_not_called()
        self.assertEqual(MessagingRecord.objects.count(), 0)

    @freeze_time("2024-01-20T00:01:00Z")
    @patch("posthog.tasks.periodic_digest.capture_event")
    def test_periodic_digest_dry_run_no_record(self, mock_capture: MagicMock) -> None:
        # Create test data
        Dashboard.objects.create(
            team=self.team,
            name="Test Dashboard",
        )

        # Run in dry_run mode
        send_all_periodic_digest_reports(dry_run=True)

        # Verify no capture call and no messaging record
        mock_capture.assert_not_called()
        self.assertEqual(MessagingRecord.objects.count(), 0)

    @freeze_time("2024-01-20T00:01:00Z")
    @patch("posthog.tasks.periodic_digest.capture_event")
    def test_periodic_digest_excludes_playlists_without_names_and_derived_names(self, mock_capture: MagicMock) -> None:
        # Create test data from "last week"
        with freeze_time("2024-01-15T00:01:00Z"):
            # Create playlists with various name states
            valid_playlist = SessionRecordingPlaylist.objects.create(
                team=self.team,
                name="Valid Playlist",
                derived_name="Derived Playlist",
            )
            SessionRecordingPlaylist.objects.create(
                team=self.team,
                name=None,  # Null name should be excluded
                derived_name=None,
            )
            SessionRecordingPlaylist.objects.create(
                team=self.team,
                name="",  # Empty string name should be excluded
                derived_name=None,
            )

        # Run the periodic digest report task
        send_all_periodic_digest_reports()

        # Extract the playlists from the capture call
        call_args = mock_capture.call_args
        self.assertIsNotNone(call_args)
        properties = call_args[1]["properties"]
        team_data = next(team for team in properties["teams"] if team["team_id"] == self.team.id)
        playlists = team_data["report"]["new_playlists"]

        # Verify only the valid playlist is included
        assert len(playlists) == 1
        assert playlists[0]["name"] == "Valid Playlist"
        assert playlists[0]["id"] == valid_playlist.short_id

    @freeze_time("2024-01-20T00:01:00Z")
    @patch("posthog.tasks.periodic_digest.capture_event")
    def test_periodic_digest_respects_team_notification_settings(self, mock_capture: MagicMock) -> None:
        # Create test data
        with freeze_time("2024-01-15T00:01:00Z"):
            Dashboard.objects.create(
                team=self.team,
                name="Test Dashboard",
            )

        # Create a second user who has disabled notifications for this team
        user_with_disabled_notifications = self._create_user("test2@posthog.com")
        user_with_disabled_notifications.partial_notification_settings = {
            "project_weekly_digest_disabled": {str(self.team.id): True}  # Disable notifications for this team
        }
        user_with_disabled_notifications.save()

        # Add both users to the organization
        self.organization.members.add(user_with_disabled_notifications)

        # Run the periodic digest report task
        send_all_periodic_digest_reports()

        # Verify capture_event was only called once (for the original user)
        mock_capture.assert_called_once()

        # Verify the call was for the original user and not the one with disabled notifications
        call_args = mock_capture.call_args[1]
        self.assertEqual(call_args["distinct_id"], str(self.user.distinct_id))

    @freeze_time("2024-01-20T00:01:00Z")
    @patch("posthog.tasks.periodic_digest.capture_event")
    def test_periodic_digest_report_multiple_teams(self, mock_capture: MagicMock) -> None:
        # Create a second team in the same organization
        team_2 = Team.objects.create(organization=self.organization, name="Second Team")

        # Create test data for both teams
        with freeze_time("2024-01-15T00:01:00Z"):
            # Data for first team
            Dashboard.objects.create(
                team=self.team,
                name="Team 1 Dashboard",
            )

            # Data for second team
            Dashboard.objects.create(
                team=team_2,
                name="Team 2 Dashboard",
            )
            FeatureFlag.objects.create(
                team=team_2,
                name="Team 2 Flag",
                key="team-2-flag",
            )

        send_all_periodic_digest_reports()

        # Should be called once with data for both teams
        assert mock_capture.call_count == 1

        call_args = mock_capture.call_args[1]
        properties = call_args["properties"]

        # Verify organization-level properties
        assert properties["organization_id"] == str(self.organization.id)
        assert properties["organization_name"] == self.organization.name

        # Verify teams data
        teams_data = properties["teams"]
        assert len(teams_data) == 2

        # Find teams by team_id in the array
        team_1_data = next(team for team in teams_data if team["team_id"] == self.team.id)
        team_2_data = next(team for team in teams_data if team["team_id"] == team_2.id)

        # Verify first team's data
        assert team_1_data["team_name"] == self.team.name
        assert len(team_1_data["report"]["new_dashboards"]) == 1
        assert team_1_data["report"]["new_dashboards"][0]["name"] == "Team 1 Dashboard"
        assert len(team_1_data["report"]["new_feature_flags"]) == 0

        # Verify second team's data
        assert team_2_data["team_name"] == team_2.name
        assert len(team_2_data["report"]["new_dashboards"]) == 1
        assert team_2_data["report"]["new_dashboards"][0]["name"] == "Team 2 Dashboard"
        assert len(team_2_data["report"]["new_feature_flags"]) == 1
        assert team_2_data["report"]["new_feature_flags"][0]["name"] == "Team 2 Flag"

    @freeze_time("2024-01-20T00:01:00Z")
    @patch("posthog.tasks.periodic_digest.capture_event")
    def test_periodic_digest_report_respects_team_access(self, mock_capture: MagicMock) -> None:
        # Create a second team in the same organization
        team_2 = Team.objects.create(organization=self.organization, name="Second Team")
        team_2.access_control = True
        team_2.save()

        # Create test data for both teams
        with freeze_time("2024-01-15T00:01:00Z"):
            Dashboard.objects.create(
                team=self.team,
                name="Team 1 Dashboard",
            )
            Dashboard.objects.create(
                team=team_2,
                name="Team 2 Dashboard",
            )

        # Create a second user with access only to team_2
        user_2 = self._create_user("test2@posthog.com")
        self.organization.members.add(user_2)
        org_membership = OrganizationMembership.objects.get(organization=self.organization, user=user_2)
        team_2.explicit_memberships.create(parent_membership=org_membership)

        # Run the periodic digest report task
        send_all_periodic_digest_reports()

        # Should be called twice - once for each user
        assert mock_capture.call_count == 2

        # Check calls to ensure each user only got their accessible teams
        calls = mock_capture.call_args_list
        for call in calls:
            properties = call[1]["properties"]
            distinct_id = call[1]["distinct_id"]

            if distinct_id == str(self.user.distinct_id):
                # First user should only see team 1 because they were not added to team 2
                assert len(properties["teams"]) == 1
                assert any(team["team_id"] == self.team.id for team in properties["teams"])
            else:
                # Second user should see team 1 and team 2
                assert len(properties["teams"]) == 2
                assert any(team["team_id"] == team_2.id for team in properties["teams"])
