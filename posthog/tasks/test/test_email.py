from typing import Tuple
from unittest.mock import MagicMock, patch

from freezegun import freeze_time

from posthog.api.authentication import password_reset_token_generator
from posthog.api.email_verification import email_verification_token_generator
from posthog.models import Organization, Team, User
from posthog.models.instance_setting import set_instance_setting
from posthog.models.organization import OrganizationInvite, OrganizationMembership
from posthog.models.plugin import Plugin, PluginConfig
from posthog.tasks.email import (
    send_async_migration_complete_email,
    send_async_migration_errored_email,
    send_canary_email,
    send_email_verification,
    send_fatal_plugin_error,
    send_invite,
    send_member_join,
    send_password_reset,
)
from posthog.tasks.test.utils_email_tests import mock_email_messages
from posthog.test.base import APIBaseTest, ClickhouseTestMixin


def create_org_team_and_user(creation_date: str, email: str, ingested_event: bool = False) -> Tuple[Organization, User]:
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

    def test_send_email_verification(self, MockEmailMessage: MagicMock) -> None:
        mocked_email_messages = mock_email_messages(MockEmailMessage)
        org, user = create_org_team_and_user("2022-01-02 00:00:00", "admin@posthog.com")
        token = email_verification_token_generator.make_token(self.user)
        send_email_verification(user.id, token)

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
