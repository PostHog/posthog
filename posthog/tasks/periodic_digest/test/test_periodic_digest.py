import json
import random
from datetime import datetime, timedelta
from uuid import uuid4

from freezegun import freeze_time
from posthog.test.base import APIBaseTest
from unittest.mock import ANY, MagicMock, patch

from django.utils.timezone import now

from parameterized import parameterized

from posthog.helpers.session_recording_playlist_templates import DEFAULT_PLAYLIST_NAMES
from posthog.models import Dashboard, EventDefinition, Experiment, FeatureFlag, Survey, Team
from posthog.models.messaging import MessagingRecord
from posthog.models.organization import OrganizationMembership
from posthog.models.signals import mute_selected_signals
from posthog.session_recordings.models.session_recording import SessionRecording
from posthog.session_recordings.models.session_recording_playlist import (
    SessionRecordingPlaylist,
    SessionRecordingPlaylistViewed,
)
from posthog.session_recordings.models.session_recording_playlist_item import SessionRecordingPlaylistItem
from posthog.tasks.periodic_digest.periodic_digest import send_all_periodic_digest_reports
from posthog.tasks.periodic_digest.playlist_digests import get_teams_with_interesting_playlists

from products.data_warehouse.backend.models import ExternalDataSource
from products.enterprise.backend.models.rbac.access_control import AccessControl


@freeze_time("2024-01-01T00:01:00Z")  # A Monday
class TestPeriodicDigestReport(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.distinct_id = str(uuid4())

    @freeze_time("2024-01-20T00:01:00Z")
    @patch("posthog.tasks.periodic_digest.periodic_digest.capture_event")
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

            # Create playlists
            explicit_collection = SessionRecordingPlaylist.objects.create(
                team=self.team,
                name="Test Explicit Collection",
                type="collection",
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
                type="collection",
            )
            explicit_saved_filter = SessionRecordingPlaylist.objects.create(
                team=self.team,
                name="Test Saved Filter",
                type="filters",
            )
            # a playlist with no type is a collection if it has any pinned items
            implicit_collection = SessionRecordingPlaylist.objects.create(
                team=self.team,
                name="Test Implicit Collection",
            )

            with mute_selected_signals():
                SessionRecordingPlaylistItem.objects.create(
                    playlist=implicit_collection,
                    recording=SessionRecording.objects.create(team=self.team, session_id="123", distinct_id="123"),
                )

            # a playlist with no type is a saved filter if it has no pinned items
            implicit_saved_filter = SessionRecordingPlaylist.objects.create(
                team=self.team,
                name="Test Implicit Saved Filter",
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
                                "name": "Test Implicit Collection",
                                "id": implicit_collection.short_id,
                                "count": 1,
                                "has_more_available": False,
                                "type": "collection",
                                "url_path": f"/replay/playlists/{implicit_collection.short_id}",
                            },
                            {
                                "name": "Test Explicit Collection",
                                "id": explicit_collection.short_id,
                                "count": None,
                                "has_more_available": False,
                                "type": "collection",
                                "url_path": f"/replay/playlists/{explicit_collection.short_id}",
                            },
                            {
                                "name": "Derived Playlist",
                                "id": derived_playlist.short_id,
                                "count": None,
                                "has_more_available": False,
                                "type": "collection",
                                "url_path": f"/replay/playlists/{derived_playlist.short_id}",
                            },
                            {
                                "name": "Test Saved Filter",
                                "id": explicit_saved_filter.short_id,
                                "count": None,
                                "has_more_available": False,
                                "type": "filters",
                                "url_path": f"/replay/home/?filterId={explicit_saved_filter.short_id}",
                            },
                            {
                                "name": "Test Implicit Saved Filter",
                                "id": implicit_saved_filter.short_id,
                                "count": None,
                                "has_more_available": False,
                                "type": "filters",
                                "url_path": f"/replay/home/?filterId={implicit_saved_filter.short_id}",
                            },
                        ],
                        "interesting_collections": [
                            {
                                "name": "Test Implicit Collection",
                                "id": implicit_collection.short_id,
                                "count": 1,
                                "has_more_available": False,
                                "type": "collection",
                                "url_path": f"/replay/playlists/{implicit_collection.short_id}",
                            },
                            {
                                "name": "Test Explicit Collection",
                                "id": explicit_collection.short_id,
                                "count": None,
                                "has_more_available": False,
                                "type": "collection",
                                "url_path": f"/replay/playlists/{explicit_collection.short_id}",
                            },
                            {
                                "name": "Derived Playlist",
                                "id": derived_playlist.short_id,
                                "count": None,
                                "has_more_available": False,
                                "type": "collection",
                                "url_path": f"/replay/playlists/{derived_playlist.short_id}",
                            },
                        ],
                        "interesting_saved_filters": [
                            {
                                "name": "Test Saved Filter",
                                "id": explicit_saved_filter.short_id,
                                "count": None,
                                "has_more_available": False,
                                "type": "filters",
                                "url_path": f"/replay/home/?filterId={explicit_saved_filter.short_id}",
                            },
                            {
                                "name": "Test Implicit Saved Filter",
                                "id": implicit_saved_filter.short_id,
                                "count": None,
                                "has_more_available": False,
                                "type": "filters",
                                "url_path": f"/replay/home/?filterId={implicit_saved_filter.short_id}",
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
                    "digest_items_with_data": 10,
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
            "total_digest_items_with_data": 10,
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

    @patch("posthog.tasks.periodic_digest.periodic_digest.capture_event")
    def test_periodic_digest_report_dry_run(self, mock_capture: MagicMock) -> None:
        send_all_periodic_digest_reports(dry_run=True)
        mock_capture.assert_not_called()

    @patch("posthog.tasks.periodic_digest.periodic_digest.capture_event")
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
                        "interesting_collections": [],
                        "interesting_saved_filters": [],
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
    @patch("posthog.tasks.periodic_digest.periodic_digest.capture_event")
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
    @patch("posthog.tasks.periodic_digest.periodic_digest.capture_event")
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
    @patch("posthog.tasks.periodic_digest.periodic_digest.capture_event")
    def test_periodic_digest_empty_report_no_record(self, mock_capture: MagicMock) -> None:
        # Run without any data (empty digest)
        send_all_periodic_digest_reports()

        # Verify no capture call and no messaging record
        mock_capture.assert_not_called()
        self.assertEqual(MessagingRecord.objects.count(), 0)

    @freeze_time("2024-01-20T00:01:00Z")
    @patch("posthog.tasks.periodic_digest.periodic_digest.capture_event")
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
    @patch("posthog.tasks.periodic_digest.periodic_digest.capture_event")
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
    @patch("posthog.tasks.periodic_digest.periodic_digest.capture_event")
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
    @patch("posthog.tasks.periodic_digest.periodic_digest.capture_event")
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
    @patch("posthog.tasks.periodic_digest.periodic_digest.capture_event")
    def test_periodic_digest_report_respects_team_access(self, mock_capture: MagicMock) -> None:
        # Create a second team in the same organization
        team_2 = Team.objects.create(organization=self.organization, name="Second Team")
        AccessControl.objects.create(team=team_2, access_level="none", resource="project", resource_id=str(team_2.id))

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
        AccessControl.objects.create(
            team=team_2,
            access_level="member",
            resource="project",
            resource_id=str(team_2.id),
            organization_member=org_membership,
        )

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

    @parameterized.expand(
        [
            ("no_redis_value", [None], None, False),
            ("count_no_more", [json.dumps({"session_ids": ["a", "b"], "has_more": False})], 2, False),
            ("count_with_more", [json.dumps({"session_ids": ["a"], "has_more": True})], 1, True),
        ]
    )
    @patch("posthog.tasks.periodic_digest.playlist_digests.get_client")
    def test_get_teams_with_new_playlists_counts(
        self,
        desc: str,
        redis_values: list[str],
        expected_count: int,
        expected_has_more: bool,
        mock_get_client: MagicMock,
    ) -> None:
        SessionRecordingPlaylist.objects.create(
            team=self.team,
            name="Test",
            short_id="abc",
            derived_name=None,
        )

        mock_redis = MagicMock()
        mock_redis.mget.return_value = redis_values if redis_values is not None else []
        mock_get_client.return_value = mock_redis

        from posthog.tasks.periodic_digest.periodic_digest import get_teams_with_new_playlists

        result = get_teams_with_new_playlists(datetime.now(), datetime.now() - timedelta(days=1))

        playlist_result = result[0]
        assert playlist_result.count == expected_count, f"{desc}: count"
        assert playlist_result.has_more_available == expected_has_more, f"{desc}: has_more"

    @freeze_time("2024-01-20T00:01:00Z")
    @patch("posthog.tasks.periodic_digest.periodic_digest.capture_event")
    def test_get_teams_with_new_playlists_only_with_pinned_items(self, _mock_capture: MagicMock) -> None:
        playlist_with_item = SessionRecordingPlaylist.objects.create(
            team=self.team,
            name="With Item",
            short_id="abc",
            derived_name=None,
            deleted=False,
        )
        SessionRecordingPlaylistItem.objects.create(
            playlist=playlist_with_item,
            session_id="s1",
        )

        _playlist_without_item = SessionRecordingPlaylist.objects.create(
            team=self.team,
            name="No Item",
            short_id="def",
            derived_name=None,
            deleted=False,
        )

        # Patch redis
        with patch("posthog.tasks.periodic_digest.playlist_digests.get_client") as mock_get_client:
            mock_redis = MagicMock()
            mock_redis.mget.return_value = [None, None]
            mock_get_client.return_value = mock_redis

            from posthog.tasks.periodic_digest.periodic_digest import get_teams_with_new_playlists

            result = get_teams_with_new_playlists(datetime.now(), datetime.now() - timedelta(days=1))

        # Only the playlist with a pinned item should be present
        assert [{p.name: p.count} for p in result] == [{"With Item": 1}, {"No Item": None}]

    @freeze_time("2024-01-20T00:01:00Z")
    @patch("posthog.tasks.periodic_digest.periodic_digest.capture_event")
    def test_periodic_digest_excludes_default_named_playlists(self, mock_capture: MagicMock) -> None:
        # need to type ignore here, because mypy insists this returns a list but it does not
        default_name: str = random.choice(DEFAULT_PLAYLIST_NAMES)  # type: ignore
        with freeze_time("2024-01-15T00:01:00Z"):
            # Playlist with a default name should be excluded
            SessionRecordingPlaylist.objects.create(
                team=self.team,
                name=default_name,
                derived_name=None,
            )
            # Playlist with a custom name should be included
            custom_playlist = SessionRecordingPlaylist.objects.create(
                team=self.team,
                name="Custom Playlist",
                derived_name=None,
            )

        send_all_periodic_digest_reports()

        call_args = mock_capture.call_args
        self.assertIsNotNone(call_args)
        properties = call_args[1]["properties"]
        team_data = next(team for team in properties["teams"] if team["team_id"] == self.team.id)
        playlists = team_data["report"]["new_playlists"]

        # Only the custom playlist should be included
        assert len(playlists) == 1
        assert playlists[0]["name"] == "Custom Playlist"
        assert playlists[0]["id"] == custom_playlist.short_id

    def test_interesting_playlists_sorted_by_views(self) -> None:
        with freeze_time("2024-01-20T00:01:00Z") as frozen_time:
            playlist1 = SessionRecordingPlaylist.objects.create(team=self.team, name="Playlist 1")
            playlist2 = SessionRecordingPlaylist.objects.create(team=self.team, name="Playlist 2")
            playlist3 = SessionRecordingPlaylist.objects.create(team=self.team, name="Playlist 3")

            # Simulate views: playlist2 > playlist1 > playlist3
            for i in range(5):
                frozen_time.tick(delta=timedelta(seconds=i))
                SessionRecordingPlaylistViewed.objects.create(user=self.user, team=self.team, playlist=playlist2)

            for i in range(3):
                frozen_time.tick(delta=timedelta(seconds=i))
                SessionRecordingPlaylistViewed.objects.create(user=self.user, team=self.team, playlist=playlist1)

            frozen_time.tick()
            SessionRecordingPlaylistViewed.objects.create(user=self.user, team=self.team, playlist=playlist3)

            results = get_teams_with_interesting_playlists(datetime(2024, 1, 20))
            names = [p.name for p in results if p.name in {"Playlist 1", "Playlist 2", "Playlist 3"}]

            assert names == ["Playlist 2", "Playlist 1", "Playlist 3"]
            assert results[0].view_count == 5
            assert results[1].view_count == 3
            assert results[2].view_count == 1

    def test_interesting_playlists_sorted_by_user_count(self) -> None:
        with freeze_time("2024-01-20T00:01:00Z") as frozen_time:
            playlist1 = SessionRecordingPlaylist.objects.create(team=self.team, name="Playlist 1")
            playlist2 = SessionRecordingPlaylist.objects.create(team=self.team, name="Playlist 2")

            # playlist1: 5 views from 1 user
            for i in range(5):
                frozen_time.tick(delta=timedelta(seconds=i))
                SessionRecordingPlaylistViewed.objects.create(user=self.user, team=self.team, playlist=playlist1)

            # playlist2: 5 views from 5 different users
            for i in range(5):
                frozen_time.tick(delta=timedelta(seconds=i))
                user = self._create_user(f"user{i}{i}@posthog.com")
                SessionRecordingPlaylistViewed.objects.create(user=user, team=self.team, playlist=playlist2)

            results = get_teams_with_interesting_playlists(datetime(2024, 1, 20))
            names = [p.name for p in results if p.name in {"Playlist 1", "Playlist 2"}]

            assert names[0] == "Playlist 2"  # More unique users, so comes first
            assert results[0].user_count == 5
            assert results[1].user_count == 1
