import datetime as dt

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
    login_from_new_device_notification,
    send_async_migration_complete_email,
    send_async_migration_errored_email,
    send_batch_export_run_failure,
    send_canary_email,
    send_email_verification,
    send_fatal_plugin_error,
    send_hog_functions_daily_digest,
    send_hog_functions_digest_email,
    send_invite,
    send_member_join,
    send_password_reset,
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

        self._create_user("test2@posthog.com")
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
        assert mocked_email_messages[0].to == [{"recipient": "test2@posthog.com", "raw_email": "test2@posthog.com"}]

        self.user.partial_notification_settings = {"plugin_disabled": True}
        self.user.save()
        send_hog_functions_digest_email(digest_data)

        # Should now be sent to both users
        assert len(mocked_email_messages[1].to) == 2

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
        with self.settings(HOG_FUNCTIONS_DAILY_DIGEST_TEAM_IDS=[str(self.team.id)]):
            send_hog_functions_daily_digest()

        assert len(mocked_email_messages) == 1
        assert mocked_email_messages[0].send.call_count == 1
        assert mocked_email_messages[0].html_body

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

        assert len(mocked_email_messages) == 1
        assert mocked_email_messages[0].send.call_count == 1
        assert mocked_email_messages[0].html_body

        # Reset mocked messages
        mocked_email_messages.clear()

        # Test 4: Using '*' in allowlist - should send email to all teams with failures
        with self.settings(HOG_FUNCTIONS_DAILY_DIGEST_TEAM_IDS=["*"]):
            send_hog_functions_daily_digest()

        assert len(mocked_email_messages) == 1
        assert mocked_email_messages[0].send.call_count == 1
        assert mocked_email_messages[0].html_body

        # Reset mocked messages
        mocked_email_messages.clear()

        # Test 5: Test notification settings - user with plugin_disabled: False should not receive email
        self._create_user("test2@posthog.com")
        self.user.partial_notification_settings = {"plugin_disabled": False}
        self.user.save()

        send_hog_functions_daily_digest()
        # Should be sent to users with notifications enabled (creator, editor, test2)
        recipients = {recipient["raw_email"] for recipient in mocked_email_messages[0].to}
        expected_recipients = {"creator@posthog.com", "editor@posthog.com", "test2@posthog.com"}
        assert recipients == expected_recipients

        # Test 6: Test notification settings - user with plugin_disabled: True should receive email
        self.user.partial_notification_settings = {"plugin_disabled": True}
        self.user.save()

        send_hog_functions_daily_digest()
        # Should now be sent to all users (creator, editor, original user, test2)
        assert len(mocked_email_messages[1].to) == 4

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
        assert len(mocked_email_messages) == 1
        assert len(mocked_email_messages[0].to) == 2
        sent_emails = {recipient["raw_email"] for recipient in mocked_email_messages[0].to}
        assert "test2@posthog.com" in sent_emails
        assert "override@posthog.com" in sent_emails

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
