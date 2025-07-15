import datetime as dt
from unittest.mock import MagicMock, patch

from freezegun import freeze_time

from posthog.api.authentication import password_reset_token_generator
from posthog.api.email_verification import email_verification_token_generator
from posthog.batch_exports.models import (
    BatchExport,
    BatchExportDestination,
    BatchExportRun,
)
from posthog.models import Organization, Team, User
from posthog.models.hog_functions.hog_function import HogFunction
from posthog.models.instance_setting import set_instance_setting
from posthog.models.organization import OrganizationMembership
from posthog.models.organization_invite import OrganizationInvite
from posthog.models.plugin import Plugin, PluginConfig
from posthog.tasks.email import (
    send_async_migration_complete_email,
    send_async_migration_errored_email,
    send_batch_export_run_failure,
    send_canary_email,
    send_email_verification,
    send_fatal_plugin_error,
    send_hog_functions_digest_email,
    send_hog_functions_daily_digest,
    send_invite,
    send_member_join,
    send_password_reset,
)
from posthog.tasks.test.utils_email_tests import mock_email_messages
from posthog.test.base import APIBaseTest, ClickhouseTestMixin


def create_org_team_and_user(creation_date: str, email: str, ingested_event: bool = False) -> tuple[Organization, User]:
    with freeze_time(creation_date):
        org = Organization.objects.create(name="too_late_org")
        Team.objects.create(organization=org, name="Default Project", ingested_event=ingested_event)
        user = User.objects.create_and_join(
            organization=org,
            email=email,
            password=None,
            level=OrganizationMembership.Level.OWNER,
        )
        return org, user


@patch("posthog.tasks.email.EmailMessage")
class TestEmail(APIBaseTest, ClickhouseTestMixin):
    """
    NOTE: Every task in the "email" tasks should have at least one test.
    using the `mock_email_messages` helper writes the email output to `tasks/test/__emails__`
    so you can check out what it is rendered 🙌
    """

    @classmethod
    def setUpTestData(cls) -> None:
        super().setUpTestData()
        set_instance_setting("EMAIL_HOST", "fake_host")
        set_instance_setting("EMAIL_ENABLED", True)
        create_org_team_and_user("2022-01-01 00:00:00", "too_late_user@posthog.com")
        create_org_team_and_user(
            "2022-01-02 00:00:00",
            "ingested_event_in_range_user@posthog.com",
            ingested_event=True,
        )
        create_org_team_and_user("2022-01-03 00:00:00", "too_early_user@posthog.com")

    def test_send_invite(self, MockEmailMessage: MagicMock) -> None:
        mocked_email_messages = mock_email_messages(MockEmailMessage)

        org, user = create_org_team_and_user("2022-01-02 00:00:00", "admin@posthog.com")
        invite = OrganizationInvite.objects.create(organization=org, created_by=user, target_email="test@posthog.com")

        send_invite(invite.id)

        assert len(mocked_email_messages) == 1
        assert mocked_email_messages[0].send.call_count == 1
        assert mocked_email_messages[0].html_body

    def test_send_member_join(self, MockEmailMessage: MagicMock) -> None:
        mocked_email_messages = mock_email_messages(MockEmailMessage)

        org, user = create_org_team_and_user("2022-01-02 00:00:00", "admin@posthog.com")

        user = User.objects.create_and_join(
            organization=org,
            email="new-user@posthog.com",
            password=None,
            level=OrganizationMembership.Level.MEMBER,
        )
        send_member_join(user.uuid, org.id)

        assert len(mocked_email_messages) == 1
        assert mocked_email_messages[0].send.call_count == 1
        assert mocked_email_messages[0].html_body

    def test_send_password_reset(self, MockEmailMessage: MagicMock) -> None:
        mocked_email_messages = mock_email_messages(MockEmailMessage)
        org, user = create_org_team_and_user("2022-01-02 00:00:00", "admin@posthog.com")
        token = password_reset_token_generator.make_token(self.user)

        send_password_reset(user.id, token)

        assert len(mocked_email_messages) == 1
        assert mocked_email_messages[0].send.call_count == 1
        assert mocked_email_messages[0].html_body

    @patch("posthoganalytics.capture")
    def test_send_email_verification(self, mock_capture: MagicMock, MockEmailMessage: MagicMock) -> None:
        mocked_email_messages = mock_email_messages(MockEmailMessage)
        org, user = create_org_team_and_user("2022-01-02 00:00:00", "admin@posthog.com")
        token = email_verification_token_generator.make_token(self.user)
        send_email_verification(user.id, token)

        mock_capture.assert_called_once_with(
            event="verification email sent",
            distinct_id=user.distinct_id,
            groups={"organization": str(user.current_organization_id)},
        )
        assert len(mocked_email_messages) == 1
        assert mocked_email_messages[0].send.call_count == 1
        assert mocked_email_messages[0].html_body

    def test_send_fatal_plugin_error(self, MockEmailMessage: MagicMock) -> None:
        mocked_email_messages = mock_email_messages(MockEmailMessage)
        org, user = create_org_team_and_user("2022-01-02 00:00:00", "admin@posthog.com")
        plugin = Plugin.objects.create(organization=org)
        plugin_config = PluginConfig.objects.create(plugin=plugin, team=user.team, enabled=True, order=1)

        send_fatal_plugin_error(plugin_config.id, "20222-01-01", error="It exploded!", is_system_error=False)

        assert len(mocked_email_messages) == 1
        assert mocked_email_messages[0].send.call_count == 1
        assert mocked_email_messages[0].html_body

    def test_send_fatal_plugin_error_with_settings(self, MockEmailMessage: MagicMock) -> None:
        mocked_email_messages = mock_email_messages(MockEmailMessage)
        plugin = Plugin.objects.create(organization=self.organization)
        plugin_config = PluginConfig.objects.create(plugin=plugin, team=self.team, enabled=True, order=1)
        self._create_user("test2@posthog.com")
        self.user.partial_notification_settings = {"plugin_disabled": False}
        self.user.save()

        send_fatal_plugin_error(plugin_config.id, "20222-01-01", error="It exploded!", is_system_error=False)

        # Should only be sent to user2
        assert mocked_email_messages[0].to == [{"recipient": "test2@posthog.com", "raw_email": "test2@posthog.com"}]

        self.user.partial_notification_settings = {"plugin_disabled": True}
        self.user.save()
        send_fatal_plugin_error(plugin_config.id, "20222-01-01", error="It exploded!", is_system_error=False)
        # should be sent to both
        assert len(mocked_email_messages[1].to) == 2

    def test_send_batch_export_run_failure(self, MockEmailMessage: MagicMock) -> None:
        mocked_email_messages = mock_email_messages(MockEmailMessage)
        _, user = create_org_team_and_user("2022-01-02 00:00:00", "admin@posthog.com")
        batch_export_destination = BatchExportDestination.objects.create(
            type=BatchExportDestination.Destination.S3, config={"bucket_name": "my_production_s3_bucket"}
        )
        batch_export = BatchExport.objects.create(  # type: ignore
            team=user.team, name="A batch export", destination=batch_export_destination
        )
        now = dt.datetime.now()
        batch_export_run = BatchExportRun.objects.create(
            batch_export=batch_export,
            status=BatchExportRun.Status.FAILED,
            data_interval_start=now - dt.timedelta(hours=1),
            data_interval_end=now,
        )

        send_batch_export_run_failure(batch_export_run.id)

        assert len(mocked_email_messages) == 1
        assert mocked_email_messages[0].send.call_count == 1
        assert mocked_email_messages[0].html_body

    def test_send_batch_export_run_failure_with_settings(self, MockEmailMessage: MagicMock) -> None:
        mocked_email_messages = mock_email_messages(MockEmailMessage)
        batch_export_destination = BatchExportDestination.objects.create(
            type=BatchExportDestination.Destination.S3, config={"bucket_name": "my_production_s3_bucket"}
        )
        batch_export = BatchExport.objects.create(  # type: ignore
            team=self.user.team, name="A batch export", destination=batch_export_destination
        )
        now = dt.datetime.now()
        batch_export_run = BatchExportRun.objects.create(
            batch_export=batch_export,
            status=BatchExportRun.Status.FAILED,
            data_interval_start=now - dt.timedelta(hours=1),
            data_interval_end=now,
        )

        self._create_user("test2@posthog.com")
        self.user.partial_notification_settings = {"plugin_disabled": False}
        self.user.save()

        send_batch_export_run_failure(batch_export_run.id)
        # Should only be sent to user2
        assert mocked_email_messages[0].to == [{"recipient": "test2@posthog.com", "raw_email": "test2@posthog.com"}]

        self.user.partial_notification_settings = {"plugin_disabled": True}
        self.user.save()

        send_batch_export_run_failure(batch_export_run.id)
        # should be sent to both
        assert len(mocked_email_messages[1].to) == 2

    def test_send_canary_email(self, MockEmailMessage: MagicMock) -> None:
        mocked_email_messages = mock_email_messages(MockEmailMessage)
        send_canary_email("test@posthog.com")

        assert len(mocked_email_messages) == 1
        assert mocked_email_messages[0].send.call_count == 1
        assert mocked_email_messages[0].html_body

    def test_send_async_migration_complete_email(self, MockEmailMessage: MagicMock) -> None:
        mocked_email_messages = mock_email_messages(MockEmailMessage)

        User.objects.create(email="staff-user@posthog.com", password="password", is_staff=True)
        send_async_migration_complete_email("migration_1", "20:00")

        assert len(mocked_email_messages) == 1
        assert mocked_email_messages[0].send.call_count == 1
        assert mocked_email_messages[0].html_body

    def test_send_async_migration_errored_email(self, MockEmailMessage: MagicMock) -> None:
        mocked_email_messages = mock_email_messages(MockEmailMessage)

        User.objects.create(email="staff-user@posthog.com", password="password", is_staff=True)
        send_async_migration_errored_email("migration_1", "20:00", "It exploded!")

        assert len(mocked_email_messages) == 1
        assert mocked_email_messages[0].send.call_count == 1
        assert mocked_email_messages[0].html_body

    def test_send_hog_functions_digest_email(self, MockEmailMessage: MagicMock) -> None:
        mocked_email_messages = mock_email_messages(MockEmailMessage)

        digest_data = {
            "team_id": self.team.id,
            "date_str": "2023-01-15",
            "formatted_date": "January 15, 2023",
            "functions": [
                {
                    "id": "test-hog-function-1",
                    "name": "Test Function 1",
                    "type": "destination",
                    "status": "HEALTHY",
                    "succeeded": 150,
                    "failed": 5,
                    "filtered": 10,
                    "total_runs": 155,
                    "url": "http://localhost:8000/project/1/pipeline/destinations/test-hog-function-1",
                },
                {
                    "id": "test-hog-function-2",
                    "name": "Test Function 2",
                    "type": "transformation",
                    "status": "DEGRADED",
                    "succeeded": 200,
                    "failed": 50,
                    "filtered": 0,
                    "total_runs": 250,
                    "url": "http://localhost:8000/project/1/pipeline/destinations/test-hog-function-2",
                },
            ],
            "total_functions": 2,
            "total_succeeded": 350,
            "total_failed": 55,
            "total_filtered": 10,
            "total_runs": 405,
        }

        send_hog_functions_digest_email(digest_data)

        assert len(mocked_email_messages) == 1
        assert mocked_email_messages[0].send.call_count == 1
        assert mocked_email_messages[0].html_body

    def test_send_hog_functions_digest_email_with_settings(self, MockEmailMessage: MagicMock) -> None:
        mocked_email_messages = mock_email_messages(MockEmailMessage)

        self._create_user("test2@posthog.com")
        self.user.partial_notification_settings = {"hog_functions_digest": False}
        self.user.save()

        digest_data = {
            "team_id": self.team.id,
            "date_str": "2023-01-15",
            "formatted_date": "January 15, 2023",
            "functions": [
                {
                    "id": "test-hog-function",
                    "name": "Test Function",
                    "type": "destination",
                    "status": "HEALTHY",
                    "succeeded": 100,
                    "failed": 0,
                    "filtered": 5,
                    "total_runs": 100,
                    "url": "http://localhost:8000/project/1/pipeline/destinations/test-hog-function",
                }
            ],
            "total_functions": 1,
            "total_succeeded": 100,
            "total_failed": 0,
            "total_filtered": 5,
            "total_runs": 100,
        }

        send_hog_functions_digest_email(digest_data)

        # Should only be sent to user2 (user1 has notifications disabled)
        assert mocked_email_messages[0].to == [{"recipient": "test2@posthog.com", "raw_email": "test2@posthog.com"}]

        self.user.partial_notification_settings = {"hog_functions_digest": True}
        self.user.save()
        send_hog_functions_digest_email(digest_data)

        # Should now be sent to both users
        assert len(mocked_email_messages[1].to) == 2

    def test_send_hog_functions_digest_email_team_not_found(self, MockEmailMessage: MagicMock) -> None:
        mocked_email_messages = mock_email_messages(MockEmailMessage)

        digest_data = {
            "team_id": 99999,  # Non-existent team ID
            "date_str": "2023-01-15",
            "formatted_date": "January 15, 2023",
            "functions": [
                {
                    "id": "test",
                    "name": "Test",
                    "type": "destination",
                    "status": "HEALTHY",
                    "succeeded": 1,
                    "failed": 0,
                    "filtered": 0,
                    "total_runs": 1,
                    "url": "test",
                }
            ],
            "total_functions": 1,
            "total_succeeded": 1,
            "total_failed": 0,
            "total_filtered": 0,
            "total_runs": 1,
        }

        send_hog_functions_digest_email(digest_data)

        # Should not send any emails
        assert len(mocked_email_messages) == 0

    @patch("posthog.clickhouse.client.sync_execute")
    def test_send_hog_functions_daily_digest(self, mock_sync_execute: MagicMock, MockEmailMessage: MagicMock) -> None:
        mocked_email_messages = mock_email_messages(MockEmailMessage)

        # Create a HogFunction for testing
        hog_function = HogFunction.objects.create(
            team=self.team,
            name="Test Destination Function",
            type="destination",
            enabled=True,
            deleted=False,
            hog="return event",
        )

        # Mock the ClickHouse query response for metrics data only
        # Teams are now fetched from PostgreSQL via Django ORM
        mock_sync_execute.return_value = [
            # Metrics query result
            (
                self.team.id,
                hog_function.id,
                "Test Destination Function",
                "destination",
                {"state": "HEALTHY"},
                "succeeded",
                100,
            ),
            (
                self.team.id,
                hog_function.id,
                "Test Destination Function",
                "destination",
                {"state": "HEALTHY"},
                "failed",
                5,
            ),
            (
                self.team.id,
                hog_function.id,
                "Test Destination Function",
                "destination",
                {"state": "HEALTHY"},
                "filtered",
                10,
            ),
        ]

        send_hog_functions_daily_digest()

        # Should query ClickHouse once for metrics (teams come from PostgreSQL)
        assert mock_sync_execute.call_count == 1

        # Should send one digest email
        assert len(mocked_email_messages) == 1
        assert mocked_email_messages[0].send.call_count == 1
        assert mocked_email_messages[0].html_body

    @patch("posthog.clickhouse.client.sync_execute")
    def test_send_hog_functions_daily_digest_no_functions(
        self, mock_sync_execute: MagicMock, MockEmailMessage: MagicMock
    ) -> None:
        mocked_email_messages = mock_email_messages(MockEmailMessage)

        # No HogFunctions created, so no teams should be found
        send_hog_functions_daily_digest()

        # Should not query ClickHouse since no teams with active functions exist
        assert mock_sync_execute.call_count == 0
        assert len(mocked_email_messages) == 0

    @patch("posthog.clickhouse.client.sync_execute")
    def test_send_hog_functions_daily_digest_disabled_function(
        self, mock_sync_execute: MagicMock, MockEmailMessage: MagicMock
    ) -> None:
        mocked_email_messages = mock_email_messages(MockEmailMessage)

        # Create disabled HogFunction
        HogFunction.objects.create(
            team=self.team,
            name="Disabled Function",
            type="destination",
            enabled=False,  # Disabled
            deleted=False,
            hog="return event",
        )

        send_hog_functions_daily_digest()

        # Should not query ClickHouse since no teams with enabled functions exist
        assert mock_sync_execute.call_count == 0
        assert len(mocked_email_messages) == 0

    @patch("posthog.clickhouse.client.sync_execute")
    def test_send_hog_functions_daily_digest_deleted_function(
        self, mock_sync_execute: MagicMock, MockEmailMessage: MagicMock
    ) -> None:
        mocked_email_messages = mock_email_messages(MockEmailMessage)

        # Create deleted HogFunction
        HogFunction.objects.create(
            team=self.team,
            name="Deleted Function",
            type="destination",
            enabled=True,
            deleted=True,  # Deleted
            hog="return event",
        )

        send_hog_functions_daily_digest()

        # Should not query ClickHouse since no teams with active (non-deleted) functions exist
        assert mock_sync_execute.call_count == 0
        assert len(mocked_email_messages) == 0
