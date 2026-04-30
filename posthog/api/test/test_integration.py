import hmac
import json
import time
import hashlib
from datetime import timedelta

import pytest
from unittest.mock import MagicMock, patch

from django.conf import settings as django_settings
from django.core.cache import cache
from django.test.client import Client as HttpClient
from django.utils import timezone

from rest_framework import status

from posthog.api.integration import IntegrationViewSet
from posthog.api.oauth.test_dcr import generate_rsa_key
from posthog.models.integration import (
    GITHUB_REPOSITORY_REFRESH_COOLDOWN_SECONDS,
    PRIVATE_CHANNEL_WITHOUT_ACCESS,
    SLACK_INTEGRATION_KINDS,
    EmailIntegration,
    GitHubIntegration,
    Integration,
    SlackIntegration,
    StripeIntegration,
)
from posthog.models.oauth import OAuthAccessToken, OAuthApplication, OAuthRefreshToken
from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.team import Team
from posthog.models.user import User
from posthog.models.utils import hash_key_value
from posthog.rate_limit import GitHubRepositoryRefreshThrottle


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

    @patch("posthog.models.integration.SESProvider")
    def test_integration_from_domain(self, mock_ses_provider_class):
        mock_client = MagicMock()
        mock_ses_provider_class.return_value = mock_client

        integration = EmailIntegration.create_native_integration(
            {**self.valid_config, "mail_from_subdomain": "youmustnothavelikedmyemail", "provider": "ses"},
            team_id=self.team.id,
            organization_id=self.organization.id,
            created_by=self.user,
        )
        assert integration.kind == "email"
        assert integration.integration_id == self.valid_config["email"]
        assert integration.team_id == self.team.id
        assert integration.config == {
            "email": self.valid_config["email"],
            "name": self.valid_config["name"],
            "domain": "posthog.com",
            "mail_from_subdomain": "youmustnothavelikedmyemail",
            "verified": False,
            "provider": "ses",
        }
        assert integration.sensitive_config == {}
        assert integration.created_by == self.user

        mock_client.create_email_domain.assert_called_once_with(
            "posthog.com", mail_from_subdomain="youmustnothavelikedmyemail", team_id=self.team.id
        )

    @patch("posthog.models.integration.SESProvider")
    def test_email_verify_returns_ses_result(self, mock_ses_provider_class):
        mock_client = MagicMock()
        mock_ses_provider_class.return_value = mock_client

        # Mock the verify_email_domain method to return a test result
        expected_result = {
            "status": "pending",
            "dnsRecords": [
                {
                    "type": "verification",
                    "recordType": "TXT",
                    "recordHostname": "_amazonses.posthog.com",
                    "recordValue": "test-verification-token",
                    "status": "pending",
                },
                {
                    "type": "dkim",
                    "recordType": "CNAME",
                    "recordHostname": "token1._domainkey.posthog.com",
                    "recordValue": "token1.dkim.amazonses.com",
                    "status": "pending",
                },
                {
                    "type": "spf",
                    "recordType": "TXT",
                    "recordHostname": "@",
                    "recordValue": "v=spf1 include:amazonses.com ~all",
                    "status": "pending",
                },
            ],
        }
        mock_client.verify_email_domain.return_value = expected_result

        integration = EmailIntegration.create_native_integration(
            {**self.valid_config, "provider": "ses"},
            team_id=self.team.id,
            organization_id=self.organization.id,
            created_by=self.user,
        )
        email_integration = EmailIntegration(integration)
        verification_result = email_integration.verify()

        assert verification_result == expected_result

        mock_client.verify_email_domain.assert_called_once_with(
            "posthog.com", mail_from_subdomain="feedback", team_id=self.team.id
        )

        integration.refresh_from_db()
        assert integration.config == {
            "email": self.valid_config["email"],
            "name": self.valid_config["name"],
            "domain": "posthog.com",
            "mail_from_subdomain": "feedback",
            "verified": False,
            "provider": "ses",
        }

    @patch("posthog.models.integration.SESProvider")
    def test_email_verify_updates_integration(self, mock_ses_provider_class):
        mock_client = MagicMock()
        mock_ses_provider_class.return_value = mock_client

        # Mock the verify_email_domain method to return a test result
        expected_result = {
            "status": "success",
            "dnsRecords": [],
        }
        mock_client.verify_email_domain.return_value = expected_result

        integration = EmailIntegration.create_native_integration(
            {**self.valid_config, "provider": "ses"},
            team_id=self.team.id,
            organization_id=self.organization.id,
            created_by=self.user,
        )
        email_integration = EmailIntegration(integration)
        verification_result = email_integration.verify()

        assert verification_result == expected_result

        mock_client.verify_email_domain.assert_called_once_with(
            "posthog.com", mail_from_subdomain="feedback", team_id=self.team.id
        )

        integration.refresh_from_db()
        assert integration.config == {
            "email": self.valid_config["email"],
            "name": self.valid_config["name"],
            "domain": "posthog.com",
            "mail_from_subdomain": "feedback",
            "verified": True,
            "provider": "ses",
        }

    @patch("posthog.models.integration.SESProvider")
    def test_email_verify_updates_all_other_integrations_with_same_domain(self, mock_ses_provider_class, settings):
        settings.SES_ACCESS_KEY_ID = "test_access_key"
        settings.SES_SECRET_ACCESS_KEY = "test_secret_key"

        mock_client = MagicMock()
        mock_ses_provider_class.return_value = mock_client
        # Mock the verify_email_domain method to return a test result
        expected_result = {
            "status": "success",
            "dnsRecords": [],
        }
        mock_client.verify_email_domain.return_value = expected_result

        integration1 = EmailIntegration.create_native_integration(
            {**self.valid_config, "provider": "ses"},
            team_id=self.team.id,
            organization_id=self.organization.id,
            created_by=self.user,
        )
        integration2 = EmailIntegration.create_native_integration(
            {**self.valid_config, "provider": "ses"},
            team_id=self.team.id,
            organization_id=self.organization.id,
            created_by=self.user,
        )
        integrationOtherDomain = EmailIntegration.create_native_integration(
            {
                "email": "me@otherdomain.com",
                "name": "Me",
                "mail_from_subdomain": "feedback",
                "provider": "ses",
            },
            team_id=self.team.id,
            organization_id=self.organization.id,
            created_by=self.user,
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
        self.user = User.objects.create_and_join(
            self.organization, "test@posthog.com", "test", level=OrganizationMembership.Level.ADMIN
        )

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

    @patch(
        "posthog.models.integration.get_instance_settings",
        return_value={
            "SLACK_APP_CLIENT_ID": "test-client-id",
            "SLACK_APP_CLIENT_SECRET": "test-client-secret",
            "SLACK_APP_SIGNING_SECRET": "test-signing-secret",
        },
    )
    def test_list_integrations_shows_github_and_slack_for_api_keys(self, _mock_settings, client: HttpClient):
        Integration.objects.create(
            team=self.team,
            kind="slack",
            integration_id="T_LIST",
            config={"authed_user": {"id": "test_user_id"}, "team": {"name": "Test Workspace"}},
            sensitive_config={"access_token": "test-token"},
            created_by=self.user,
        )

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
        kinds = {integration["kind"] for integration in results}
        assert kinds == {"github", "slack"}
        # twilio_integration is created in the fixture but should remain hidden from API-key callers.
        assert "twilio" not in kinds
        # Sensitive credentials never round-trip via the list serializer.
        assert all("sensitive_config" not in integration for integration in results)

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

    @patch(
        "posthog.models.integration.get_instance_settings",
        return_value={
            "SLACK_APP_CLIENT_ID": "test-client-id",
            "SLACK_APP_CLIENT_SECRET": "test-client-secret",
            "SLACK_APP_SIGNING_SECRET": "test-signing-secret",
        },
    )
    def test_retrieve_slack_integration_with_scope_succeeds(self, _mock_settings, client: HttpClient):
        slack_integration = Integration.objects.create(
            team=self.team,
            kind="slack",
            integration_id="T_RETRIEVE",
            config={"authed_user": {"id": "test_user_id"}, "team": {"name": "Test Workspace"}},
            sensitive_config={"access_token": "test-token"},
            created_by=self.user,
        )

        key_value = "test_key_retrieve_slack"
        PersonalAPIKey.objects.create(
            label="Test Key",
            user=self.user,
            secure_value=hash_key_value(key_value),
            scopes=["integration:read"],
        )

        response = client.get(
            f"/api/environments/{self.team.pk}/integrations/{slack_integration.id}/",
            HTTP_AUTHORIZATION=f"Bearer {key_value}",
        )

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["kind"] == "slack"
        # Sensitive credentials never round-trip via the retrieve serializer.
        assert "sensitive_config" not in body

    @patch("posthog.models.integration.GitHubIntegration.list_cached_repositories")
    def test_github_repos_with_scope_succeeds(self, mock_list_repos, client: HttpClient):
        mock_list_repos.return_value = (
            [
                {"id": 1, "name": "repo1", "full_name": "org/repo1"},
                {"id": 2, "name": "repo2", "full_name": "org/repo2"},
            ],
            False,
        )

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
        data = response.json()
        assert len(data["repositories"]) == 2
        assert data["repositories"][0]["name"] == "repo1"
        assert data["repositories"][1]["name"] == "repo2"
        assert data["has_more"] is False
        mock_list_repos.assert_called_once_with(search="", limit=100, offset=0)

    @patch("posthog.models.integration.GitHubIntegration.list_cached_repositories")
    def test_github_repos_pagination(self, mock_list_repos, client: HttpClient):
        repos = [{"id": i, "name": f"repo{i}", "full_name": f"org/repo{i}"} for i in range(100)]
        mock_list_repos.return_value = (repos, True)

        key_value = "test_key_123"
        PersonalAPIKey.objects.create(
            label="Test Key",
            user=self.user,
            secure_value=hash_key_value(key_value),
            scopes=["integration:read"],
        )

        response = client.get(
            f"/api/environments/{self.team.pk}/integrations/{self.github_integration.id}/github_repos/?limit=100&offset=100",
            HTTP_AUTHORIZATION=f"Bearer {key_value}",
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data["repositories"]) == 100
        assert data["has_more"] is True
        mock_list_repos.assert_called_once_with(search="", limit=100, offset=100)

    @patch("posthog.models.integration.GitHubIntegration.list_cached_repositories")
    def test_github_repos_has_more_false_when_partial_page(self, mock_list_repos, client: HttpClient):
        repos = [{"id": i, "name": f"repo{i}", "full_name": f"org/repo{i}"} for i in range(50)]
        mock_list_repos.return_value = (repos, False)

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
        data = response.json()
        assert len(data["repositories"]) == 50
        assert data["has_more"] is False

    @patch("posthog.models.integration.GitHubIntegration.list_cached_repositories")
    def test_github_repos_passes_limit_offset(self, mock_list_repos, client: HttpClient):
        repos = [{"id": i, "name": f"repo{i}", "full_name": f"org/repo{i}"} for i in range(10)]
        mock_list_repos.return_value = (repos, True)

        key_value = "test_key_123"
        PersonalAPIKey.objects.create(
            label="Test Key",
            user=self.user,
            secure_value=hash_key_value(key_value),
            scopes=["integration:read"],
        )

        response = client.get(
            f"/api/environments/{self.team.pk}/integrations/{self.github_integration.id}/github_repos/?limit=10&offset=50",
            HTTP_AUTHORIZATION=f"Bearer {key_value}",
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data["repositories"]) == 10
        assert data["has_more"] is True
        mock_list_repos.assert_called_once_with(search="", limit=10, offset=50)

    @patch("posthog.models.integration.GitHubIntegration.list_cached_repositories")
    def test_github_repos_passes_search_before_pagination(self, mock_list_repos, client: HttpClient):
        repos = [{"id": 2, "name": "posthog-js", "full_name": "org/posthog-js"}]
        mock_list_repos.return_value = (repos, False)

        key_value = "test_key_123"
        PersonalAPIKey.objects.create(
            label="Test Key",
            user=self.user,
            secure_value=hash_key_value(key_value),
            scopes=["integration:read"],
        )

        response = client.get(
            f"/api/environments/{self.team.pk}/integrations/{self.github_integration.id}/github_repos/?search=posthog&limit=1&offset=1",
            HTTP_AUTHORIZATION=f"Bearer {key_value}",
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["repositories"] == repos
        assert data["has_more"] is False
        mock_list_repos.assert_called_once_with(search="posthog", limit=1, offset=1)

    @patch("posthog.models.integration.GitHubIntegration.sync_repository_cache")
    def test_refresh_github_repos_with_write_scope_succeeds(self, mock_sync_repository_cache, client: HttpClient):
        mock_sync_repository_cache.return_value = [
            {"id": 1, "name": "repo1", "full_name": "org/repo1"},
            {"id": 2, "name": "repo2", "full_name": "org/repo2"},
        ]

        key_value = "test_key_123"
        PersonalAPIKey.objects.create(
            label="Test Key",
            user=self.user,
            secure_value=hash_key_value(key_value),
            scopes=["integration:write"],
        )

        response = client.post(
            f"/api/environments/{self.team.pk}/integrations/{self.github_integration.id}/github_repos/refresh/",
            HTTP_AUTHORIZATION=f"Bearer {key_value}",
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data["repositories"]) == 2
        assert data["repositories"][0]["full_name"] == "org/repo1"
        mock_sync_repository_cache.assert_called_once_with(
            min_refresh_interval_seconds=GITHUB_REPOSITORY_REFRESH_COOLDOWN_SECONDS
        )

    @patch("posthog.models.integration.GitHubIntegration.sync_repository_cache")
    def test_refresh_github_repos_uses_sync_path_even_with_fresh_cache(
        self,
        mock_sync_repository_cache,
        client: HttpClient,
    ):
        mock_sync_repository_cache.return_value = [
            {"id": 1, "name": "repo1", "full_name": "org/repo1"},
        ]

        key_value = "test_key_123"
        PersonalAPIKey.objects.create(
            label="Test Key",
            user=self.user,
            secure_value=hash_key_value(key_value),
            scopes=["integration:write"],
        )

        response = client.post(
            f"/api/environments/{self.team.pk}/integrations/{self.github_integration.id}/github_repos/refresh/",
            HTTP_AUTHORIZATION=f"Bearer {key_value}",
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["repositories"] == [{"id": 1, "name": "repo1", "full_name": "org/repo1"}]
        mock_sync_repository_cache.assert_called_once_with(
            min_refresh_interval_seconds=GITHUB_REPOSITORY_REFRESH_COOLDOWN_SECONDS
        )

    @patch("posthog.models.integration.GitHubIntegration.sync_repository_cache")
    def test_refresh_github_repos_with_read_scope_fails(self, mock_sync_repository_cache, client: HttpClient):
        key_value = "test_key_123"
        PersonalAPIKey.objects.create(
            label="Test Key",
            user=self.user,
            secure_value=hash_key_value(key_value),
            scopes=["integration:read"],
        )

        response = client.post(
            f"/api/environments/{self.team.pk}/integrations/{self.github_integration.id}/github_repos/refresh/",
            HTTP_AUTHORIZATION=f"Bearer {key_value}",
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert "integration:write" in response.json()["detail"]
        mock_sync_repository_cache.assert_not_called()

    def test_refresh_github_repos_is_mapped_as_write_action(self):
        assert "refresh_github_repos" in IntegrationViewSet.scope_object_write_actions

    def test_refresh_github_repos_uses_dedicated_refresh_throttle(self):
        view = IntegrationViewSet()
        view.action = "refresh_github_repos"

        throttles = view.get_throttles()

        assert any(isinstance(throttle, GitHubRepositoryRefreshThrottle) for throttle in throttles)

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

    @pytest.mark.parametrize(
        "kind,scope,expected_status,expected_detail_substring",
        [
            ("slack", "integration:read", status.HTTP_200_OK, None),
            ("slack-posthog-code", "integration:read", status.HTTP_200_OK, None),
            ("slack", "feature_flag:read", status.HTTP_403_FORBIDDEN, "integration:read"),
            # GitHub passes the queryset filter (it's a read-allowed kind) but the channels
            # action's kind guard rejects it with a 400 before SlackIntegration is constructed.
            ("github", "integration:read", status.HTTP_400_BAD_REQUEST, "Slack"),
            # Twilio is filtered out of the queryset entirely for API-key callers — 404.
            ("twilio", "integration:read", status.HTTP_404_NOT_FOUND, None),
        ],
    )
    @patch("posthog.api.integration.SlackIntegration")
    def test_channels_action_auth_and_kind_matrix(
        self,
        mock_slack_class,
        kind: str,
        scope: str,
        expected_status: int,
        expected_detail_substring: str | None,
        client: HttpClient,
    ):
        if kind in SLACK_INTEGRATION_KINDS:
            target_integration = Integration.objects.create(
                team=self.team,
                kind=kind,
                integration_id=f"T_{kind.upper()}",
                config={"authed_user": {"id": "test_user_id"}},
                sensitive_config={"access_token": "test-token-123"},
                created_by=self.user,
            )
        elif kind == "github":
            target_integration = self.github_integration
        elif kind == "twilio":
            target_integration = self.twilio_integration
        else:
            raise ValueError(f"Unhandled kind in test parameters: {kind}")

        mock_slack_instance = MagicMock()
        mock_slack_instance.list_channels.return_value = [
            {
                "id": "C1",
                "name": "general",
                "is_private": False,
                "is_member": True,
                "is_ext_shared": False,
                "is_private_without_access": False,
            },
            {
                "id": "C2",
                "name": "random",
                "is_private": False,
                "is_member": True,
                "is_ext_shared": False,
                "is_private_without_access": False,
            },
        ]
        mock_slack_class.return_value = mock_slack_instance

        key_value = f"test_key_{kind}_{scope}".replace(":", "_").replace("-", "_")
        PersonalAPIKey.objects.create(
            label="Test Key",
            user=self.user,
            secure_value=hash_key_value(key_value),
            scopes=[scope],
        )

        response = client.get(
            f"/api/environments/{self.team.pk}/integrations/{target_integration.id}/channels/",
            HTTP_AUTHORIZATION=f"Bearer {key_value}",
        )

        assert response.status_code == expected_status
        if expected_status == status.HTTP_200_OK:
            data = response.json()
            assert len(data["channels"]) == 2
            assert data["channels"][0]["id"] == "C1"
            assert data["channels"][0]["name"] == "general"
            assert data["channels"][0]["is_private_without_access"] is False
        elif expected_detail_substring is not None:
            assert expected_detail_substring in response.json()["detail"]

    def test_channels_action_with_missing_authed_user_returns_400(self, client: HttpClient):
        slack_integration = Integration.objects.create(
            team=self.team,
            kind="slack",
            integration_id="T_NOAUTHEDUSER",
            config={},
            sensitive_config={"access_token": "test-token"},
            created_by=self.user,
        )

        key_value = "test_key_no_authed_user"
        PersonalAPIKey.objects.create(
            label="Test Key",
            user=self.user,
            secure_value=hash_key_value(key_value),
            scopes=["integration:read"],
        )

        response = client.get(
            f"/api/environments/{self.team.pk}/integrations/{slack_integration.id}/channels/",
            HTTP_AUTHORIZATION=f"Bearer {key_value}",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "authed_user" in response.json()["detail"]

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


class TestGitHubIntegrationStateValidation:
    @pytest.fixture(autouse=True)
    def setup_environment(self, db):
        self.organization = Organization.objects.create(name="Test Org")
        self.team = Team.objects.create(organization=self.organization, name="Test Team")
        self.user = User.objects.create_and_join(
            self.organization, "test@posthog.com", "test", level=OrganizationMembership.Level.ADMIN
        )

    def _github_config(self, **overrides):
        base = {"installation_id": "12345", "state": "valid-token", "code": "oauth-code-abc"}
        base.update(overrides)
        return base

    @patch("posthog.models.integration.GitHubIntegration.integration_from_installation_id")
    def test_create_github_integration_without_state_rejected(self, mock_from_install, client: HttpClient):
        client.force_login(self.user)

        response = client.post(
            f"/api/environments/{self.team.pk}/integrations/",
            {"kind": "github", "config": {"installation_id": "12345", "code": "some-code"}},
            content_type="application/json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "state token must be provided" in response.json()["detail"]
        mock_from_install.assert_not_called()

    @patch("posthog.models.integration.GitHubIntegration.integration_from_installation_id")
    def test_create_github_integration_without_code_rejected(self, mock_from_install, client: HttpClient):
        client.force_login(self.user)

        response = client.post(
            f"/api/environments/{self.team.pk}/integrations/",
            {"kind": "github", "config": {"installation_id": "12345", "state": "some-state"}},
            content_type="application/json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "OAuth code must be provided" in response.json()["detail"]
        mock_from_install.assert_not_called()

    @patch("posthog.models.integration.GitHubIntegration.integration_from_installation_id")
    def test_create_github_integration_with_invalid_state_rejected(self, mock_from_install, client: HttpClient):
        client.force_login(self.user)
        cache.set(f"github_state:{self.user.id}", "correct-token", timeout=300)

        response = client.post(
            f"/api/environments/{self.team.pk}/integrations/",
            {"kind": "github", "config": self._github_config(state="wrong-token")},
            content_type="application/json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "Invalid or expired state token" in response.json()["detail"]
        mock_from_install.assert_not_called()

    @patch("posthog.models.integration.GitHubIntegration.integration_from_installation_id")
    def test_create_github_integration_with_expired_state_rejected(self, mock_from_install, client: HttpClient):
        client.force_login(self.user)
        # No token in cache = expired

        response = client.post(
            f"/api/environments/{self.team.pk}/integrations/",
            {"kind": "github", "config": self._github_config(state="some-token")},
            content_type="application/json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "Invalid or expired state token" in response.json()["detail"]
        mock_from_install.assert_not_called()

    @patch("posthog.models.github_integration_base.GitHubIntegrationBase.verify_user_installation_access")
    @patch("posthog.models.integration.GitHubIntegration.github_user_from_code")
    @patch("posthog.models.integration.GitHubIntegration.integration_from_installation_id")
    @patch("posthog.models.user_integration.user_github_integration_from_installation")
    def test_create_github_integration_with_valid_state_succeeds(
        self, mock_user_integration, mock_from_install, mock_from_code, mock_verify, client: HttpClient
    ):
        from posthog.models.integration import GitHubUserAuthorization

        client.force_login(self.user)
        state_token = "valid-token-abc123"
        cache.set(f"github_state:{self.user.id}", state_token, timeout=300)

        mock_from_code.return_value = GitHubUserAuthorization(
            gh_id=42,
            gh_login="testuser",
            access_token="ghu_test",
            refresh_token=None,
            access_token_expires_in=None,
            refresh_token_expires_in=None,
        )
        mock_verify.return_value = True
        mock_integration = Integration.objects.create(
            team=self.team,
            kind="github",
            integration_id="12345",
            config={"installation_id": "12345"},
            sensitive_config={"access_token": "ghs_test"},
        )
        mock_from_install.return_value = mock_integration

        response = client.post(
            f"/api/environments/{self.team.pk}/integrations/",
            {"kind": "github", "config": self._github_config(state=state_token)},
            content_type="application/json",
        )

        assert response.status_code == status.HTTP_201_CREATED
        mock_from_code.assert_called_once_with("oauth-code-abc")
        mock_verify.assert_called_once_with("12345", "ghu_test")
        mock_from_install.assert_called_once_with("12345", self.team.pk, self.user)
        # Token consumed — cannot be reused
        assert cache.get(f"github_state:{self.user.id}") is None

    @patch("posthog.models.github_integration_base.GitHubIntegrationBase.verify_user_installation_access")
    @patch("posthog.models.integration.GitHubIntegration.github_user_from_code")
    @patch("posthog.models.integration.GitHubIntegration.integration_from_installation_id")
    @patch("posthog.models.user_integration.user_github_integration_from_installation")
    def test_create_github_integration_state_token_single_use(
        self, mock_user_integration, mock_from_install, mock_from_code, mock_verify, client: HttpClient
    ):
        from posthog.models.integration import GitHubUserAuthorization

        client.force_login(self.user)
        state_token = "single-use-token"
        cache.set(f"github_state:{self.user.id}", state_token, timeout=300)

        mock_from_code.return_value = GitHubUserAuthorization(
            gh_id=42,
            gh_login="testuser",
            access_token="ghu_test",
            refresh_token=None,
            access_token_expires_in=None,
            refresh_token_expires_in=None,
        )
        mock_verify.return_value = True
        mock_integration = Integration.objects.create(
            team=self.team,
            kind="github",
            integration_id="12345",
            config={"installation_id": "12345"},
            sensitive_config={"access_token": "ghs_test"},
        )
        mock_from_install.return_value = mock_integration

        # First request succeeds
        response = client.post(
            f"/api/environments/{self.team.pk}/integrations/",
            {"kind": "github", "config": self._github_config(state=state_token)},
            content_type="application/json",
        )
        assert response.status_code == status.HTTP_201_CREATED

        # Second request with same token fails
        response = client.post(
            f"/api/environments/{self.team.pk}/integrations/",
            {"kind": "github", "config": self._github_config(state=state_token)},
            content_type="application/json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "Invalid or expired state token" in response.json()["detail"]

    @patch("posthog.models.integration.GitHubIntegration.integration_from_installation_id")
    def test_create_github_integration_cross_user_state_rejected(self, mock_from_install, client: HttpClient):
        other_user = User.objects.create_and_join(
            self.organization, "attacker@posthog.com", "test", level=OrganizationMembership.Level.ADMIN
        )
        client.force_login(other_user)
        # Token belongs to self.user, not other_user
        cache.set(f"github_state:{self.user.id}", "victim-token", timeout=300)

        response = client.post(
            f"/api/environments/{self.team.pk}/integrations/",
            {"kind": "github", "config": self._github_config(state="victim-token")},
            content_type="application/json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "Invalid or expired state token" in response.json()["detail"]
        mock_from_install.assert_not_called()

    @patch("posthog.models.integration.GitHubIntegration.github_user_from_code")
    @patch("posthog.models.integration.GitHubIntegration.integration_from_installation_id")
    def test_create_github_integration_code_exchange_failure_rejected(
        self, mock_from_install, mock_from_code, client: HttpClient
    ):
        client.force_login(self.user)
        state_token = "valid-token"
        cache.set(f"github_state:{self.user.id}", state_token, timeout=300)

        mock_from_code.return_value = None

        response = client.post(
            f"/api/environments/{self.team.pk}/integrations/",
            {"kind": "github", "config": self._github_config(state=state_token)},
            content_type="application/json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "Failed to exchange the OAuth code" in response.json()["detail"]
        mock_from_install.assert_not_called()

    @patch("posthog.models.integration.GitHubIntegration.github_user_from_code")
    @patch("posthog.models.integration.GitHubIntegration.integration_from_installation_id")
    def test_create_github_integration_rejects_foreign_installation_id(
        self, mock_from_install, mock_user_from_code, client: HttpClient
    ):
        """A user must not be able to write a personal UserIntegration carrying another
        tenant's GitHub installation tokens by submitting a foreign ``installation_id``
        alongside their own valid state token and OAuth code.

        The state token cached at ``/integrations/authorize`` binds only to the calling
        user's id, and the GitHub App's JWT can mint installation tokens for any of the
        App's installations — so per-user authorization for the supplied
        ``installation_id`` must be enforced in the create path itself (e.g. by calling
        GitHub's ``/user/installations/{installation_id}/repositories`` with the OAuth
        user token before persisting, or by binding ``installation_id`` into the cached
        state). Without that check, the auto-created UserIntegration would let the caller
        act as themselves on repos belonging to a different tenant.
        """
        from posthog.models.integration import GitHubUserAuthorization
        from posthog.models.user_integration import UserIntegration

        FOREIGN_INSTALLATION_ID = "999888777"  # belongs to another tenant
        ATTACKER_GH_LOGIN = "mallory"
        ATTACKER_USER_TOKEN = "gho_attacker_user_token"  # nosec
        VICTIM_INSTALLATION_TOKEN = "ghs_victim_installation_token"  # nosec

        client.force_login(self.user)
        state_token = "valid-attacker-state"
        cache.set(f"github_state:{self.user.id}", state_token, timeout=300)

        # The App-JWT call in integration_from_installation_id succeeds for any of the
        # App's installations (this is intrinsic to GitHub Apps — the JWT is App-scoped,
        # not user-scoped), so per-user authorization must be forced separately.
        foreign_integration = Integration.objects.create(
            team=self.team,
            kind="github",
            integration_id=FOREIGN_INSTALLATION_ID,
            config={
                "installation_id": FOREIGN_INSTALLATION_ID,
                "expires_in": 3600,
                "refreshed_at": int(time.time()),
                "repository_selection": "all",
                "account": {"type": "Organization", "name": "victim-org"},
            },
            sensitive_config={"access_token": VICTIM_INSTALLATION_TOKEN},
            created_by=self.user,
        )
        mock_from_install.return_value = foreign_integration

        # Caller's OAuth code exchange returns their identity + user-to-server token.
        # This token does NOT have access to FOREIGN_INSTALLATION_ID; the create path
        # must confirm that with GitHub before persisting any user-scoped credentials.
        mock_user_from_code.return_value = GitHubUserAuthorization(
            gh_id=12345,
            gh_login=ATTACKER_GH_LOGIN,
            access_token=ATTACKER_USER_TOKEN,
            refresh_token="ghr_attacker_refresh",
            access_token_expires_in=28800,
            refresh_token_expires_in=15897600,
        )

        client.post(
            f"/api/environments/{self.team.pk}/integrations/",
            {
                "kind": "github",
                "config": {
                    "installation_id": FOREIGN_INSTALLATION_ID,
                    "state": state_token,
                    "code": "attacker_oauth_code",
                },
            },
            content_type="application/json",
        )

        # No UserIntegration may be written for an installation the caller has not been
        # confirmed to own. Either the request is rejected, or it succeeds without the
        # auto-create — both are acceptable; the row simply must not exist.
        attacker_user_integration = UserIntegration.objects.filter(
            user=self.user, kind="github", integration_id=FOREIGN_INSTALLATION_ID
        ).first()

        assert attacker_user_integration is None, (
            "A UserIntegration was written carrying a foreign installation's access token "
            "without confirming the caller owns the installation. The create path must call "
            "GitHub's /user/installations/{installation_id}/repositories with the OAuth user "
            "token (or otherwise bind installation_id into the cached state) before writing."
        )


class TestStripeIntegration:
    @pytest.fixture(autouse=True)
    def setup_integration(self, db):
        self.organization = Organization.objects.create(name="Test Org")
        self.team = Team.objects.create(organization=self.organization, name="Test Team")
        self.user = User.objects.create_and_join(
            self.organization, "test@posthog.com", "test", level=OrganizationMembership.Level.ADMIN
        )

    def _create_stripe_integration(self) -> Integration:
        return Integration.objects.create(
            team=self.team,
            kind="stripe",
            config={"account_name": "Test Business (acct_123)"},
            sensitive_config={"access_token": "sk_live_test123"},
            integration_id="acct_123",
            created_by=self.user,
        )

    @patch("posthog.api.integration.StripeIntegration")
    def test_destroy_calls_clear_posthog_secrets(self, MockStripeIntegration, client: HttpClient):
        integration = self._create_stripe_integration()
        mock_instance = MagicMock()
        MockStripeIntegration.return_value = mock_instance

        client.force_login(self.user)
        response = client.delete(f"/api/environments/{self.team.pk}/integrations/{integration.id}/")

        assert response.status_code == status.HTTP_204_NO_CONTENT
        MockStripeIntegration.assert_called_once()
        mock_instance.clear_posthog_secrets.assert_called_once()
        assert not Integration.objects.filter(id=integration.id).exists()

    @patch("posthog.api.integration.StripeIntegration")
    def test_destroy_still_deletes_when_clear_secrets_fails(self, MockStripeIntegration, client: HttpClient):
        integration = self._create_stripe_integration()
        mock_instance = MagicMock()
        mock_instance.clear_posthog_secrets.side_effect = Exception("Stripe API error")
        MockStripeIntegration.return_value = mock_instance

        client.force_login(self.user)
        response = client.delete(f"/api/environments/{self.team.pk}/integrations/{integration.id}/")

        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert not Integration.objects.filter(id=integration.id).exists()

    def test_destroy_non_stripe_does_not_call_clear_secrets(self, client: HttpClient):
        integration = Integration.objects.create(
            team=self.team,
            kind="slack",
            config={"authed_user": {"id": "U123"}},
            sensitive_config={"access_token": "xoxb-test"},
            created_by=self.user,
        )

        client.force_login(self.user)
        with patch("posthog.api.integration.StripeIntegration") as MockStripeIntegration:
            response = client.delete(f"/api/environments/{self.team.pk}/integrations/{integration.id}/")

        assert response.status_code == status.HTTP_204_NO_CONTENT
        MockStripeIntegration.assert_not_called()
        assert not Integration.objects.filter(id=integration.id).exists()

    @pytest.fixture()
    def stripe_settings(self, settings):
        settings.STRIPE_APP_CLIENT_ID = "ca_test123"
        settings.STRIPE_APP_SECRET_KEY = "sk_test_secret"
        settings.STRIPE_SIGNING_SECRET = "whsec_test_signing"
        return settings

    def _make_install_signature(
        self, state: str, user_id: str, account_id: str, secret: str = "whsec_test_signing"
    ) -> str:
        """Build a valid t=...,v1=... header for a marketplace install callback."""
        ts = int(time.time())
        payload = json.dumps(
            {"state": state, "user_id": user_id, "account_id": account_id},
            separators=(",", ":"),
        )
        signed = f"{ts}.{payload}".encode()
        digest = hmac.new(secret.encode("utf-8"), signed, hashlib.sha256).hexdigest()
        return f"t={ts},v1={digest}"

    @patch("posthog.api.integration.StripeIntegration")
    @patch("posthog.api.integration.OauthIntegration.integration_from_oauth_response")
    def test_create_calls_write_posthog_secrets(
        self, mock_oauth_response, MockStripeIntegration, stripe_settings, client: HttpClient
    ):
        created_integration = self._create_stripe_integration()
        mock_oauth_response.return_value = created_integration
        mock_instance = MagicMock()
        MockStripeIntegration.return_value = mock_instance

        client.force_login(self.user)
        response = client.post(
            f"/api/environments/{self.team.pk}/integrations",
            {"kind": "stripe", "config": {"code": "oauth_code_123"}},
            content_type="application/json",
        )

        assert response.status_code == status.HTTP_201_CREATED
        MockStripeIntegration.assert_called_once_with(created_integration)
        mock_instance.write_posthog_secrets.assert_called_once_with(self.team.pk, self.user)

    @patch("posthog.api.integration.StripeIntegration")
    @patch("posthog.api.integration.OauthIntegration.integration_from_oauth_response")
    def test_create_succeeds_when_write_secrets_fails(
        self, mock_oauth_response, MockStripeIntegration, stripe_settings, client: HttpClient
    ):
        created_integration = self._create_stripe_integration()
        mock_oauth_response.return_value = created_integration
        mock_instance = MagicMock()
        mock_instance.write_posthog_secrets.side_effect = Exception("Stripe API error")
        MockStripeIntegration.return_value = mock_instance

        client.force_login(self.user)
        response = client.post(
            f"/api/environments/{self.team.pk}/integrations",
            {"kind": "stripe", "config": {"code": "oauth_code_123"}},
            content_type="application/json",
        )

        assert response.status_code == status.HTTP_201_CREATED

    @patch("posthog.api.integration.StripeIntegration")
    @patch("posthog.api.integration.OauthIntegration.integration_from_oauth_response")
    def test_posthog_initiated_oauth_with_state_still_works(
        self, mock_oauth_response, MockStripeIntegration, stripe_settings, client: HttpClient
    ):
        created_integration = self._create_stripe_integration()
        mock_oauth_response.return_value = created_integration
        mock_instance = MagicMock()
        MockStripeIntegration.return_value = mock_instance

        client.force_login(self.user)
        response = client.post(
            f"/api/environments/{self.team.pk}/integrations",
            {"kind": "stripe", "config": {"state": "next=/foo&token=abc123", "code": "oauth_code_123"}},
            content_type="application/json",
        )

        assert response.status_code == status.HTTP_201_CREATED
        mock_instance.write_posthog_secrets.assert_called_once_with(self.team.pk, self.user)

    @patch("posthog.api.integration.StripeIntegration")
    @patch("posthog.api.integration.OauthIntegration.integration_from_oauth_response")
    def test_posthog_initiated_oauth_ignores_marketplace_conflict_guard(
        self, mock_oauth_response, MockStripeIntegration, stripe_settings, client: HttpClient
    ):
        self._create_stripe_integration()
        new_integration = Integration(
            team=self.team,
            kind="stripe",
            integration_id="acct_999",
            config={},
            sensitive_config={},
        )
        mock_oauth_response.return_value = new_integration
        mock_instance = MagicMock()
        MockStripeIntegration.return_value = mock_instance

        client.force_login(self.user)
        response = client.post(
            f"/api/environments/{self.team.pk}/integrations",
            {
                "kind": "stripe",
                "config": {"state": "next=/foo&token=abc123", "code": "oauth_code_999"},
            },
            content_type="application/json",
        )

        assert response.status_code == status.HTTP_201_CREATED
        mock_oauth_response.assert_called_once()

    # The Stripe Apps OAuth flow (used by stripe_api_access_type: oauth) doesn't sign the
    # callback redirect — only the install-link OAuth mechanism emits install_signature.
    # The conflict guard is the defense-in-depth here, not signature verification.
    @pytest.mark.parametrize("include_install_signature", [True, False])
    @patch("posthog.api.integration.StripeIntegration")
    @patch("posthog.api.integration.OauthIntegration.integration_from_oauth_response")
    def test_marketplace_callback_without_state_succeeds(
        self,
        mock_oauth_response,
        MockStripeIntegration,
        include_install_signature,
        stripe_settings,
        client: HttpClient,
    ):
        created_integration = self._create_stripe_integration()
        mock_oauth_response.return_value = created_integration
        mock_instance = MagicMock()
        MockStripeIntegration.return_value = mock_instance

        config: dict = {
            "code": "oauth_code_123",
            "stripe_user_id": "acct_123",
            "account_id": "acct_123",
            "user_id": "usr_abc",
        }
        if include_install_signature:
            config["install_signature"] = self._make_install_signature(
                state="", user_id="usr_abc", account_id="acct_123"
            )

        client.force_login(self.user)
        response = client.post(
            f"/api/environments/{self.team.pk}/integrations",
            {"kind": "stripe", "config": config},
            content_type="application/json",
        )

        assert response.status_code == status.HTTP_201_CREATED
        mock_instance.write_posthog_secrets.assert_called_once_with(self.team.pk, self.user)

    @patch("posthog.api.integration.StripeIntegration")
    @patch("posthog.api.integration.OauthIntegration.integration_from_oauth_response")
    def test_marketplace_callback_rejects_forged_install_signature_when_present(
        self, mock_oauth_response, MockStripeIntegration, stripe_settings, client: HttpClient
    ):
        forged = self._make_install_signature(state="", user_id="usr_abc", account_id="acct_123", secret="wrong_secret")
        client.force_login(self.user)
        response = client.post(
            f"/api/environments/{self.team.pk}/integrations",
            {
                "kind": "stripe",
                "config": {
                    "code": "oauth_code_123",
                    "stripe_user_id": "acct_123",
                    "account_id": "acct_123",
                    "user_id": "usr_abc",
                    "install_signature": forged,
                },
            },
            content_type="application/json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "stripe_install_signature_invalid" in response.content.decode()
        mock_oauth_response.assert_not_called()
        MockStripeIntegration.assert_not_called()

    @patch("posthog.api.integration.StripeIntegration")
    @patch("posthog.api.integration.OauthIntegration.integration_from_oauth_response")
    def test_marketplace_callback_rejects_when_different_stripe_account_connected(
        self, mock_oauth_response, MockStripeIntegration, stripe_settings, client: HttpClient
    ):
        self._create_stripe_integration()

        sig = self._make_install_signature(state="", user_id="usr_xyz", account_id="acct_999")
        client.force_login(self.user)
        response = client.post(
            f"/api/environments/{self.team.pk}/integrations",
            {
                "kind": "stripe",
                "config": {
                    "code": "oauth_code_999",
                    "stripe_user_id": "acct_999",
                    "account_id": "acct_999",
                    "user_id": "usr_xyz",
                    "install_signature": sig,
                },
            },
            content_type="application/json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "stripe_integration_conflict" in response.content.decode()
        mock_oauth_response.assert_not_called()
        MockStripeIntegration.assert_not_called()

    @patch("posthog.api.integration.StripeIntegration")
    @patch("posthog.api.integration.OauthIntegration.integration_from_oauth_response")
    def test_marketplace_callback_allows_reinstall_of_same_stripe_account(
        self, mock_oauth_response, MockStripeIntegration, stripe_settings, client: HttpClient
    ):
        existing = self._create_stripe_integration()
        mock_oauth_response.return_value = existing
        mock_instance = MagicMock()
        MockStripeIntegration.return_value = mock_instance

        sig = self._make_install_signature(state="", user_id="usr_abc", account_id="acct_123")
        client.force_login(self.user)
        response = client.post(
            f"/api/environments/{self.team.pk}/integrations",
            {
                "kind": "stripe",
                "config": {
                    "code": "oauth_code_123",
                    "stripe_user_id": "acct_123",
                    "account_id": "acct_123",
                    "user_id": "usr_abc",
                    "install_signature": sig,
                },
            },
            content_type="application/json",
        )

        assert response.status_code == status.HTTP_201_CREATED
        mock_oauth_response.assert_called_once()

    @patch("posthog.api.integration.OauthIntegration.integration_from_oauth_response")
    def test_stripe_oauth_exchange_failure_returns_error(
        self, mock_oauth_response, stripe_settings, client: HttpClient
    ):
        mock_oauth_response.side_effect = Exception("Stripe returned invalid_grant")

        sig = self._make_install_signature(state="", user_id="usr_abc", account_id="acct_123")
        client.force_login(self.user)
        response = client.post(
            f"/api/environments/{self.team.pk}/integrations",
            {
                "kind": "stripe",
                "config": {
                    "code": "ac_invalid",
                    "stripe_user_id": "acct_123",
                    "account_id": "acct_123",
                    "user_id": "usr_abc",
                    "install_signature": sig,
                },
            },
            content_type="application/json",
        )

        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        assert not Integration.objects.filter(team_id=self.team.pk, kind="stripe").exists()


class TestStripeIntegrationOAuthTokens:
    @pytest.fixture(autouse=True)
    def _override_oidc_key(self, settings):
        settings.OAUTH2_PROVIDER = {
            **django_settings.OAUTH2_PROVIDER,
            "OIDC_RSA_PRIVATE_KEY": generate_rsa_key(),
        }

    @pytest.fixture(autouse=True)
    def setup(self, db):
        self.organization = Organization.objects.create(name="Test Org")
        self.team = Team.objects.create(organization=self.organization, name="Test Team")
        self.user = User.objects.create_and_join(self.organization, "test@posthog.com", "test")
        self.oauth_app = OAuthApplication.objects.create(
            name="PostHog for Stripe",
            client_id="stripe_oauth_client_id",
            client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://example.com/callback",
            algorithm="RS256",
        )

    def _create_integration_with_tokens(self) -> tuple[Integration, OAuthAccessToken, OAuthRefreshToken]:
        integration = Integration.objects.create(
            team=self.team,
            kind="stripe",
            config={"account_name": "Test (acct_123)"},
            sensitive_config={"access_token": "sk_live_test"},
            integration_id="acct_123",
            created_by=self.user,
        )
        access_token = OAuthAccessToken.objects.create(
            application=self.oauth_app,
            token="ph_access_token_test",
            user=self.user,
            expires=timezone.now() + timedelta(days=365),
            scope=StripeIntegration.SCOPES,
            scoped_teams=[self.team.pk],
        )
        refresh_token = OAuthRefreshToken.objects.create(
            application=self.oauth_app,
            token="ph_refresh_token_test",
            user=self.user,
            access_token=access_token,
            scoped_teams=[self.team.pk],
        )
        return integration, access_token, refresh_token

    @patch("posthog.models.integration.settings")
    def test_destroy_oauth_tokens_deletes_tokens(self, mock_settings):
        mock_settings.STRIPE_POSTHOG_OAUTH_CLIENT_ID = self.oauth_app.client_id
        integration, access_token, refresh_token = self._create_integration_with_tokens()
        stripe_int = StripeIntegration(integration)

        stripe_int._destroy_posthog_oauth_tokens()

        assert not OAuthAccessToken.objects.filter(pk=access_token.pk).exists()
        assert not OAuthRefreshToken.objects.filter(pk=refresh_token.pk).exists()

    @patch("posthog.models.integration.settings")
    def test_destroy_oauth_tokens_only_affects_same_team(self, mock_settings):
        mock_settings.STRIPE_POSTHOG_OAUTH_CLIENT_ID = self.oauth_app.client_id
        integration, _, _ = self._create_integration_with_tokens()

        other_team = Team.objects.create(organization=self.organization, name="Other Team")
        other_access_token = OAuthAccessToken.objects.create(
            application=self.oauth_app,
            token="ph_access_other",
            user=self.user,
            expires=timezone.now() + timedelta(days=365),
            scope=StripeIntegration.SCOPES,
            scoped_teams=[other_team.pk],
        )
        other_refresh_token = OAuthRefreshToken.objects.create(
            application=self.oauth_app,
            token="ph_refresh_other",
            user=self.user,
            access_token=other_access_token,
            scoped_teams=[other_team.pk],
        )

        stripe_int = StripeIntegration(integration)
        stripe_int._destroy_posthog_oauth_tokens()

        assert OAuthAccessToken.objects.filter(pk=other_access_token.pk).exists()
        assert OAuthRefreshToken.objects.filter(pk=other_refresh_token.pk).exists()

    @patch("posthog.models.integration.settings")
    def test_destroy_oauth_tokens_noop_when_no_oauth_app(self, mock_settings):
        mock_settings.STRIPE_POSTHOG_OAUTH_CLIENT_ID = None
        integration, access_token, refresh_token = self._create_integration_with_tokens()
        stripe_int = StripeIntegration(integration)

        stripe_int._destroy_posthog_oauth_tokens()

        assert OAuthAccessToken.objects.filter(pk=access_token.pk).exists()
        assert OAuthRefreshToken.objects.filter(pk=refresh_token.pk).exists()

    @patch("posthog.models.integration.StripeClient")
    @patch("posthog.models.integration.settings")
    def test_write_posthog_secrets_uses_account_scope(self, mock_settings, MockStripeClient):
        mock_settings.STRIPE_POSTHOG_OAUTH_CLIENT_ID = self.oauth_app.client_id
        mock_settings.STRIPE_APP_SECRET_KEY = "sk_test"
        mock_client = MagicMock()
        MockStripeClient.return_value = mock_client

        integration = Integration.objects.create(
            team=self.team,
            kind="stripe",
            config={},
            sensitive_config={},
            integration_id="acct_456",
            created_by=self.user,
        )
        stripe_int = StripeIntegration(integration)
        stripe_int.write_posthog_secrets(self.team.pk, self.user)

        calls = mock_client.apps.secrets.create.call_args_list
        assert len(calls) == 5
        for call in calls:
            assert call.kwargs["params"]["scope"] == {"type": "account"}
            assert call.kwargs["options"] == {"stripe_account": "acct_456"}

        secret_payloads = {call.kwargs["params"]["name"]: call.kwargs["params"]["payload"] for call in calls}
        assert secret_payloads["posthog_project_id"] == str(self.team.pk)
        assert secret_payloads["posthog_oauth_client_id"] == self.oauth_app.client_id

    @patch("posthog.models.integration.StripeClient")
    @patch("posthog.models.integration.settings")
    def test_clear_posthog_secrets_uses_account_scope(self, mock_settings, MockStripeClient):
        mock_settings.STRIPE_APP_SECRET_KEY = "sk_test"
        mock_settings.STRIPE_POSTHOG_OAUTH_CLIENT_ID = None
        mock_client = MagicMock()
        MockStripeClient.return_value = mock_client

        integration = Integration.objects.create(
            team=self.team,
            kind="stripe",
            config={},
            sensitive_config={},
            integration_id="acct_789",
            created_by=self.user,
        )
        stripe_int = StripeIntegration(integration)
        stripe_int.clear_posthog_secrets()

        calls = mock_client.apps.secrets.delete_where.call_args_list
        assert len(calls) == 5
        for call in calls:
            assert call.kwargs["params"]["scope"] == {"type": "account"}
            assert call.kwargs["options"] == {"stripe_account": "acct_789"}


def _make_github_branches_response(names: list[str], has_next: bool = False) -> MagicMock:
    """Build a mock requests.Response for the GitHub branches API."""
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = [{"name": n} for n in names]
    link = '<https://api.github.com/next>; rel="next"' if has_next else ""
    response.headers = {"Link": link}
    return response


class TestGitHubBranches:
    @pytest.fixture(autouse=True)
    def setup_integration(self, db):
        self.organization = Organization.objects.create(name="Test Org")
        self.team = Team.objects.create(organization=self.organization, name="Test Team")
        self.user = User.objects.create_and_join(
            self.organization, "test@posthog.com", "test", level=OrganizationMembership.Level.ADMIN
        )
        self.integration = Integration.objects.create(
            team=self.team,
            kind="github",
            config={"installation_id": "12345", "refreshed_at": 0, "expires_in": 999999},
            sensitive_config={"access_token": "test-token"},
        )
        self.github = GitHubIntegration(self.integration)

    @patch("posthog.models.integration.requests.get")
    def test_list_branches_returns_first_page(self, mock_get):
        names = [f"branch-{i}" for i in range(100)]
        mock_get.return_value = _make_github_branches_response(names, has_next=True)

        branches, has_more = self.github.list_branches("org/repo", limit=100, offset=0)

        assert branches == names
        assert has_more is True
        mock_get.assert_called_once()
        assert "page=1" in mock_get.call_args[0][0]

    @patch("posthog.models.integration.requests.get")
    def test_list_branches_offset_skips_pages(self, mock_get):
        """Requesting offset=200 should start fetching from GitHub page 3."""
        page3_names = [f"branch-{i}" for i in range(200, 300)]
        mock_get.return_value = _make_github_branches_response(page3_names, has_next=True)

        branches, has_more = self.github.list_branches("org/repo", limit=100, offset=200)

        assert branches == page3_names
        assert has_more is True
        assert mock_get.call_count == 1
        assert "page=3" in mock_get.call_args[0][0]

    @patch("posthog.models.integration.requests.get")
    def test_list_branches_last_page_no_more(self, mock_get):
        names = [f"branch-{i}" for i in range(50)]
        mock_get.return_value = _make_github_branches_response(names, has_next=False)

        branches, has_more = self.github.list_branches("org/repo", limit=100, offset=0)

        assert branches == names
        assert has_more is False

    @patch("posthog.models.integration.requests.get")
    def test_list_branches_spans_two_github_pages(self, mock_get):
        """An offset that doesn't align with per_page=100 requires fetching two GitHub pages."""
        page1_names = [f"branch-{i}" for i in range(100)]
        page2_names = [f"branch-{i}" for i in range(100, 200)]

        mock_get.side_effect = [
            _make_github_branches_response(page1_names, has_next=True),
            _make_github_branches_response(page2_names, has_next=False),
        ]

        branches, has_more = self.github.list_branches("org/repo", limit=100, offset=50)

        assert len(branches) == 100
        assert branches == [f"branch-{i}" for i in range(50, 150)]
        # There are still branches 150-199 beyond this window
        assert has_more is True
        assert mock_get.call_count == 2

    @patch("posthog.models.integration.requests.get")
    def test_list_branches_empty_repo(self, mock_get):
        mock_get.return_value = _make_github_branches_response([], has_next=False)

        branches, has_more = self.github.list_branches("org/repo")

        assert branches == []
        assert has_more is False

    @patch("posthog.models.integration.requests.get")
    def test_list_branches_401_triggers_refresh_and_retry(self, mock_get):
        unauthorized = MagicMock()
        unauthorized.status_code = 401

        names = ["main", "develop"]
        success = _make_github_branches_response(names, has_next=False)

        mock_get.side_effect = [unauthorized, success]

        with patch.object(self.github, "refresh_access_token"):
            branches, has_more = self.github.list_branches("org/repo")

        assert branches == names
        assert mock_get.call_count == 2

    @patch("posthog.models.integration.GitHubIntegration.list_cached_branches")
    def test_api_endpoint_passes_search_limit_offset(self, mock_list_cached, client: HttpClient):
        mock_list_cached.return_value = ([f"branch-{i}" for i in range(10)], "main", True)
        client.force_login(self.user)

        response = client.get(
            f"/api/environments/{self.team.pk}/integrations/{self.integration.pk}/github_branches/",
            {"repo": "org/repo", "search": "feature", "limit": "10", "offset": "50"},
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data["branches"]) == 10
        assert data["has_more"] is True
        assert data["default_branch"] == "main"
        mock_list_cached.assert_called_once_with(
            "org/repo",
            search="feature",
            limit=10,
            offset=50,
        )

    @patch("posthog.models.integration.GitHubIntegration.list_cached_branches")
    def test_api_endpoint_default_branch_first_on_page_one(self, mock_list_cached, client: HttpClient):
        mock_list_cached.return_value = (["main", "alpha", "zebra"], "main", False)
        client.force_login(self.user)

        response = client.get(
            f"/api/environments/{self.team.pk}/integrations/{self.integration.pk}/github_branches/",
            {"repo": "org/repo"},
        )

        data = response.json()
        assert data["branches"][0] == "main"
        assert data["default_branch"] == "main"

    @patch("posthog.models.integration.GitHubIntegration.list_cached_branches")
    def test_api_endpoint_pages_cached_branches_without_reinserting_default(self, mock_list_cached, client: HttpClient):
        mock_list_cached.return_value = (["other"], "main", False)
        client.force_login(self.user)

        response = client.get(
            f"/api/environments/{self.team.pk}/integrations/{self.integration.pk}/github_branches/",
            {"repo": "org/repo", "offset": "100"},
        )

        data = response.json()
        assert data["branches"] == ["other"]

    @patch("posthog.models.integration.GitHubIntegration.list_cached_branches")
    def test_api_endpoint_prepends_default_branch_even_when_not_in_list(self, mock_list_cached, client: HttpClient):
        mock_list_cached.return_value = (["main", "alpha", "beta"], "main", False)
        client.force_login(self.user)

        response = client.get(
            f"/api/environments/{self.team.pk}/integrations/{self.integration.pk}/github_branches/",
            {"repo": "org/repo"},
        )

        data = response.json()
        assert data["branches"] == ["main", "alpha", "beta"]

    @patch("posthog.models.integration.GitHubIntegration.get_default_branch", return_value="main")
    @patch("posthog.models.integration.GitHubIntegration.list_branches")
    def test_api_endpoint_validates_limit_max(self, mock_list, mock_default, client: HttpClient):
        mock_list.return_value = ([], False)
        client.force_login(self.user)

        response = client.get(
            f"/api/environments/{self.team.pk}/integrations/{self.integration.pk}/github_branches/",
            {"repo": "org/repo", "limit": "1001"},
        )

        assert response.status_code == 400

    @patch("posthog.models.integration.requests.get")
    def test_get_default_branch_is_cached(self, mock_get):
        from django.core.cache import cache

        cache.clear()

        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {"default_branch": "develop"}
        mock_get.return_value = response

        first = self.github.get_default_branch("org/repo-cache-test")
        second = self.github.get_default_branch("org/repo-cache-test")

        assert first == "develop"
        assert second == "develop"
        assert mock_get.call_count == 1
