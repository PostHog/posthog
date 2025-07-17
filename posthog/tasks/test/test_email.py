import datetime as dt
from unittest.mock import MagicMock, patch

from django.utils import timezone
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
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, run_clickhouse_statement_in_parallel
from posthog.models.app_metrics2.sql import TRUNCATE_APP_METRICS2_TABLE_SQL


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
                    "succeeded": 95,
                    "failed": 5,
                    "filtered": 2,
                    "url": "http://localhost:8000/project/1/pipeline/destinations/test-hog-function-1",
                },
                {
                    "id": "test-hog-function-2",
                    "name": "Test Function 2",
                    "type": "transformation",
                    "succeeded": 200,
                    "failed": 50,
                    "filtered": 10,
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
                    "id": "test-hog-function",
                    "name": "Test Function",
                    "type": "destination",
                    "succeeded": 80,
                    "failed": 10,
                    "filtered": 5,
                    "url": "http://localhost:8000/project/1/pipeline/destinations/test-hog-function",
                }
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
                    "filtered": 3,
                    "url": "test",
                }
            ],
        }

        send_hog_functions_digest_email(digest_data)

        # Should not send any emails
        assert len(mocked_email_messages) == 0

    def test_send_hog_functions_daily_digest(self, MockEmailMessage: MagicMock) -> None:
        from posthog.test.fixtures import create_app_metric2

        # Clean up app_metrics2 table before test
        run_clickhouse_statement_in_parallel([TRUNCATE_APP_METRICS2_TABLE_SQL])

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
