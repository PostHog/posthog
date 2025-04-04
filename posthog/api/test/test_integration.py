from unittest.mock import patch, MagicMock

import pytest

from posthog.models.integration import Integration
from posthog.models.integration import SlackIntegration, PRIVATE_CHANNEL_WITHOUT_ACCESS
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
