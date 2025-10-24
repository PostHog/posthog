import pytest
from unittest.mock import MagicMock, patch

from django.test.client import Client as HttpClient

from rest_framework import status

from posthog.models.integration import PRIVATE_CHANNEL_WITHOUT_ACCESS, EmailIntegration, Integration, SlackIntegration
from posthog.models.organization import Organization
from posthog.models.personal_api_key import PersonalAPIKey, hash_key_value
from posthog.models.team import Team
from posthog.models.user import User


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
            "verified": False,
            "provider": "mailjet",
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

        mock_client.verify_email_domain.assert_called_once_with("posthog.com")

        integration.refresh_from_db()
        assert integration.config == {
            "email": self.valid_config["email"],
            "name": self.valid_config["name"],
            "domain": "posthog.com",
            "verified": False,
            "provider": "mailjet",
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

        mock_client.verify_email_domain.assert_called_once_with("posthog.com")

        integration.refresh_from_db()
        assert integration.config == {
            "email": self.valid_config["email"],
            "name": self.valid_config["name"],
            "domain": "posthog.com",
            "verified": True,
            "provider": "mailjet",
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

        assert not integration1.config["verified"]
        assert not integration2.config["verified"]
        assert not integrationOtherDomain.config["verified"]

        email_integration = EmailIntegration(integration1)
        verification_result = email_integration.verify()
        assert verification_result["status"] == "success"

        integration1.refresh_from_db()
        integration2.refresh_from_db()
        integrationOtherDomain.refresh_from_db()

        assert integration1.config["verified"]
        assert integration2.config["verified"]
        assert not integrationOtherDomain.config["verified"]


class TestDatabricksIntegration:
    @pytest.fixture(autouse=True)
    def setup_integration(self, db):
        self.organization = Organization.objects.create(name="Test Org")
        self.team = Team.objects.create(organization=self.organization, name="Test Team")
        self.user = User.objects.create_and_join(self.organization, "test@posthog.com", "test")

    @patch("posthog.models.integration.socket.socket")
    def test_integration_from_config_with_valid_config(
        self,
        mock_socket,
        client: HttpClient,
    ):
        mock_socket.return_value.connect.return_value = None
        client.force_login(self.user)

        response = client.post(
            f"/api/environments/{self.team.pk}/integrations",
            {
                "kind": "databricks",
                "config": {
                    "server_hostname": "databricks.com",
                    "client_id": "client_id",
                    "client_secret": "client_secret",
                },
            },
            content_type="application/json",
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert response.json()["kind"] == "databricks"

        # get integration from db
        id = response.json()["id"]
        integration = Integration.objects.get(id=id)
        assert integration.kind == "databricks"
        assert integration.team == self.team
        assert integration.config == {"server_hostname": "databricks.com"}
        assert integration.sensitive_config == {"client_id": "client_id", "client_secret": "client_secret"}
        assert integration.created_by == self.user
        assert integration.integration_id == "databricks.com"

    @pytest.mark.parametrize(
        "invalid_config,expected_error_message",
        [
            # missing client_secret
            (
                {"server_hostname": "databricks.com", "client_id": "client_id"},
                "Server hostname, client ID, and client secret must be provided",
            ),
            # missing client_id
            (
                {"server_hostname": "databricks.com", "client_secret": "client_secret"},
                "Server hostname, client ID, and client secret must be provided",
            ),
            # missing server_hostname
            (
                {"client_id": "client_id", "client_secret": "client_secret"},
                "Server hostname, client ID, and client secret must be provided",
            ),
            # missing all
            ({}, "Server hostname, client ID, and client secret must be provided"),
            # wrong type for client_secret
            (
                {"server_hostname": "databricks.com", "client_id": "client_id", "client_secret": 1},
                "Server hostname, client ID, and client secret must be strings",
            ),
        ],
    )
    @patch("posthog.models.integration.socket.socket")
    def test_integration_from_config_with_invalid_config(
        self,
        mock_socket,
        invalid_config,
        expected_error_message,
        client: HttpClient,
    ):
        mock_socket.return_value.connect.return_value = None
        client.force_login(self.user)

        response = client.post(
            f"/api/environments/{self.team.pk}/integrations",
            {
                "kind": "databricks",
                "config": invalid_config,
            },
            content_type="application/json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["detail"] == expected_error_message


class TestIntegrationAPIKeyAccess:
    @pytest.fixture(autouse=True)
    def setup_integration(self, db):
        self.organization = Organization.objects.create(name="Test Org")
        self.team = Team.objects.create(organization=self.organization, name="Test Team")
        self.user = User.objects.create_and_join(self.organization, "test@posthog.com", "test")

        self.github_integration = Integration.objects.create(
            team=self.team,
            kind="github",
            config={"installation_id": "12345"},
            sensitive_config={"access_token": "test-token"},
        )

        self.twilio_integration = Integration.objects.create(
            team=self.team,
            kind="twilio",
            config={"account_sid": "test_sid"},
            sensitive_config={"auth_token": "twilio-token"},
        )

    def test_list_integrations_without_scope_fails(self, client: HttpClient):
        key_value = "test_key_123"
        PersonalAPIKey.objects.create(
            label="Test Key",
            user=self.user,
            secure_value=hash_key_value(key_value),
            scopes=["feature_flag:read"],
        )

        response = client.get(
            f"/api/environments/{self.team.pk}/integrations/",
            HTTP_AUTHORIZATION=f"Bearer {key_value}",
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert "integration:read" in response.json()["detail"]

    def test_list_integrations_with_scope_succeeds(self, client: HttpClient):
        key_value = "test_key_123"
        PersonalAPIKey.objects.create(
            label="Test Key",
            user=self.user,
            secure_value=hash_key_value(key_value),
            scopes=["integration:read"],
        )

        response = client.get(
            f"/api/environments/{self.team.pk}/integrations/",
            HTTP_AUTHORIZATION=f"Bearer {key_value}",
        )

        assert response.status_code == status.HTTP_200_OK
        assert len(response.json()["results"]) == 1
        assert response.json()["results"][0]["kind"] == "github"

    def test_list_integrations_only_shows_github_for_api_keys(self, client: HttpClient):
        key_value = "test_key_123"
        PersonalAPIKey.objects.create(
            label="Test Key",
            user=self.user,
            secure_value=hash_key_value(key_value),
            scopes=["integration:read"],
        )

        response = client.get(
            f"/api/environments/{self.team.pk}/integrations/",
            HTTP_AUTHORIZATION=f"Bearer {key_value}",
        )

        assert response.status_code == status.HTTP_200_OK
        results = response.json()["results"]
        assert len(results) == 1
        assert results[0]["kind"] == "github"
        assert all(integration["kind"] == "github" for integration in results)

    def test_retrieve_github_integration_with_scope_succeeds(self, client: HttpClient):
        key_value = "test_key_123"
        PersonalAPIKey.objects.create(
            label="Test Key",
            user=self.user,
            secure_value=hash_key_value(key_value),
            scopes=["integration:read"],
        )

        response = client.get(
            f"/api/environments/{self.team.pk}/integrations/{self.github_integration.id}/",
            HTTP_AUTHORIZATION=f"Bearer {key_value}",
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["kind"] == "github"

    def test_retrieve_non_github_integration_with_api_key_fails(self, client: HttpClient):
        key_value = "test_key_123"
        PersonalAPIKey.objects.create(
            label="Test Key",
            user=self.user,
            secure_value=hash_key_value(key_value),
            scopes=["integration:read"],
        )

        response = client.get(
            f"/api/environments/{self.team.pk}/integrations/{self.twilio_integration.id}/",
            HTTP_AUTHORIZATION=f"Bearer {key_value}",
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND

    @patch("posthog.models.integration.GitHubIntegration.list_repositories")
    def test_github_repos_with_scope_succeeds(self, mock_list_repos, client: HttpClient):
        mock_list_repos.return_value = ["repo1", "repo2"]

        key_value = "test_key_123"
        PersonalAPIKey.objects.create(
            label="Test Key",
            user=self.user,
            secure_value=hash_key_value(key_value),
            scopes=["integration:read"],
        )

        response = client.get(
            f"/api/environments/{self.team.pk}/integrations/{self.github_integration.id}/github_repos/",
            HTTP_AUTHORIZATION=f"Bearer {key_value}",
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["repositories"] == ["repo1", "repo2"]

    def test_github_repos_without_scope_fails(self, client: HttpClient):
        key_value = "test_key_123"
        PersonalAPIKey.objects.create(
            label="Test Key",
            user=self.user,
            secure_value=hash_key_value(key_value),
            scopes=["feature_flag:read"],
        )

        response = client.get(
            f"/api/environments/{self.team.pk}/integrations/{self.github_integration.id}/github_repos/",
            HTTP_AUTHORIZATION=f"Bearer {key_value}",
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert "integration:read" in response.json()["detail"]

    def test_create_integration_with_api_key_fails(self, client: HttpClient):
        key_value = "test_key_123"
        PersonalAPIKey.objects.create(
            label="Test Key",
            user=self.user,
            secure_value=hash_key_value(key_value),
            scopes=["integration:read"],
        )

        response = client.post(
            f"/api/environments/{self.team.pk}/integrations/",
            {"kind": "github", "config": {"installation_id": "99999"}},
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {key_value}",
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert "integration:write" in response.json()["detail"]

    def test_delete_integration_with_api_key_fails(self, client: HttpClient):
        key_value = "test_key_123"
        PersonalAPIKey.objects.create(
            label="Test Key",
            user=self.user,
            secure_value=hash_key_value(key_value),
            scopes=["integration:read"],
        )

        response = client.delete(
            f"/api/environments/{self.team.pk}/integrations/{self.github_integration.id}/",
            HTTP_AUTHORIZATION=f"Bearer {key_value}",
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert "integration:write" in response.json()["detail"]

    def test_session_auth_shows_all_integrations(self, client: HttpClient):
        client.force_login(self.user)

        response = client.get(f"/api/environments/{self.team.pk}/integrations/")

        assert response.status_code == status.HTTP_200_OK
        results = response.json()["results"]
        assert len(results) == 2
        kinds = [integration["kind"] for integration in results]
        assert "github" in kinds
        assert "twilio" in kinds
