import datetime as dt
from typing import cast

from freezegun import freeze_time
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, run_clickhouse_statement_in_parallel
from unittest.mock import MagicMock, patch

from django.utils import timezone

from posthog.api.authentication import password_reset_token_generator
from posthog.api.email_verification import email_verification_token_generator
from posthog.batch_exports.models import BatchExport, BatchExportDestination, BatchExportRun
from posthog.models import Organization, Team, User
from posthog.models.app_metrics2.sql import TRUNCATE_APP_METRICS2_TABLE_SQL
from posthog.models.hog_functions.hog_function import HogFunction
from posthog.models.instance_setting import set_instance_setting
from posthog.models.organization import OrganizationMembership
from posthog.models.organization_invite import OrganizationInvite
from posthog.models.plugin import Plugin, PluginConfig
from posthog.tasks.email import (
    get_members_to_notify_for_pipeline_error,
    login_from_new_device_notification,
    send_async_migration_complete_email,
    send_async_migration_errored_email,
    send_batch_export_run_failure,
    send_canary_email,
    send_discussions_mentioned,
    send_email_verification,
    send_fatal_plugin_error,
    send_hog_functions_daily_digest,
    send_hog_functions_digest_email,
    send_invite,
    send_member_join,
    send_new_ticket_notification,
    send_password_reset,
    should_send_pipeline_error_notification,
)
from posthog.tasks.test.utils_email_tests import mock_email_messages


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
        user2 = self._create_user("test2@posthog.com")
        self.user.partial_notification_settings = {"plugin_disabled": False}
        self.user.save()

        send_fatal_plugin_error(plugin_config.id, "20222-01-01", error="It exploded!", is_system_error=False)

        # Should only be sent to user2
        assert mocked_email_messages[0].to == [
            {"recipient": "test2@posthog.com", "raw_email": "test2@posthog.com", "distinct_id": str(user2.distinct_id)}
        ]

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

        user2 = self._create_user("test2@posthog.com")
        self.user.partial_notification_settings = {"plugin_disabled": False}
        self.user.save()

        send_batch_export_run_failure(batch_export_run.id)
        # Should only be sent to user2
        assert mocked_email_messages[0].to == [
            {"recipient": "test2@posthog.com", "raw_email": "test2@posthog.com", "distinct_id": str(user2.distinct_id)}
        ]

        self.user.partial_notification_settings = {"plugin_disabled": True}
        self.user.save()

        send_batch_export_run_failure(batch_export_run.id)
        # should be sent to both
        assert len(mocked_email_messages[1].to) == 2

    def test_send_batch_export_run_failure_with_threshold(self, MockEmailMessage: MagicMock) -> None:
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

        # Test with threshold 0.0 (default) - should notify on any failure
        send_batch_export_run_failure(batch_export_run.id, failure_rate=0.5)
        assert len(mocked_email_messages) == 1
        assert mocked_email_messages[0].send.call_count == 1

        # Test with threshold 0.5 and failure rate 0.6 - should notify
        self.user.partial_notification_settings = {
            "plugin_disabled": True,
            "data_pipeline_error_threshold": 0.5,
        }
        self.user.save()
        send_batch_export_run_failure(batch_export_run.id, failure_rate=0.6)
        assert len(mocked_email_messages) == 2
        assert mocked_email_messages[1].send.call_count == 1

        # Test with threshold 0.5 and failure rate 0.4 - should NOT notify
        send_batch_export_run_failure(batch_export_run.id, failure_rate=0.4)
        # Should still be 2 messages (no new message sent)
        assert len(mocked_email_messages) == 2

        # Test with threshold 0.5 and failure rate exactly 0.5 - should NOT notify (threshold is exclusive)
        send_batch_export_run_failure(batch_export_run.id, failure_rate=0.5)
        assert len(mocked_email_messages) == 2

        # Test with threshold 0.0 explicitly set - should notify on any failure
        self.user.partial_notification_settings = {
            "plugin_disabled": True,
            "data_pipeline_error_threshold": 0.0,
        }
        self.user.save()
        send_batch_export_run_failure(batch_export_run.id, failure_rate=0.1)
        assert len(mocked_email_messages) == 3
        assert mocked_email_messages[2].send.call_count == 1

    def test_send_batch_export_run_failure_with_threshold_disabled(self, MockEmailMessage: MagicMock) -> None:
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

        # Test with plugin_disabled=False - should not notify even with high failure rate
        self.user.partial_notification_settings = {
            "plugin_disabled": False,
            "data_pipeline_error_threshold": 0.5,
        }
        self.user.save()
        send_batch_export_run_failure(batch_export_run.id, failure_rate=1.0)
        assert len(mocked_email_messages) == 0

    def test_should_send_pipeline_error_notification(self, MockEmailMessage: MagicMock) -> None:
        # Test default behavior (threshold 0.0) - should notify on any failure
        assert should_send_pipeline_error_notification(self.user, failure_rate=0.1) is True
        assert should_send_pipeline_error_notification(self.user, failure_rate=0.0) is True

        # Test with threshold 0.5
        self.user.partial_notification_settings = {
            "plugin_disabled": True,
            "data_pipeline_error_threshold": 0.5,
        }
        self.user.save()
        assert should_send_pipeline_error_notification(self.user, failure_rate=0.6) is True
        assert should_send_pipeline_error_notification(self.user, failure_rate=0.5) is False
        assert should_send_pipeline_error_notification(self.user, failure_rate=0.4) is False

        # Test with threshold 0.0 explicitly set
        self.user.partial_notification_settings = {
            "plugin_disabled": True,
            "data_pipeline_error_threshold": 0.0,
        }
        self.user.save()
        assert should_send_pipeline_error_notification(self.user, failure_rate=0.1) is True

    def test_get_members_to_notify_for_pipeline_error(self, MockEmailMessage: MagicMock) -> None:
        user2 = self._create_user("test2@posthog.com")

        # Test with default settings (threshold 0.0) - both users should be notified
        memberships = get_members_to_notify_for_pipeline_error(cast(Team, self.user.team), failure_rate=0.5)
        assert len(memberships) == 2
        assert {m.user.email for m in memberships} == {self.user.email, user2.email}

        # Test with threshold 0.6 and failure rate 0.5 - no users should be notified
        self.user.partial_notification_settings = {
            "plugin_disabled": True,
            "data_pipeline_error_threshold": 0.6,
        }
        self.user.save()
        user2.partial_notification_settings = {
            "plugin_disabled": True,
            "data_pipeline_error_threshold": 0.6,
        }
        user2.save()
        memberships = get_members_to_notify_for_pipeline_error(cast(Team, self.user.team), failure_rate=0.5)
        assert len(memberships) == 0

        # Test with threshold 0.4 and failure rate 0.5 - both users should be notified
        self.user.partial_notification_settings = {
            "plugin_disabled": True,
            "data_pipeline_error_threshold": 0.4,
        }
        self.user.save()
        user2.partial_notification_settings = {
            "plugin_disabled": True,
            "data_pipeline_error_threshold": 0.4,
        }
        user2.save()
        memberships = get_members_to_notify_for_pipeline_error(cast(Team, self.user.team), failure_rate=0.5)
        assert len(memberships) == 2

        # Test with one user having plugin_disabled=False
        self.user.partial_notification_settings = {
            "plugin_disabled": False,
            "data_pipeline_error_threshold": 0.4,
        }
        self.user.save()
        memberships = get_members_to_notify_for_pipeline_error(cast(Team, self.user.team), failure_rate=0.5)
        assert len(memberships) == 1
        assert memberships[0].user.email == user2.email

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
            "functions": [
                {
                    "id": "test-hog-function-1",
                    "name": "Test Function 1",
                    "type": "destination",
                    "created_by_email": "creator1@example.com",
                    "last_edited_by_email": "editor1@example.com",
                    "last_edit_date": "2025-08-01",
                    "succeeded": 95,
                    "failed": 5,
                    "failure_rate": 5.0,
                    "url": "http://localhost:8000/project/1/pipeline/destinations/test-hog-function-1",
                },
                {
                    "id": "test-hog-function-2",
                    "name": "Test Function 2",
                    "type": "transformation",
                    "created_by_email": "creator2@example.com",
                    "last_edited_by_email": "editor2@example.com",
                    "last_edit_date": "2025-08-02",
                    "succeeded": 200,
                    "failed": 50,
                    "failure_rate": 20.0,
                    "url": "http://localhost:8000/project/1/pipeline/destinations/test-hog-function-2",
                },
            ],
        }

        send_hog_functions_digest_email(digest_data)

        assert len(mocked_email_messages) == 1
        assert mocked_email_messages[0].send.call_count == 1
        assert mocked_email_messages[0].html_body

    def test_send_hog_functions_digest_email_with_settings(self, MockEmailMessage: MagicMock) -> None:
        mocked_email_messages = mock_email_messages(MockEmailMessage)

        user2 = self._create_user("test2@posthog.com")
        self.user.partial_notification_settings = {"plugin_disabled": False}
        self.user.save()

        digest_data = {
            "team_id": self.team.id,
            "functions": [
                {
                    "id": "test-hog-function-1",
                    "name": "Webhook Alert System",
                    "type": "destination",
                    "created_by_email": "admin@company.com",
                    "last_edited_by_email": "dev@company.com",
                    "last_edit_date": "2025-07-20",
                    "succeeded": 1000,
                    "failed": 50000,
                    "failure_rate": 98.0,
                    "url": "http://localhost:8000/project/1/pipeline/destinations/test-hog-function-1",
                },
                {
                    "id": "test-hog-function-2",
                    "name": "Slack Notifications",
                    "type": "transformation",
                    "created_by_email": None,  # Test case for missing creator
                    "last_edited_by_email": "maintainer@company.com",
                    "last_edit_date": "2025-07-15",
                    "succeeded": 1500000,
                    "failed": 25000,
                    "failure_rate": 1.6,
                    "url": "http://localhost:8000/project/1/pipeline/destinations/test-hog-function-2",
                },
                {
                    "id": "test-hog-function-3",
                    "name": "Email Campaign Processor",
                    "type": "destination",
                    "created_by_email": "developer@company.com",
                    "last_edited_by_email": None,  # Test case for missing last editor
                    "last_edit_date": None,
                    "succeeded": 75000,
                    "failed": 3500,
                    "failure_rate": 4.5,
                    "url": "http://localhost:8000/project/1/pipeline/destinations/test-hog-function-3",
                },
                {
                    "id": "test-hog-function-4",
                    "name": "Data Warehouse Sync",
                    "type": "destination",
                    "created_by_email": "data-team@company.com",
                    "last_edited_by_email": "ops@company.com",
                    "last_edit_date": "2025-07-25",
                    "succeeded": 2000000,
                    "failed": 150000,
                    "failure_rate": 7.0,
                    "url": "http://localhost:8000/project/1/pipeline/destinations/test-hog-function-4",
                },
                {
                    "id": "test-hog-function-5",
                    "name": "Analytics Dashboard Feed",
                    "type": "transformation",
                    "created_by_email": "analytics@company.com",
                    "last_edited_by_email": "analyst@company.com",
                    "last_edit_date": "2025-08-05",
                    "succeeded": 500000,
                    "failed": 12000,
                    "failure_rate": 2.3,
                    "url": "http://localhost:8000/project/1/pipeline/destinations/test-hog-function-5",
                },
            ],
        }

        send_hog_functions_digest_email(digest_data)

        # Should only be sent to user2 (user1 has notifications disabled)
        # Each user gets their own email now
        assert len(mocked_email_messages) == 1
        assert mocked_email_messages[0].to == [
            {"recipient": "test2@posthog.com", "raw_email": "test2@posthog.com", "distinct_id": str(user2.distinct_id)}
        ]

        self.user.partial_notification_settings = {"plugin_disabled": True}
        self.user.save()
        send_hog_functions_digest_email(digest_data)

        # Should now be sent to both users (2 separate emails, one per user)
        assert len(mocked_email_messages) == 3  # 1 from first call + 2 from second call
        # Verify both users received emails from the second call
        second_call_recipients = {msg.to[0]["raw_email"] for msg in mocked_email_messages[1:]}
        assert second_call_recipients == {"user1@posthog.com", "test2@posthog.com"}

    def test_send_hog_functions_digest_email_team_not_found(self, MockEmailMessage: MagicMock) -> None:
        mocked_email_messages = mock_email_messages(MockEmailMessage)

        digest_data = {
            "team_id": 99999,  # Non-existent team ID
            "functions": [
                {
                    "id": "test",
                    "name": "Test",
                    "type": "destination",
                    "succeeded": 50,
                    "failed": 10,
                    "url": "test",
                }
            ],
        }

        send_hog_functions_digest_email(digest_data)

        # Should not send any emails
        assert len(mocked_email_messages) == 0

    def test_send_hog_functions_digest_email_comma_formatting(self, MockEmailMessage: MagicMock) -> None:
        mocked_email_messages = mock_email_messages(MockEmailMessage)

        digest_data = {
            "team_id": self.team.id,
            "functions": [
                {
                    "id": "test-hog-function-1",
                    "name": "Webhook Alert System",
                    "type": "destination",
                    "created_by_email": "user@example.com",
                    "last_edited_by_email": "modifier@example.com",
                    "last_edit_date": "2025-07-28",
                    "succeeded": 1000,
                    "failed": 50000,
                    "failure_rate": 98.0,
                    "url": "http://localhost:8000/project/1/pipeline/destinations/test-hog-function-1",
                },
                {
                    "id": "test-hog-function-2",
                    "name": "Slack Notifications",
                    "type": "transformation",
                    "created_by_email": "another@example.com",
                    "last_edited_by_email": "updater@example.com",
                    "last_edit_date": "2025-07-30",
                    "succeeded": 1500000,
                    "failed": 25000,
                    "failure_rate": 1.6,
                    "url": "http://localhost:8000/project/1/pipeline/destinations/test-hog-function-2",
                },
            ],
        }

        send_hog_functions_digest_email(digest_data)

        assert len(mocked_email_messages) == 1
        assert mocked_email_messages[0].send.call_count == 1

        # Check that the HTML body contains comma-formatted numbers
        html_body = mocked_email_messages[0].html_body
        assert "1,000" in html_body  # succeeded count for first function
        assert "50,000" in html_body  # failed count for first function
        assert "1,500,000" in html_body  # succeeded count for second function
        assert "25,000" in html_body  # failed count for second function

    def test_send_hog_functions_daily_digest(self, MockEmailMessage: MagicMock) -> None:
        from posthog.test.fixtures import create_app_metric2

        # Clean up app_metrics2 table before test
        run_clickhouse_statement_in_parallel([TRUNCATE_APP_METRICS2_TABLE_SQL])

        mocked_email_messages = mock_email_messages(MockEmailMessage)

        # Create users for creator and editor
        creator_user = self._create_user("creator@posthog.com")
        editor_user = self._create_user("editor@posthog.com")

        # Create a HogFunction for testing with real creator
        hog_function = HogFunction.objects.create(
            team=self.team,
            name="Test Destination Function",
            type="destination",
            enabled=True,
            deleted=False,
            hog="return event",
            created_by=creator_user,
        )

        # Create an activity log entry for this function (simulating an edit)
        from posthog.models.activity_logging.activity_log import ActivityLog, Detail

        edit_date = timezone.now() - dt.timedelta(days=1)
        ActivityLog.objects.create(
            team_id=self.team.id,
            user=editor_user,
            activity="updated",
            scope="HogFunction",
            item_id=str(hog_function.id),
            detail=Detail(name=hog_function.name, type="destination"),
            created_at=edit_date,
        )

        # Create test data in app_metrics2 table with all metric types
        create_app_metric2(
            team_id=self.team.id,
            app_source="hog_function",
            app_source_id=str(hog_function.id),
            timestamp=timezone.now() - dt.timedelta(hours=1),  # Within last 24h
            metric_kind="failure",
            metric_name="failed",
            count=5,  # This will trigger the digest
        )
        create_app_metric2(
            team_id=self.team.id,
            app_source="hog_function",
            app_source_id=str(hog_function.id),
            timestamp=timezone.now() - dt.timedelta(hours=1),
            metric_kind="success",
            metric_name="succeeded",
            count=95,
        )
        create_app_metric2(
            team_id=self.team.id,
            app_source="hog_function",
            app_source_id=str(hog_function.id),
            timestamp=timezone.now() - dt.timedelta(hours=1),
            metric_kind="filter",
            metric_name="filtered",
            count=3,
        )

        # Test 1: Enable digest for this team - should send email since there are failures
        # There are 3 users at this point (self.user, creator_user, editor_user)
        with self.settings(HOG_FUNCTIONS_DAILY_DIGEST_TEAM_IDS=[str(self.team.id)]):
            send_hog_functions_daily_digest()

        # Each user gets their own email (3 users = 3 emails)
        assert len(mocked_email_messages) == 3
        for msg in mocked_email_messages:
            assert msg.send.call_count == 1
            assert msg.html_body

        # Check that the HTML body contains both creator and editor info
        html_body = mocked_email_messages[0].html_body
        assert "creator@posthog.com" in html_body, "Creator email should be in the email"
        assert "editor@posthog.com" in html_body, "Editor email should be in the email"
        assert edit_date.strftime("%Y-%m-%d") in html_body, "Edit date should be in the email"

        # Reset mocked messages
        mocked_email_messages.clear()

        # Test 2: Team not in allowlist - should not send email
        with self.settings(HOG_FUNCTIONS_DAILY_DIGEST_TEAM_IDS=["999"]):
            send_hog_functions_daily_digest()

        assert len(mocked_email_messages) == 0

        # Test 3: Empty allowlist (default behavior) - should send email since there are failures
        with self.settings(HOG_FUNCTIONS_DAILY_DIGEST_TEAM_IDS=[]):
            send_hog_functions_daily_digest()

        # Each user gets their own email (3 users = 3 emails)
        assert len(mocked_email_messages) == 3
        for msg in mocked_email_messages:
            assert msg.send.call_count == 1
            assert msg.html_body

        # Reset mocked messages
        mocked_email_messages.clear()

        # Test 4: Using '*' in allowlist - should send email to all teams with failures
        with self.settings(HOG_FUNCTIONS_DAILY_DIGEST_TEAM_IDS=["*"]):
            send_hog_functions_daily_digest()

        # Each user gets their own email (3 users = 3 emails)
        assert len(mocked_email_messages) == 3
        for msg in mocked_email_messages:
            assert msg.send.call_count == 1
            assert msg.html_body

        # Reset mocked messages
        mocked_email_messages.clear()

        # Test 5: Test notification settings - user with plugin_disabled: False should not receive email
        self._create_user("test2@posthog.com")
        self.user.partial_notification_settings = {"plugin_disabled": False}
        self.user.save()

        send_hog_functions_daily_digest()
        # Should be sent to users with notifications enabled (creator, editor, test2) - 3 separate emails
        recipients = {msg.to[0]["raw_email"] for msg in mocked_email_messages}
        expected_recipients = {"creator@posthog.com", "editor@posthog.com", "test2@posthog.com"}
        assert recipients == expected_recipients

        # Reset mocked messages
        mocked_email_messages.clear()

        # Test 6: Test notification settings - user with plugin_disabled: True should receive email
        self.user.partial_notification_settings = {"plugin_disabled": True}
        self.user.save()

        send_hog_functions_daily_digest()
        # Should now be sent to all users (creator, editor, original user, test2) - 4 separate emails
        assert len(mocked_email_messages) == 4

    def test_send_hog_functions_digest_email_with_test_email_override(self, MockEmailMessage: MagicMock) -> None:
        mocked_email_messages = mock_email_messages(MockEmailMessage)

        # Create users for testing
        self._create_user("test2@posthog.com")
        self._create_user("override@posthog.com")

        # Disable notifications for the main user to verify override bypasses settings
        self.user.partial_notification_settings = {"plugin_disabled": False}
        self.user.save()

        digest_data = {
            "team_id": self.team.id,
            "functions": [
                {
                    "id": "test-hog-function-1",
                    "name": "Test Function 1",
                    "type": "destination",
                    "created_by_email": "test@example.com",
                    "last_edited_by_email": "tester@example.com",
                    "last_edit_date": "2025-08-04",
                    "succeeded": 95,
                    "failed": 5,
                    "failure_rate": 5.0,
                    "url": "http://localhost:8000/project/1/pipeline/destinations/test-hog-function-1",
                },
            ],
        }

        # Test with valid email override (user is member of org) - should send only to override email
        send_hog_functions_digest_email(digest_data, test_email_override="override@posthog.com")

        assert len(mocked_email_messages) == 1
        assert mocked_email_messages[0].send.call_count == 1
        # Should only be sent to the override email, not to other team members
        assert len(mocked_email_messages[0].to) == 1
        assert mocked_email_messages[0].to[0]["raw_email"] == "override@posthog.com"
        assert mocked_email_messages[0].html_body

        # Reset mocked messages
        mocked_email_messages.clear()

        # Test with invalid email override (user not member of org) - should not send email
        send_hog_functions_digest_email(digest_data, test_email_override="invalid@example.com")

        # No email should be sent since invalid@example.com is not a member of the organization
        assert len(mocked_email_messages) == 0

        # Test without email override - should follow normal notification settings
        send_hog_functions_digest_email(digest_data)

        # Should be sent to test2 and override user (both have notifications enabled), but not to main user
        # Each user now gets their own email
        assert len(mocked_email_messages) == 2
        sent_emails = {msg.to[0]["raw_email"] for msg in mocked_email_messages}
        assert "test2@posthog.com" in sent_emails
        assert "override@posthog.com" in sent_emails

    def test_send_hog_functions_digest_email_with_error_rate_threshold(self, MockEmailMessage: MagicMock) -> None:
        mocked_email_messages = mock_email_messages(MockEmailMessage)

        # Create users with different error rate thresholds
        # User with no threshold (default 0.0) - should receive all functions
        self._create_user("no_threshold@posthog.com")

        # User with 10% threshold - should only receive functions with failure_rate > 10%
        user_10_threshold = self._create_user("threshold_10@posthog.com")
        user_10_threshold.partial_notification_settings = {"data_pipeline_error_threshold": 0.1}
        user_10_threshold.save()

        # User with 50% threshold - should only receive functions with failure_rate > 50%
        user_50_threshold = self._create_user("threshold_50@posthog.com")
        user_50_threshold.partial_notification_settings = {"data_pipeline_error_threshold": 0.5}
        user_50_threshold.save()

        # User with 100% threshold - should not receive any email (no function can exceed 100%)
        user_100_threshold = self._create_user("threshold_100@posthog.com")
        user_100_threshold.partial_notification_settings = {"data_pipeline_error_threshold": 1.0}
        user_100_threshold.save()

        # Disable notifications for the main test user to simplify assertions
        self.user.partial_notification_settings = {"plugin_disabled": False}
        self.user.save()

        digest_data = {
            "team_id": self.team.id,
            "functions": [
                {
                    "id": "low-failure-function",
                    "name": "Low Failure Function",
                    "type": "destination",
                    "created_by_email": "creator@example.com",
                    "last_edited_by_email": "editor@example.com",
                    "last_edit_date": "2025-08-01",
                    "succeeded": 95,
                    "failed": 5,
                    "failure_rate": 5.0,  # 5% failure rate
                    "url": "http://localhost:8000/project/1/pipeline/destinations/low-failure-function",
                },
                {
                    "id": "medium-failure-function",
                    "name": "Medium Failure Function",
                    "type": "destination",
                    "created_by_email": "creator@example.com",
                    "last_edited_by_email": "editor@example.com",
                    "last_edit_date": "2025-08-02",
                    "succeeded": 75,
                    "failed": 25,
                    "failure_rate": 25.0,  # 25% failure rate
                    "url": "http://localhost:8000/project/1/pipeline/destinations/medium-failure-function",
                },
                {
                    "id": "high-failure-function",
                    "name": "High Failure Function",
                    "type": "destination",
                    "created_by_email": "creator@example.com",
                    "last_edited_by_email": "editor@example.com",
                    "last_edit_date": "2025-08-03",
                    "succeeded": 40,
                    "failed": 60,
                    "failure_rate": 60.0,  # 60% failure rate
                    "url": "http://localhost:8000/project/1/pipeline/destinations/high-failure-function",
                },
            ],
        }

        send_hog_functions_digest_email(digest_data)

        # Each user gets their own email (3 emails total - user_100_threshold gets none)
        assert len(mocked_email_messages) == 3

        # Collect emails by recipient for easier assertions
        emails_by_recipient: dict[str, MagicMock] = {}
        for msg in mocked_email_messages:
            assert len(msg.to) == 1  # Each message should have exactly one recipient
            recipient_email = msg.to[0]["raw_email"]
            emails_by_recipient[recipient_email] = msg

        # Verify user_no_threshold received all 3 functions (check html_body for function names)
        assert "no_threshold@posthog.com" in emails_by_recipient
        no_threshold_html = emails_by_recipient["no_threshold@posthog.com"].html_body
        assert "Low Failure Function" in no_threshold_html
        assert "Medium Failure Function" in no_threshold_html
        assert "High Failure Function" in no_threshold_html

        # Verify user_10_threshold received 2 functions (25% and 60%, not 5%)
        assert "threshold_10@posthog.com" in emails_by_recipient
        threshold_10_html = emails_by_recipient["threshold_10@posthog.com"].html_body
        assert "Low Failure Function" not in threshold_10_html
        assert "Medium Failure Function" in threshold_10_html
        assert "High Failure Function" in threshold_10_html

        # Verify user_50_threshold received only 1 function (60%, not 5% or 25%)
        assert "threshold_50@posthog.com" in emails_by_recipient
        threshold_50_html = emails_by_recipient["threshold_50@posthog.com"].html_body
        assert "Low Failure Function" not in threshold_50_html
        assert "Medium Failure Function" not in threshold_50_html
        assert "High Failure Function" in threshold_50_html

        # Verify user_100_threshold did not receive any email
        assert "threshold_100@posthog.com" not in emails_by_recipient

    def test_send_hog_functions_daily_digest_no_eligible_functions(self, MockEmailMessage: MagicMock) -> None:
        from posthog.test.fixtures import create_app_metric2

        # Clean up app_metrics2 table before test
        run_clickhouse_statement_in_parallel([TRUNCATE_APP_METRICS2_TABLE_SQL])

        mocked_email_messages = mock_email_messages(MockEmailMessage)

        # Test 1: No HogFunctions created - should not send email
        send_hog_functions_daily_digest()
        assert len(mocked_email_messages) == 0

        # Test 2: HogFunction with no failures - should not send email
        hog_function = HogFunction.objects.create(
            team=self.team,
            name="Working Function",
            type="destination",
            enabled=True,
            deleted=False,
            hog="return event",
            created_by=self.user,
        )

        # Only create successful metrics, no failures
        create_app_metric2(
            team_id=self.team.id,
            app_source="hog_function",
            app_source_id=str(hog_function.id),
            timestamp=timezone.now() - dt.timedelta(hours=1),  # Within last 24h
            metric_kind="success",
            metric_name="succeeded",
            count=100,
        )

        send_hog_functions_daily_digest()
        assert len(mocked_email_messages) == 0

        # Test 3: Disabled HogFunction with failures - should not send email
        HogFunction.objects.all().delete()  # Clear previous functions
        disabled_function = HogFunction.objects.create(
            team=self.team,
            name="Disabled Function",
            type="destination",
            enabled=False,  # Disabled
            deleted=False,
            hog="return event",
            created_by=self.user,
        )

        # Create failure metrics for disabled function
        create_app_metric2(
            team_id=self.team.id,
            app_source="hog_function",
            app_source_id=str(disabled_function.id),
            timestamp=timezone.now() - dt.timedelta(hours=1),  # Within last 24h
            metric_kind="failure",
            metric_name="failed",
            count=5,
        )

        send_hog_functions_daily_digest()
        assert len(mocked_email_messages) == 0

        # Test 4: Deleted HogFunction with failures - should not send email
        HogFunction.objects.all().delete()  # Clear previous functions
        deleted_function = HogFunction.objects.create(
            team=self.team,
            name="Deleted Function",
            type="destination",
            enabled=True,
            deleted=True,  # Deleted
            hog="return event",
            created_by=self.user,
        )

        # Create failure metrics for deleted function
        create_app_metric2(
            team_id=self.team.id,
            app_source="hog_function",
            app_source_id=str(deleted_function.id),
            timestamp=timezone.now() - dt.timedelta(hours=1),  # Within last 24h
            metric_kind="failure",
            metric_name="failed",
            count=5,
        )

        with self.settings(HOG_FUNCTIONS_DAILY_DIGEST_TEAM_IDS=[str(self.team.id)]):
            send_hog_functions_daily_digest()

        assert len(mocked_email_messages) == 0

    @patch("posthog.tasks.email.check_and_cache_login_device")
    def test_login_from_new_device_notification(
        self, mock_check_device: MagicMock, MockEmailMessage: MagicMock
    ) -> None:
        mocked_email_messages = mock_email_messages(MockEmailMessage)
        mock_check_device.return_value = True  # Simulate new device

        login_from_new_device_notification(
            user_id=self.user.id,
            login_time=timezone.now(),
            short_user_agent="Chrome 135.0.0 on Mac OS 15.3",
            ip_address="24.114.32.12",  # random ip in Canada
            backend_name="google-oauth2",
        )

        assert len(mocked_email_messages) == 1
        assert mocked_email_messages[0].send.call_count == 1
        assert mocked_email_messages[0].subject == "A new device logged into your account"

        # Check that location appears in email body
        html_body = mocked_email_messages[0].html_body
        assert html_body
        assert "Canada" in html_body
        assert "Google OAuth" in html_body

    @patch("posthog.tasks.email.check_and_cache_login_device")
    def test_login_from_new_device_notification_email_password(
        self, mock_check_device: MagicMock, MockEmailMessage: MagicMock
    ) -> None:
        mocked_email_messages = mock_email_messages(MockEmailMessage)
        mock_check_device.return_value = True  # Simulate new device

        login_from_new_device_notification(
            user_id=self.user.id,
            login_time=timezone.now(),
            short_user_agent="Chrome 135.0.0 on Mac OS 15.3",
            ip_address="24.114.32.12",  # random ip in Canada
            backend_name="django.contrib.auth.backends.ModelBackend",
        )

        assert len(mocked_email_messages) == 1
        assert mocked_email_messages[0].send.call_count == 1
        assert mocked_email_messages[0].subject == "A new device logged into your account"

        # Check that location appears in email body
        html_body = mocked_email_messages[0].html_body
        assert html_body
        assert "Canada" in html_body
        assert "Email/password" in html_body

    def test_send_new_ticket_notification(self, MockEmailMessage: MagicMock) -> None:
        from products.conversations.backend.models import Ticket

        mocked_email_messages = mock_email_messages(MockEmailMessage)

        # Set up notification recipients in team settings
        self.team.conversations_settings = {"notification_recipients": [self.user.id]}
        self.team.save()

        # Create a ticket
        ticket = Ticket.objects.create_with_number(
            team=self.team,
            widget_session_id="test-session-id",
            distinct_id="test-distinct-id",
            channel_source="widget",
            status="new",
            anonymous_traits={"name": "Test Customer", "email": "customer@example.com"},
        )

        send_new_ticket_notification(
            ticket_id=str(ticket.id),
            team_id=self.team.id,
            first_message_content="Hello, I need help with something",
        )

        assert len(mocked_email_messages) == 1
        assert mocked_email_messages[0].send.call_count == 1
        assert f"Ticket #{ticket.ticket_number}" in mocked_email_messages[0].subject
        assert mocked_email_messages[0].html_body
        assert "Test Customer" in mocked_email_messages[0].html_body
        assert "Hello, I need help with something" in mocked_email_messages[0].html_body

    def test_send_new_ticket_notification_no_recipients(self, MockEmailMessage: MagicMock) -> None:
        from products.conversations.backend.models import Ticket

        mocked_email_messages = mock_email_messages(MockEmailMessage)

        # No notification recipients configured
        self.team.conversations_settings = {}
        self.team.save()

        ticket = Ticket.objects.create_with_number(
            team=self.team,
            widget_session_id="test-session-id",
            distinct_id="test-distinct-id",
            channel_source="widget",
            status="new",
        )

        send_new_ticket_notification(
            ticket_id=str(ticket.id),
            team_id=self.team.id,
            first_message_content="Hello",
        )

        # No email should be sent
        assert len(mocked_email_messages) == 0

    def test_send_new_ticket_notification_recipient_without_access(self, MockEmailMessage: MagicMock) -> None:
        from products.conversations.backend.models import Ticket

        mocked_email_messages = mock_email_messages(MockEmailMessage)

        # Create another org and user who shouldn't have access
        other_org = Organization.objects.create(name="Other Org")
        other_user = User.objects.create_and_join(
            organization=other_org,
            email="other@example.com",
            password=None,
            level=OrganizationMembership.Level.OWNER,
        )

        # Set the other user as recipient (they don't have access to this team)
        self.team.conversations_settings = {"notification_recipients": [other_user.id]}
        self.team.save()

        ticket = Ticket.objects.create_with_number(
            team=self.team,
            widget_session_id="test-session-id",
            distinct_id="test-distinct-id",
            channel_source="widget",
            status="new",
        )

        send_new_ticket_notification(
            ticket_id=str(ticket.id),
            team_id=self.team.id,
            first_message_content="Hello",
        )

        # No email should be sent since recipient doesn't have access
        assert len(mocked_email_messages) == 0

    def test_send_discussions_mentioned_with_slug_generates_correct_href(self, MockEmailMessage: MagicMock) -> None:
        from posthog.models import Comment

        mocked_email_messages = mock_email_messages(MockEmailMessage)

        # Create a mentioned user
        mentioned_user = User.objects.create_and_join(
            organization=self.organization, email="mentioned@posthog.com", password=None
        )

        # Create a replay comment
        comment = Comment.objects.create(
            team=self.team,
            content="Test comment",
            scope="Replay",
            item_id="test-replay-id",
            created_by=self.user,
        )

        # Call task with explicit slug
        send_discussions_mentioned(
            comment_id=str(comment.id),
            mentioned_user_ids=[mentioned_user.id],
            slug="/replay/test-replay-id",
        )

        assert len(mocked_email_messages) == 1
        assert mocked_email_messages[0].send.call_count == 1

        # Verify the href in template context uses the provided slug
        actual_href = mocked_email_messages[0].properties["href"]
        expected_href = "http://localhost:8010/replay/test-replay-id"
        assert actual_href == expected_href, f"Expected {expected_href}, got {actual_href}"

    def test_send_discussions_mentioned_replay_without_slug_generates_href_from_item_id(
        self, MockEmailMessage: MagicMock
    ) -> None:
        from posthog.models import Comment

        mocked_email_messages = mock_email_messages(MockEmailMessage)

        mentioned_user = User.objects.create_and_join(
            organization=self.organization, email="mentioned2@posthog.com", password=None
        )

        # Create a replay comment
        comment = Comment.objects.create(
            team=self.team,
            content="Test comment",
            scope="Replay",
            item_id="replay-uuid-123",
            created_by=self.user,
        )

        # Call task without slug (empty string)
        send_discussions_mentioned(
            comment_id=str(comment.id),
            mentioned_user_ids=[mentioned_user.id],
            slug="",
        )

        assert len(mocked_email_messages) == 1
        assert mocked_email_messages[0].send.call_count == 1

        # Verify the href is auto-generated from scope and item_id
        assert mocked_email_messages[0].properties["href"] == "http://localhost:8010/replay/replay-uuid-123"

    def test_send_discussions_mentioned_notebook_without_slug_generates_href_from_item_id(
        self, MockEmailMessage: MagicMock
    ) -> None:
        from posthog.models import Comment

        mocked_email_messages = mock_email_messages(MockEmailMessage)

        mentioned_user = User.objects.create_and_join(
            organization=self.organization, email="mentioned3@posthog.com", password=None
        )

        # Create a notebook comment
        comment = Comment.objects.create(
            team=self.team,
            content="Notebook test comment",
            scope="Notebook",
            item_id="notebook-short-id",
            created_by=self.user,
        )

        # Call task without slug
        send_discussions_mentioned(
            comment_id=str(comment.id),
            mentioned_user_ids=[mentioned_user.id],
            slug="",
        )

        assert len(mocked_email_messages) == 1
        assert mocked_email_messages[0].send.call_count == 1

        # Verify the href is auto-generated for notebook
        assert mocked_email_messages[0].properties["href"] == "http://localhost:8010/notebook/notebook-short-id"

    def test_send_discussions_mentioned_unknown_scope_without_slug_falls_back_to_base_url(
        self, MockEmailMessage: MagicMock
    ) -> None:
        from posthog.models import Comment

        mocked_email_messages = mock_email_messages(MockEmailMessage)

        mentioned_user = User.objects.create_and_join(
            organization=self.organization, email="mentioned4@posthog.com", password=None
        )

        # Create a comment with unknown scope
        comment = Comment.objects.create(
            team=self.team,
            content="Unknown scope comment",
            scope="UnknownScope",
            item_id="some-item-id",
            created_by=self.user,
        )

        # Call task without slug
        send_discussions_mentioned(
            comment_id=str(comment.id),
            mentioned_user_ids=[mentioned_user.id],
            slug="",
        )

        assert len(mocked_email_messages) == 1
        assert mocked_email_messages[0].send.call_count == 1

        # Verify the href falls back to base URL
        assert mocked_email_messages[0].properties["href"] == "http://localhost:8010"
