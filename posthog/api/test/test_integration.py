from unittest.mock import patch, MagicMock

import pytest

from posthog.api.test.test_team import create_team
from posthog.models.integration import Integration
from posthog.models.integration import EmailIntegration, SlackIntegration, PRIVATE_CHANNEL_WITHOUT_ACCESS
from posthog.models.user import User
from posthog.models.organization import Organization
from posthog.models.team import Team


class TestSlackIntegration:
    @pytest.fixture(autouse=True)
    def setup_integration(self, db):
        self.user = User.objects.create(email="test@posthog.com")
        self.organization = Organization.objects.create(name="Test Org")
        self.team = Team.objects.create(organization=self.organization, name="Test Team")

        self.integration = Integration.objects.create(
            team=self.team,
            kind="slack",
            config={"authed_user": {"id": "test_user_id"}},
            sensitive_config={"access_token": "test-token-123"},
        )

    @patch("posthog.models.integration.WebClient")
    def test_list_channels_with_access(self, mock_webclient_class):
        mock_client = MagicMock()
        mock_webclient_class.return_value = mock_client

        mock_client.conversations_list.return_value = {
            "channels": [
                {"id": "C123", "name": "a_channel", "is_private": False, "is_ext_shared": False},
                {"id": "C456", "name": "b_channel", "is_private": False, "is_ext_shared": False},
                {"id": "C789", "name": "c_channel", "is_private": False, "is_ext_shared": False},
            ],
            "response_metadata": {"next_cursor": ""},
        }

        mock_client.users_conversations.return_value = {
            "channels": [
                {
                    "id": "CP123",
                    "name": "d_private_channel",
                    "is_private": True,
                    "is_ext_shared": False,
                }
            ],
            "response_metadata": {"next_cursor": ""},
        }

        slack = SlackIntegration(self.integration)

        channels = slack.list_channels(True, "test_user_id")

        mock_client.conversations_list.assert_called_once_with(
            exclude_archived=True, types="public_channel", limit=200, cursor=None
        )
        mock_client.users_conversations.assert_called_once_with(
            exclude_archived=True, types="private_channel", limit=200, cursor=None, user="test_user_id"
        )

        assert len(channels) == 4
        assert channels[0]["id"] == "C123"
        assert channels[0]["name"] == "a_channel"
        assert channels[3]["id"] == "CP123"
        assert channels[3]["name"] == "d_private_channel"

    @patch("posthog.models.integration.WebClient")
    def test_list_channels_without_access(self, mock_webclient_class):
        mock_client = MagicMock()
        mock_webclient_class.return_value = mock_client

        mock_client.conversations_list.return_value = {
            "channels": [
                {"id": "C123", "name": "a_channel", "is_private": False, "is_ext_shared": False},
                {"id": "C456", "name": "b_channel", "is_private": False, "is_ext_shared": False},
                {"id": "C789", "name": "c_channel", "is_private": False, "is_ext_shared": False},
            ],
            "response_metadata": {"next_cursor": ""},
        }

        mock_client.users_conversations.return_value = {
            "channels": [
                {
                    "id": "CP123",
                    "name": "d_private_channel",
                    "is_private": True,
                    "is_ext_shared": False,
                }
            ],
            "response_metadata": {"next_cursor": ""},
        }

        slack = SlackIntegration(self.integration)

        channels = slack.list_channels(False, "test_user_id")

        mock_client.conversations_list.assert_called_once_with(
            exclude_archived=True, types="public_channel", limit=200, cursor=None
        )
        mock_client.users_conversations.assert_called_once_with(
            exclude_archived=True, types="private_channel", limit=200, cursor=None, user="test_user_id"
        )

        assert len(channels) == 4
        assert channels[1]["id"] == "C123"
        assert channels[1]["name"] == "a_channel"
        assert channels[0]["id"] == "CP123"
        assert channels[0]["name"] == PRIVATE_CHANNEL_WITHOUT_ACCESS
        assert channels[0]["is_private_without_access"]

    @patch("posthog.models.integration.WebClient")
    def test_get_channel_by_id_private_with_access(self, mock_webclient_class):
        mock_client = MagicMock()
        mock_webclient_class.return_value = mock_client

        mock_client.conversations_info.return_value = {
            "channel": {"id": "C123", "name": "general", "is_private": True, "is_ext_shared": False, "num_members": 10}
        }

        mock_client.conversations_members.return_value = {"members": ["test_user_id", "U2", "U3"]}

        slack = SlackIntegration(self.integration)
        channel = slack.get_channel_by_id("C123", True, "test_user_id")

        mock_client.conversations_info.assert_called_once_with(channel="C123", include_num_members=True)
        mock_client.conversations_members.assert_called_once_with(channel="C123", limit=11)

        assert channel is not None
        assert channel["id"] == "C123"
        assert channel["name"] == "general"
        assert channel["is_private"]
        assert not channel["is_private_without_access"]

    @patch("posthog.models.integration.WebClient")
    def test_get_channel_by_id_private_without_access(self, mock_webclient_class):
        mock_client = MagicMock()
        mock_webclient_class.return_value = mock_client

        mock_client.conversations_info.return_value = {
            "channel": {"id": "C123", "name": "general", "is_private": True, "is_ext_shared": False, "num_members": 10}
        }

        mock_client.conversations_members.return_value = {"members": ["test_user_id", "U2", "U3"]}

        slack = SlackIntegration(self.integration)
        channel = slack.get_channel_by_id("C123", False, "test_user_id")

        mock_client.conversations_info.assert_called_once_with(channel="C123", include_num_members=True)
        mock_client.conversations_members.assert_called_once_with(channel="C123", limit=11)

        assert channel is not None
        assert channel["id"] == "C123"
        assert channel["name"] == PRIVATE_CHANNEL_WITHOUT_ACCESS
        assert channel["is_private"]
        assert channel["is_private_without_access"]

    @patch("posthog.models.integration.WebClient")
    def test_get_channel_by_id_public_with_access(self, mock_webclient_class):
        mock_client = MagicMock()
        mock_webclient_class.return_value = mock_client

        mock_client.conversations_info.return_value = {
            "channel": {"id": "C123", "name": "general", "is_private": False, "is_ext_shared": False, "num_members": 10}
        }

        mock_client.conversations_members.return_value = {"members": ["test_user_id", "U2", "U3"]}

        slack = SlackIntegration(self.integration)
        channel = slack.get_channel_by_id("C123", True, "test_user_id")

        mock_client.conversations_info.assert_called_once_with(channel="C123", include_num_members=True)
        mock_client.conversations_members.assert_called_once_with(channel="C123", limit=11)

        assert channel is not None
        assert channel["id"] == "C123"
        assert channel["name"] == "general"
        assert not channel["is_private"]
        assert not channel["is_private_without_access"]

    @patch("posthog.models.integration.WebClient")
    def test_get_channel_by_id_public_without_access(self, mock_webclient_class):
        mock_client = MagicMock()
        mock_webclient_class.return_value = mock_client

        mock_client.conversations_info.return_value = {
            "channel": {"id": "C123", "name": "general", "is_private": False, "is_ext_shared": False, "num_members": 10}
        }

        mock_client.conversations_members.return_value = {"members": ["test_user_id", "U2", "U3"]}

        slack = SlackIntegration(self.integration)
        channel = slack.get_channel_by_id("C123", False, "test_user_id")

        mock_client.conversations_info.assert_called_once_with(channel="C123", include_num_members=True)
        mock_client.conversations_members.assert_called_once_with(channel="C123", limit=11)

        assert channel is not None
        assert channel["id"] == "C123"
        assert channel["name"] == "general"
        assert not channel["is_private"]
        assert not channel["is_private_without_access"]


class TestEmailIntegration:
    @pytest.fixture(autouse=True)
    def setup_integration(self, db):
        self.valid_config = {
            "email": "test@posthog.com",
            "name": "Test User",
        }
        self.user = User.objects.create(email="test@posthog.com")
        self.organization = Organization.objects.create(name="Test Org")
        self.team = Team.objects.create(organization=self.organization, name="Test Team")

    @patch("posthog.models.integration.MailjetProvider")
    def test_integration_from_domain(self, mock_mailjet_provider_class):
        mock_client = MagicMock()
        mock_mailjet_provider_class.return_value = mock_client

        integration = EmailIntegration.create_native_integration(self.valid_config, self.team.id, self.user)
        assert integration.kind == "email"
        assert integration.integration_id == self.valid_config["email"]
        assert integration.team_id == self.team.id
        assert integration.config == {
            "email": self.valid_config["email"],
            "name": self.valid_config["name"],
            "domain": "posthog.com",
            "mailjet_verified": False,
            "aws_ses_verified": False,
        }
        assert integration.sensitive_config == {}
        assert integration.created_by == self.user

        mock_client.create_email_domain.assert_called_once_with("posthog.com", team_id=self.team.id)

    @patch("posthog.models.integration.MailjetProvider")
    def test_email_verify_returns_mailjet_result(self, mock_mailjet_provider_class):
        mock_client = MagicMock()
        mock_mailjet_provider_class.return_value = mock_client

        # Mock the verify_email_domain method to return a test result
        expected_result = {
            "status": "pending",
            "dnsRecords": [
                {
                    "type": "dkim",
                    "recordType": "TXT",
                    "recordHostname": "mailjet._domainkey.example.com",
                    "recordValue": "v=DKIM1; k=rsa; p=MIGfMA0GCSqGSIb3DQEBA...",
                    "status": "pending",
                },
                {
                    "type": "spf",
                    "recordType": "TXT",
                    "recordHostname": "@",
                    "recordValue": "v=spf1 include:spf.mailjet.com ~all",
                    "status": "pending",
                },
            ],
        }
        mock_client.verify_email_domain.return_value = expected_result

        integration = EmailIntegration.create_native_integration(self.valid_config, self.team.id, self.user)
        email_integration = EmailIntegration(integration)
        verification_result = email_integration.verify()

        assert verification_result == expected_result

        mock_client.verify_email_domain.assert_called_once_with("posthog.com", team_id=self.team.id)

        integration.refresh_from_db()
        assert integration.config == {
            "email": self.valid_config["email"],
            "name": self.valid_config["name"],
            "domain": "posthog.com",
            "mailjet_verified": False,
            "aws_ses_verified": False,
        }

    @patch("posthog.models.integration.MailjetProvider")
    def test_email_verify_updates_integration(self, mock_mailjet_provider_class):
        mock_client = MagicMock()
        mock_mailjet_provider_class.return_value = mock_client

        # Mock the verify_email_domain method to return a test result
        expected_result = {
            "status": "success",
            "dnsRecords": [
                {
                    "type": "dkim",
                    "recordType": "TXT",
                    "recordHostname": "mailjet._domainkey.example.com",
                    "recordValue": "v=DKIM1; k=rsa; p=MIGfMA0GCSqGSIb3DQEBA...",
                    "status": "success",
                },
                {
                    "type": "spf",
                    "recordType": "TXT",
                    "recordHostname": "@",
                    "recordValue": "v=spf1 include:spf.mailjet.com ~all",
                    "status": "success",
                },
            ],
        }
        mock_client.verify_email_domain.return_value = expected_result

        integration = EmailIntegration.create_native_integration(self.valid_config, self.team.id, self.user)
        email_integration = EmailIntegration(integration)
        verification_result = email_integration.verify()

        assert verification_result == expected_result

        mock_client.verify_email_domain.assert_called_once_with("posthog.com", team_id=self.team.id)

        integration.refresh_from_db()
        assert integration.config == {
            "email": self.valid_config["email"],
            "name": self.valid_config["name"],
            "domain": "posthog.com",
            "mailjet_verified": True,
            "aws_ses_verified": False,
        }

    @patch("posthog.models.integration.MailjetProvider")
    def test_email_verify_updates_all_other_integrations_with_same_domain(self, mock_mailjet_provider_class, settings):
        settings.MAILJET_PUBLIC_KEY = "test_api_key"
        settings.MAILJET_SECRET_KEY = "test_secret_key"

        mock_client = MagicMock()
        mock_mailjet_provider_class.return_value = mock_client
        # Mock the verify_email_domain method to return a test result
        expected_result = {
            "status": "success",
            "dnsRecords": [
                {
                    "type": "dkim",
                    "recordType": "TXT",
                    "recordHostname": "mailjet._domainkey.example.com",
                    "recordValue": "v=DKIM1; k=rsa; p=MIGfMA0GCSqGSIb3DQEBA...",
                    "status": "success",
                },
                {
                    "type": "spf",
                    "recordType": "TXT",
                    "recordHostname": "@",
                    "recordValue": "v=spf1 include:spf.mailjet.com ~all",
                    "status": "success",
                },
            ],
        }
        mock_client.verify_email_domain.return_value = expected_result

        integration1 = EmailIntegration.create_native_integration(self.valid_config, self.team.id, self.user)
        integration2 = EmailIntegration.create_native_integration(self.valid_config, self.team.id, self.user)
        integrationOtherDomain = EmailIntegration.create_native_integration(
            {
                "email": "me@otherdomain.com",
                "name": "Me",
            },
            self.team.id,
            self.user,
        )
        other_team = create_team(organization=self.organization)
        integrationOtherTeam = EmailIntegration.create_native_integration(
            {
                "email": "me@otherdomain.com",
                "name": "Me",
            },
            other_team.id,
            self.user,
        )

        assert not integration1.config["mailjet_verified"]
        assert not integration2.config["mailjet_verified"]
        assert not integrationOtherDomain.config["mailjet_verified"]
        assert not integrationOtherTeam.config["mailjet_verified"]

        email_integration = EmailIntegration(integration1)
        verification_result = email_integration.verify()
        assert verification_result["status"] == "success"

        integration1.refresh_from_db()
        integration2.refresh_from_db()
        integrationOtherDomain.refresh_from_db()
        integrationOtherTeam.refresh_from_db()

        assert integration1.config["mailjet_verified"]
        assert integration2.config["mailjet_verified"]
        assert not integrationOtherDomain.config["mailjet_verified"]
        assert not integrationOtherTeam.config["mailjet_verified"]
