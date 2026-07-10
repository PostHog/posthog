import hmac
import json
import time
import hashlib
from datetime import timedelta
from urllib.parse import quote, urlencode

import pytest
from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.test import override_settings
from django.test.client import Client as HttpClient
from django.utils import timezone

from parameterized import parameterized
from rest_framework import status
from rest_framework.exceptions import ValidationError

from posthog.api.github_callback.state import store_unified_authorize_state
from posthog.api.github_callback.team_services import (
    GITHUB_LINK_EXISTING_ERROR_PERSONAL_GITHUB_REQUIRED,
    authorize_link_existing_installation,
)
from posthog.api.github_callback.types import FlowKind, GitHubAuthorizeState
from posthog.api.integration import IntegrationSerializer, IntegrationViewSet
from posthog.models.integration import (
    ERROR_TOKEN_REFRESH_FAILED,
    GITHUB_REPOSITORY_REFRESH_COOLDOWN_SECONDS,
    PRIVATE_CHANNEL_WITHOUT_ACCESS,
    SLACK_INTEGRATION_KINDS,
    EmailIntegration,
    GitHubIntegration,
    GitHubIntegrationError,
    GitHubUserAuthorization,
    Integration,
    SlackIntegration,
    StripeIntegration,
)
from posthog.models.oauth import OAuthAccessToken, OAuthApplication, OAuthRefreshToken
from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.team import Team
from posthog.models.user import User
from posthog.models.user_integration import UserIntegration
from posthog.models.utils import hash_key_value
from posthog.rate_limit import GitHubRepositoryRefreshThrottle

from products.cdp.backend.models import HogFunction
from products.cdp.backend.models.hog_function_template import HogFunctionTemplate
from products.workflows.backend.models import HogFlow


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
            exclude_archived=True, types="public_channel", limit=1000, cursor=None
        )
        mock_client.users_conversations.assert_called_once_with(
            exclude_archived=True, types="private_channel", limit=1000, cursor=None, user="test_user_id"
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
            exclude_archived=True, types="public_channel", limit=1000, cursor=None
        )
        mock_client.users_conversations.assert_called_once_with(
            exclude_archived=True, types="private_channel", limit=1000, cursor=None, user="test_user_id"
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

    def test_granted_scopes_parses_comma_separated_string(self):
        self.integration.config["scope"] = "chat:write,users:read,users:read.email"
        slack = SlackIntegration(self.integration)
        assert slack.granted_scopes() == frozenset({"chat:write", "users:read", "users:read.email"})

    def test_granted_scopes_tolerates_whitespace_and_empty_entries(self):
        self.integration.config["scope"] = " chat:write , ,users:read"
        slack = SlackIntegration(self.integration)
        assert slack.granted_scopes() == frozenset({"chat:write", "users:read"})

    def test_granted_scopes_returns_empty_when_field_missing(self):
        self.integration.config.pop("scope", None)
        slack = SlackIntegration(self.integration)
        assert slack.granted_scopes() == frozenset()

    def test_granted_scopes_returns_empty_when_field_is_empty_string(self):
        self.integration.config["scope"] = ""
        slack = SlackIntegration(self.integration)
        assert slack.granted_scopes() == frozenset()

    def test_missing_scopes_returns_difference(self):
        self.integration.config["scope"] = "chat:write,users:read"
        slack = SlackIntegration(self.integration)
        required = {"chat:write", "users:read", "users:read.email", "reactions:write"}
        assert slack.missing_scopes(required) == frozenset({"users:read.email", "reactions:write"})

    def test_missing_scopes_returns_empty_when_all_granted(self):
        required = {"chat:write", "users:read"}
        self.integration.config["scope"] = "chat:write,users:read,extra:scope"
        slack = SlackIntegration(self.integration)
        assert slack.missing_scopes(required) == frozenset()


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
            "posthog.com",
            mail_from_subdomain="youmustnothavelikedmyemail",
            team_id=self.team.id,
            org_team_ids=[self.team.id],
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

    @patch("posthog.models.integration.is_url_allowed", return_value=(True, None))
    def test_integration_from_config_with_valid_config(
        self,
        mock_is_url_allowed,
        client: HttpClient,
    ):
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
    def test_integration_from_config_with_invalid_config(
        self,
        invalid_config,
        expected_error_message,
        client: HttpClient,
    ):
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

    @pytest.mark.parametrize(
        "host",
        [
            "169.254.169.254",
            "127.0.0.1",
            "10.0.0.1",
            "192.168.1.1",
        ],
    )
    # FORCE_URL_VALIDATION exercises the real SSRF guard; otherwise is_url_allowed short-circuits
    # in dev/DEBUG, which is on under tests.
    @override_settings(FORCE_URL_VALIDATION=True)
    def test_integration_from_config_rejects_internal_host(
        self,
        host,
        client: HttpClient,
    ):
        """Member-supplied Databricks hosts that resolve to internal IPs must be rejected (SSRF guard)."""
        client.force_login(self.user)

        response = client.post(
            f"/api/environments/{self.team.pk}/integrations",
            {
                "kind": "databricks",
                "config": {
                    "server_hostname": host,
                    "client_id": "client_id",
                    "client_secret": "client_secret",
                },
            },
            content_type="application/json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert host in response.json()["detail"]
        assert not Integration.objects.filter(team=self.team, kind="databricks").exists()


class TestAwsS3Integration:
    @pytest.fixture(autouse=True)
    def setup_integration(self, db):
        self.organization = Organization.objects.create(name="Test Org")
        self.team = Team.objects.create(organization=self.organization, name="Test Team")
        self.user = User.objects.create_and_join(
            self.organization, "test@posthog.com", "test", level=OrganizationMembership.Level.ADMIN
        )

    @patch("posthog.models.integration.AwsS3Integration.validate_credentials", return_value="123456789012")
    def test_create_with_valid_config(self, mock_validate, client: HttpClient):
        client.force_login(self.user)

        response = client.post(
            f"/api/environments/{self.team.pk}/integrations",
            {
                "kind": "aws-s3",
                "config": {
                    "name": "prod-aws",
                    "aws_access_key_id": "AKIAEXAMPLE",
                    "aws_secret_access_key": "secret",
                },
            },
            content_type="application/json",
        )

        assert response.status_code == status.HTTP_201_CREATED, response.json()
        assert response.json()["kind"] == "aws-s3"

        integration = Integration.objects.get(id=response.json()["id"])
        assert integration.kind == "aws-s3"
        assert integration.team == self.team
        assert integration.integration_id == "prod-aws"
        assert integration.config == {"name": "prod-aws", "aws_account_id": "123456789012"}
        assert integration.sensitive_config == {
            "aws_access_key_id": "AKIAEXAMPLE",
            "aws_secret_access_key": "secret",
        }
        # Credentials must never surface anywhere in the API response (sensitive_config is not a
        # serializer field; this guards against a leak into config or any other exposed field).
        response_body = json.dumps(response.json())
        assert "aws_access_key_id" not in response_body
        assert "aws_secret_access_key" not in response_body
        assert "AKIAEXAMPLE" not in response_body

    @patch("posthog.models.integration.AwsS3Integration.validate_credentials")
    def test_create_rejects_invalid_credentials(self, mock_validate, client: HttpClient):
        from posthog.models.integration import S3CredentialIntegrationError

        mock_validate.side_effect = S3CredentialIntegrationError("AWS credentials are not valid: nope")
        client.force_login(self.user)

        response = client.post(
            f"/api/environments/{self.team.pk}/integrations",
            {
                "kind": "aws-s3",
                "config": {
                    "name": "prod-aws",
                    "aws_access_key_id": "AKIAEXAMPLE",
                    "aws_secret_access_key": "wrong",
                },
            },
            content_type="application/json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "AWS credentials are not valid" in response.json()["detail"]

    @patch("posthog.models.integration.AwsS3Integration.validate_credentials", return_value="123456789012")
    def test_create_rejects_duplicate_name(self, mock_validate, client: HttpClient):
        client.force_login(self.user)
        payload = {
            "kind": "aws-s3",
            "config": {"name": "prod-aws", "aws_access_key_id": "AKIAEXAMPLE", "aws_secret_access_key": "secret"},
        }

        first = client.post(f"/api/environments/{self.team.pk}/integrations", payload, content_type="application/json")
        assert first.status_code == status.HTTP_201_CREATED, first.json()

        second = client.post(f"/api/environments/{self.team.pk}/integrations", payload, content_type="application/json")
        assert second.status_code == status.HTTP_400_BAD_REQUEST
        assert "An integration named 'prod-aws' already exists" in second.json()["detail"]
        assert Integration.objects.filter(team=self.team, integration_id="prod-aws").count() == 1

    @pytest.mark.parametrize(
        "invalid_config,expected_error_message",
        [
            (
                {"aws_access_key_id": "k", "aws_secret_access_key": "s"},
                "Name, access key ID, and secret access key must be provided",
            ),
            (
                {"name": "n", "aws_secret_access_key": "s"},
                "Name, access key ID, and secret access key must be provided",
            ),
            ({"name": "n", "aws_access_key_id": "k"}, "Name, access key ID, and secret access key must be provided"),
            ({}, "Name, access key ID, and secret access key must be provided"),
            (
                {"name": "n", "aws_access_key_id": "k", "aws_secret_access_key": 1},
                "Name, access key ID, and secret access key must be strings",
            ),
        ],
    )
    def test_create_with_invalid_config(self, invalid_config, expected_error_message, client: HttpClient):
        client.force_login(self.user)

        response = client.post(
            f"/api/environments/{self.team.pk}/integrations",
            {"kind": "aws-s3", "config": invalid_config},
            content_type="application/json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["detail"] == expected_error_message


class TestS3CompatibleIntegration:
    @pytest.fixture(autouse=True)
    def setup_integration(self, db):
        self.organization = Organization.objects.create(name="Test Org")
        self.team = Team.objects.create(organization=self.organization, name="Test Team")
        self.user = User.objects.create_and_join(
            self.organization, "test@posthog.com", "test", level=OrganizationMembership.Level.ADMIN
        )

    def test_create_with_valid_config(self, client: HttpClient):
        client.force_login(self.user)

        response = client.post(
            f"/api/environments/{self.team.pk}/integrations",
            {
                "kind": "s3-compatible",
                "config": {
                    "name": "my-r2",
                    "endpoint_url": "https://account.r2.cloudflarestorage.com",
                    "aws_access_key_id": "key",
                    "aws_secret_access_key": "secret",
                },
            },
            content_type="application/json",
        )

        assert response.status_code == status.HTTP_201_CREATED, response.json()
        assert response.json()["kind"] == "s3-compatible"

        integration = Integration.objects.get(id=response.json()["id"])
        assert integration.integration_id == "my-r2"
        assert integration.config == {"name": "my-r2", "endpoint_url": "https://account.r2.cloudflarestorage.com"}
        assert integration.sensitive_config == {"aws_access_key_id": "key", "aws_secret_access_key": "secret"}
        # Credentials must never surface anywhere in the API response (sensitive_config is not a
        # serializer field; this guards against a leak into config or any other exposed field).
        response_body = json.dumps(response.json())
        assert "aws_access_key_id" not in response_body
        assert "aws_secret_access_key" not in response_body

    def test_create_rejects_duplicate_name(self, client: HttpClient):
        client.force_login(self.user)
        payload = {
            "kind": "s3-compatible",
            "config": {
                "name": "my-r2",
                "endpoint_url": "https://account.r2.cloudflarestorage.com",
                "aws_access_key_id": "key",
                "aws_secret_access_key": "secret",
            },
        }

        first = client.post(f"/api/environments/{self.team.pk}/integrations", payload, content_type="application/json")
        assert first.status_code == status.HTTP_201_CREATED, first.json()

        second = client.post(f"/api/environments/{self.team.pk}/integrations", payload, content_type="application/json")
        assert second.status_code == status.HTTP_400_BAD_REQUEST
        assert "An integration named 'my-r2' already exists" in second.json()["detail"]
        assert Integration.objects.filter(team=self.team, integration_id="my-r2").count() == 1

    # is_url_allowed bypasses validation in DEBUG/test mode, so force the production path to exercise rejection.
    @override_settings(FORCE_URL_VALIDATION=True)
    def test_create_rejects_invalid_endpoint_url(self, client: HttpClient):
        client.force_login(self.user)

        response = client.post(
            f"/api/environments/{self.team.pk}/integrations",
            {
                "kind": "s3-compatible",
                "config": {
                    "name": "bad",
                    "endpoint_url": "https://169.254.169.254",
                    "aws_access_key_id": "key",
                    "aws_secret_access_key": "secret",
                },
            },
            content_type="application/json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "Invalid endpoint URL" in response.json()["detail"]

    @pytest.mark.parametrize(
        "invalid_config,expected_error_message",
        [
            (
                {"endpoint_url": "https://e.com", "aws_access_key_id": "k", "aws_secret_access_key": "s"},
                "Name, endpoint URL, access key ID, and secret access key must be provided",
            ),
            (
                {"name": "n", "aws_access_key_id": "k", "aws_secret_access_key": "s"},
                "Name, endpoint URL, access key ID, and secret access key must be provided",
            ),
            ({}, "Name, endpoint URL, access key ID, and secret access key must be provided"),
        ],
    )
    def test_create_with_invalid_config(self, invalid_config, expected_error_message, client: HttpClient):
        client.force_login(self.user)

        response = client.post(
            f"/api/environments/{self.team.pk}/integrations",
            {"kind": "s3-compatible", "config": invalid_config},
            content_type="application/json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["detail"] == expected_error_message


class TestSnowflakeIntegration:
    @pytest.fixture(autouse=True)
    def setup_integration(self, db):
        self.organization = Organization.objects.create(name="Test Org")
        self.team = Team.objects.create(organization=self.organization, name="Test Team")
        self.user = User.objects.create_and_join(
            self.organization, "test@posthog.com", "test", level=OrganizationMembership.Level.ADMIN
        )

    def test_create_with_password_auth(self, client: HttpClient):
        client.force_login(self.user)

        response = client.post(
            f"/api/environments/{self.team.pk}/integrations",
            {
                "kind": "snowflake",
                "config": {
                    "name": "prod-snowflake",
                    "account": "myorg-myaccount",
                    "user": "posthog_svc",
                    "authentication_type": "password",
                    "password": "secret",
                },
            },
            content_type="application/json",
        )

        assert response.status_code == status.HTTP_201_CREATED, response.json()
        assert response.json()["kind"] == "snowflake"

        integration = Integration.objects.get(id=response.json()["id"])
        assert integration.integration_id == "prod-snowflake"
        assert integration.config == {
            "name": "prod-snowflake",
            "account": "myorg-myaccount",
            "user": "posthog_svc",
            "authentication_type": "password",
        }
        assert integration.sensitive_config == {"password": "secret"}
        # The credential value must never surface anywhere in the API response (sensitive_config is
        # not a serializer field; this guards against a leak into config or any other exposed field).
        # Note the word "password" legitimately appears as the non-secret authentication_type.
        response_body = json.dumps(response.json())
        assert "secret" not in response_body

    def test_create_with_keypair_auth(self, client: HttpClient):
        client.force_login(self.user)

        response = client.post(
            f"/api/environments/{self.team.pk}/integrations",
            {
                "kind": "snowflake",
                "config": {
                    "name": "prod-snowflake",
                    "account": "myorg-myaccount",
                    "user": "posthog_svc",
                    "authentication_type": "keypair",
                    "private_key": "-----BEGIN PRIVATE KEY-----\nxxx\n-----END PRIVATE KEY-----",
                    "private_key_passphrase": "phrase",
                },
            },
            content_type="application/json",
        )

        assert response.status_code == status.HTTP_201_CREATED, response.json()

        integration = Integration.objects.get(id=response.json()["id"])
        assert integration.config["authentication_type"] == "keypair"
        assert integration.sensitive_config == {
            "private_key": "-----BEGIN PRIVATE KEY-----\nxxx\n-----END PRIVATE KEY-----",
            "private_key_passphrase": "phrase",
        }
        response_body = json.dumps(response.json())
        assert "private_key" not in response_body
        assert "PRIVATE KEY" not in response_body
        assert "phrase" not in response_body

    def test_create_rejects_duplicate_name(self, client: HttpClient):
        client.force_login(self.user)
        payload = {
            "kind": "snowflake",
            "config": {
                "name": "prod-snowflake",
                "account": "myorg-myaccount",
                "user": "posthog_svc",
                "authentication_type": "password",
                "password": "secret",
            },
        }

        first = client.post(f"/api/environments/{self.team.pk}/integrations", payload, content_type="application/json")
        assert first.status_code == status.HTTP_201_CREATED, first.json()

        second = client.post(f"/api/environments/{self.team.pk}/integrations", payload, content_type="application/json")
        assert second.status_code == status.HTTP_400_BAD_REQUEST
        assert "An integration named 'prod-snowflake' already exists" in second.json()["detail"]
        assert Integration.objects.filter(team=self.team, integration_id="prod-snowflake").count() == 1

    def test_create_rejects_malformed_account(self, client: HttpClient):
        client.force_login(self.user)

        response = client.post(
            f"/api/environments/{self.team.pk}/integrations",
            {
                "kind": "snowflake",
                "config": {
                    "name": "bad",
                    "account": "https://myaccount.snowflakecomputing.com",
                    "user": "posthog_svc",
                    "authentication_type": "password",
                    "password": "secret",
                },
            },
            content_type="application/json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "invalid account identifier" in response.json()["detail"]

    @pytest.mark.parametrize(
        "invalid_config,expected_error_message",
        [
            (
                {"account": "a", "user": "u", "password": "p"},
                "Name, account, and user must be provided",
            ),
            (
                {"name": "n", "user": "u", "password": "p"},
                "Name, account, and user must be provided",
            ),
            ({}, "Name, account, and user must be provided"),
            (
                {"name": "n", "account": "a", "user": "u", "authentication_type": "password"},
                "Password is required",
            ),
            (
                {"name": "n", "account": "a", "user": "u", "authentication_type": "keypair"},
                "Private key is required",
            ),
            (
                {"name": "n", "account": "a", "user": "u", "authentication_type": "password", "password": 42},
                "Password, private key, and private key passphrase must be strings",
            ),
        ],
    )
    def test_create_with_invalid_config(self, invalid_config, expected_error_message, client: HttpClient):
        client.force_login(self.user)

        response = client.post(
            f"/api/environments/{self.team.pk}/integrations",
            {"kind": "snowflake", "config": invalid_config},
            content_type="application/json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert expected_error_message in response.json()["detail"]


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
        results = response.json()["results"]
        kinds = {integration["kind"] for integration in results}
        assert kinds == {"github", "twilio"}
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

    def test_retrieve_non_github_integration_with_api_key_succeeds(self, client: HttpClient):
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

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["kind"] == "twilio"

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

    @pytest.mark.parametrize(
        "url_suffix,method,expected_provider",
        [
            ("github_repos/", "get", "GitHub"),
            ("github_repos/refresh/", "post", "GitHub"),
            ("github_branches/?repo=org/repo", "get", "GitHub"),
            ("jira_projects/", "get", "Jira"),
            ("linear_teams/", "get", "Linear"),
        ],
    )
    def test_provider_lookup_actions_on_wrong_integration_return_400(
        self, url_suffix, method, expected_provider, client: HttpClient
    ):
        key_value = "test_key_non_github"
        PersonalAPIKey.objects.create(
            label="Test Key",
            user=self.user,
            secure_value=hash_key_value(key_value),
            scopes=["integration:read", "integration:write"],
        )

        response = getattr(client, method)(
            f"/api/environments/{self.team.pk}/integrations/{self.twilio_integration.id}/{url_suffix}",
            HTTP_AUTHORIZATION=f"Bearer {key_value}",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert expected_provider in response.json()["detail"]

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

    @pytest.mark.parametrize(
        "query_string,mock_return,expected_call",
        [
            (
                "",
                (
                    [
                        {"id": 1, "slug": "frontend-team", "name": "Frontend Team"},
                        {"id": 2, "slug": "platform", "name": "Platform"},
                    ],
                    False,
                ),
                {"search": "", "limit": 100, "offset": 0},
            ),
            (
                "?search=front&limit=10&offset=20",
                (
                    [
                        {"id": 1, "slug": "frontend-team", "name": "Frontend Team"},
                    ],
                    True,
                ),
                {"search": "front", "limit": 10, "offset": 20},
            ),
        ],
    )
    @patch("posthog.models.integration.GitHubIntegration.list_teams")
    def test_github_teams(self, mock_list_teams, query_string, mock_return, expected_call, client: HttpClient):
        mock_list_teams.return_value = mock_return

        key_value = "test_key_123"
        PersonalAPIKey.objects.create(
            label="Test Key",
            user=self.user,
            secure_value=hash_key_value(key_value),
            scopes=["integration:read"],
        )

        response = client.get(
            f"/api/environments/{self.team.pk}/integrations/{self.github_integration.id}/github_teams/{query_string}",
            HTTP_AUTHORIZATION=f"Bearer {key_value}",
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["teams"] == mock_return[0]
        assert data["has_more"] is mock_return[1]
        mock_list_teams.assert_called_once_with(**expected_call)

    @patch("posthog.models.integration.GitHubIntegration.list_teams")
    def test_github_teams_errors_return_400(self, mock_list_teams, client: HttpClient):
        mock_list_teams.side_effect = GitHubIntegrationError("GitHubIntegration: list_teams failed")

        key_value = "test_key_123"
        PersonalAPIKey.objects.create(
            label="Test Key",
            user=self.user,
            secure_value=hash_key_value(key_value),
            scopes=["integration:read"],
        )

        response = client.get(
            f"/api/environments/{self.team.pk}/integrations/{self.github_integration.id}/github_teams/",
            HTTP_AUTHORIZATION=f"Bearer {key_value}",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert (
            response.json()["detail"]
            == "Unable to fetch GitHub teams. Please check integration settings and try again."
        )

    @patch("posthog.api.integration._ensure_oauth_token_valid")
    @patch("posthog.api.integration.JiraIntegration.list_projects")
    def test_jira_projects_with_scope_succeeds(self, mock_list_projects, mock_ensure_token_valid, client: HttpClient):
        mock_list_projects.return_value = [{"id": "10000", "key": "ENG", "name": "Engineering"}]
        jira_integration = Integration.objects.create(
            team=self.team,
            kind=Integration.IntegrationKind.JIRA.value,
            config={"cloud_id": "cloud-id"},
            sensitive_config={"access_token": "test-token"},
        )

        key_value = "test_key_123"
        PersonalAPIKey.objects.create(
            label="Test Key",
            user=self.user,
            secure_value=hash_key_value(key_value),
            scopes=["integration:read"],
        )

        response = client.get(
            f"/api/environments/{self.team.pk}/integrations/{jira_integration.id}/jira_projects/",
            HTTP_AUTHORIZATION=f"Bearer {key_value}",
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {"projects": [{"id": "10000", "key": "ENG", "name": "Engineering"}]}
        mock_ensure_token_valid.assert_called_once_with(jira_integration)
        mock_list_projects.assert_called_once_with()

    @patch("posthog.api.integration._ensure_oauth_token_valid")
    @patch("posthog.api.integration.LinearIntegration.list_teams")
    def test_linear_teams_with_scope_succeeds(self, mock_list_teams, mock_ensure_token_valid, client: HttpClient):
        mock_list_teams.return_value = [{"id": "team-id", "name": "Engineering"}]
        linear_integration = Integration.objects.create(
            team=self.team,
            kind=Integration.IntegrationKind.LINEAR.value,
            config={},
            sensitive_config={"access_token": "test-token"},
        )

        key_value = "test_key_123"
        PersonalAPIKey.objects.create(
            label="Test Key",
            user=self.user,
            secure_value=hash_key_value(key_value),
            scopes=["integration:read"],
        )

        response = client.get(
            f"/api/environments/{self.team.pk}/integrations/{linear_integration.id}/linear_teams/",
            HTTP_AUTHORIZATION=f"Bearer {key_value}",
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {"teams": [{"id": "team-id", "name": "Engineering"}]}
        mock_ensure_token_valid.assert_called_once_with(linear_integration)
        mock_list_teams.assert_called_once_with()

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
            ("slack", "feature_flag:read", status.HTTP_403_FORBIDDEN, "integration:read"),
            # GitHub and Twilio resolve via the queryset, but the channels action's kind
            # guard rejects them with a 400 before SlackIntegration is constructed.
            ("github", "integration:read", status.HTTP_400_BAD_REQUEST, "Slack"),
            ("twilio", "integration:read", status.HTTP_400_BAD_REQUEST, "Slack"),
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

    @patch("posthog.api.integration.SlackIntegration")
    def test_channels_action_search_and_pagination(self, mock_slack_class, client: HttpClient):
        slack_integration = Integration.objects.create(
            team=self.team,
            kind="slack",
            integration_id="T_SEARCH",
            config={"authed_user": {"id": "test_user_id"}},
            sensitive_config={"access_token": "test-token-123"},
            created_by=self.user,
        )
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
            {
                "id": "C3",
                "name": "engineering",
                "is_private": False,
                "is_member": True,
                "is_ext_shared": False,
                "is_private_without_access": False,
            },
            {
                "id": "CPRIVATE",
                "name": PRIVATE_CHANNEL_WITHOUT_ACCESS,
                "is_private": True,
                "is_member": False,
                "is_ext_shared": False,
                "is_private_without_access": True,
            },
        ]
        mock_slack_class.return_value = mock_slack_instance

        key_value = "test_key_slack_search"
        PersonalAPIKey.objects.create(
            label="Test Key",
            user=self.user,
            secure_value=hash_key_value(key_value),
            scopes=["integration:read"],
        )

        base_url = f"/api/environments/{self.team.pk}/integrations/{slack_integration.id}/channels/"

        response = client.get(
            f"{base_url}?search=eng&limit=10",
            HTTP_AUTHORIZATION=f"Bearer {key_value}",
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["channels"] == [
            {
                "id": "C3",
                "name": "engineering",
                "is_private": False,
                "is_member": True,
                "is_ext_shared": False,
                "is_private_without_access": False,
            }
        ]
        assert data["has_more"] is False

        response = client.get(
            f"{base_url}?limit=1&offset=1",
            HTTP_AUTHORIZATION=f"Bearer {key_value}",
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data["channels"]) == 1
        assert data["channels"][0]["id"] == "C2"
        assert data["has_more"] is True

        mock_slack_instance.list_channels.assert_called_once()

    @pytest.mark.parametrize(
        "query_string,expected_ids,expected_has_more",
        [
            # Default (no params) returns all visible (non-private-without-access) channels.
            ("", ["C1", "C2", "C3"], False),
            # Pagination beyond the dataset returns an empty page.
            ("?limit=10&offset=10", [], False),
            # Search + offset combine: "gen" fuzzy-matches general+engineering, offset=1 yields engineering.
            ("?search=gen&limit=1&offset=1", ["C3"], False),
        ],
        ids=["default-no-params", "offset-past-end", "search-with-offset"],
    )
    @patch("posthog.api.integration.SlackIntegration")
    def test_channels_action_pagination_scenarios(
        self,
        mock_slack_class,
        query_string: str,
        expected_ids: list[str],
        expected_has_more: bool,
        client: HttpClient,
    ):
        slack_integration = Integration.objects.create(
            team=self.team,
            kind="slack",
            integration_id="T_PAGE",
            config={"authed_user": {"id": "test_user_id"}},
            sensitive_config={"access_token": "test-token-123"},
            created_by=self.user,
        )
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
            {
                "id": "C3",
                "name": "engineering",
                "is_private": False,
                "is_member": True,
                "is_ext_shared": False,
                "is_private_without_access": False,
            },
        ]
        mock_slack_class.return_value = mock_slack_instance

        key_value = (
            f"test_key_slack_page_{query_string or 'default'}".replace("?", "_").replace("&", "_").replace("=", "_")
        )
        PersonalAPIKey.objects.create(
            label="Test Key",
            user=self.user,
            secure_value=hash_key_value(key_value),
            scopes=["integration:read"],
        )

        response = client.get(
            f"/api/environments/{self.team.pk}/integrations/{slack_integration.id}/channels/{query_string}",
            HTTP_AUTHORIZATION=f"Bearer {key_value}",
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert [channel["id"] for channel in data["channels"]] == expected_ids
        assert data["has_more"] is expected_has_more

    @pytest.mark.parametrize(
        "search,expected_ids",
        [
            # "team-product" (C2) is a weaker fuzzy match on "product", so it ranks below the exact hit.
            ("product analytics", ["C1", "C2"]),
            ("product_analytics", ["C1", "C2"]),
            ("analytics product", ["C1", "C2"]),
            ("prod analy", ["C1"]),
            ("analytcs", ["C1"]),
            ("product-analytics", ["C1", "C2"]),
            ("team", ["C2", "C3"]),
            ("C2", ["C2"]),
            ("nonexistent channel", []),
        ],
        ids=[
            "spaces-match-hyphens",
            "underscores-match-hyphens",
            "reordered-tokens",
            "partial-tokens",
            "typo-tolerant",
            "exact-hyphenated",
            "shared-token-multi-match",
            "channel-id-paste",
            "no-match",
        ],
    )
    @patch("posthog.api.integration.SlackIntegration")
    def test_channels_action_fuzzy_search(
        self,
        mock_slack_class,
        search: str,
        expected_ids: list[str],
        client: HttpClient,
    ):
        slack_integration = Integration.objects.create(
            team=self.team,
            kind="slack",
            integration_id="T_SEARCH",
            config={"authed_user": {"id": "test_user_id"}},
            sensitive_config={"access_token": "test-token-123"},
            created_by=self.user,
        )
        mock_slack_instance = MagicMock()
        mock_slack_instance.list_channels.return_value = [
            {
                "id": "C1",
                "name": "product-analytics",
                "is_private": False,
                "is_member": True,
                "is_ext_shared": False,
                "is_private_without_access": False,
            },
            {
                "id": "C2",
                "name": "team-product",
                "is_private": False,
                "is_member": True,
                "is_ext_shared": False,
                "is_private_without_access": False,
            },
            {
                "id": "C3",
                "name": "team-design",
                "is_private": False,
                "is_member": True,
                "is_ext_shared": False,
                "is_private_without_access": False,
            },
        ]
        mock_slack_class.return_value = mock_slack_instance

        key_value = f"test_key_slack_search_{search}".replace(" ", "_").replace("-", "_")
        PersonalAPIKey.objects.create(
            label="Test Key",
            user=self.user,
            secure_value=hash_key_value(key_value),
            scopes=["integration:read"],
        )

        response = client.get(
            f"/api/environments/{self.team.pk}/integrations/{slack_integration.id}/channels/?search={quote(search)}",
            HTTP_AUTHORIZATION=f"Bearer {key_value}",
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert [channel["id"] for channel in data["channels"]] == expected_ids

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

    def test_list_integrations_filtered_by_kind(self, client: HttpClient):
        client.force_login(self.user)

        response = client.get(f"/api/environments/{self.team.pk}/integrations/?kind=twilio")

        assert response.status_code == status.HTTP_200_OK
        results = response.json()["results"]
        assert len(results) == 1
        assert results[0]["kind"] == "twilio"


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
        store_unified_authorize_state(
            GitHubAuthorizeState(
                token="correct-token",
                flow=FlowKind.TEAM_INSTALL,
                user_id=self.user.id,
                team_id=self.team.pk,
                next_url="" or None,
            ),
        )

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

    def test_github_prepare_callback_stores_authorize_state(self, client: HttpClient):
        client.force_login(self.user)
        next_path = (
            f"/account-connected/github-integration?provider=github&project_id={self.team.pk}&connect_from=posthog_code"
        )

        response = client.post(
            f"/api/environments/{self.team.pk}/integrations/github/prepare_callback/",
            {"next": next_path},
            content_type="application/json",
        )

        assert response.status_code == status.HTTP_204_NO_CONTENT
        pending_token = cache.get(f"github_authorize_pending:{self.user.id}")
        assert pending_token
        cached = cache.get(f"github_authorize:{pending_token}")
        assert cached is not None
        assert cached["next"] == next_path
        assert cached["token"] == pending_token
        assert cached["team_id"] == self.team.pk

    def test_github_authorize_rejects_absolute_next_url(self, client: HttpClient):
        client.force_login(self.user)

        response = client.get(
            f"/api/environments/{self.team.pk}/integrations/authorize/",
            {"kind": "github", "next": "https://evil.com"},
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "next must be a relative path" in response.json()["detail"]

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
        store_unified_authorize_state(
            GitHubAuthorizeState(
                token=state_token,
                flow=FlowKind.TEAM_INSTALL,
                user_id=self.user.id,
                team_id=self.team.pk,
                next_url="" or None,
            ),
        )

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
        assert cache.get(f"github_authorize:{state_token}") is None
        assert cache.get(f"github_authorize_pending:{self.user.id}") is None

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
        store_unified_authorize_state(
            GitHubAuthorizeState(
                token=state_token,
                flow=FlowKind.TEAM_INSTALL,
                user_id=self.user.id,
                team_id=self.team.pk,
                next_url="" or None,
            ),
        )

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
        store_unified_authorize_state(
            GitHubAuthorizeState(
                token="victim-token",
                flow=FlowKind.TEAM_INSTALL,
                user_id=self.user.id,
                team_id=self.team.pk,
                next_url="" or None,
            ),
        )

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
        store_unified_authorize_state(
            GitHubAuthorizeState(
                token=state_token,
                flow=FlowKind.TEAM_INSTALL,
                user_id=self.user.id,
                team_id=self.team.pk,
                next_url="" or None,
            ),
        )

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
        store_unified_authorize_state(
            GitHubAuthorizeState(
                token=state_token,
                flow=FlowKind.TEAM_INSTALL,
                user_id=self.user.id,
                team_id=self.team.pk,
                next_url="" or None,
            ),
        )

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


class TestGitHubTeamIntegrationComplete:
    @pytest.fixture(autouse=True)
    def setup_environment(self, db):
        self.organization = Organization.objects.create(name="Test Org")
        self.team = Team.objects.create(organization=self.organization, name="Test Team")
        self.user = User.objects.create_and_join(
            self.organization, "test@posthog.com", "test", level=OrganizationMembership.Level.ADMIN
        )

    def _team_github_integration(self, installation_id: str = "12345") -> Integration:
        return Integration.objects.create(
            team=self.team,
            kind="github",
            integration_id=installation_id,
            config={"installation_id": installation_id},
            sensitive_config={"access_token": "ghs_test"},
        )

    def _github_user_authorization(self) -> GitHubUserAuthorization:
        return GitHubUserAuthorization(
            gh_id=42,
            gh_login="testuser",
            access_token="ghu_test",
            refresh_token=None,
            access_token_expires_in=None,
            refresh_token_expires_in=None,
        )

    @pytest.mark.parametrize(
        "query,must_not_contain",
        [
            ({"installation_id": "12345", "code": "abc", "setup_action": "install"}, []),
            (
                {
                    "installation_id": "12345",
                    "code": "abc",
                    "state": urlencode({"token": "personal-token", "source": "user_integration"}),
                },
                ["/complete/github-link"],
            ),
        ],
    )
    def test_unauthenticated_redirects_to_login(self, query, must_not_contain, client: HttpClient):
        response = client.get("/integrations/github/callback/", query)
        assert response.status_code == status.HTTP_302_FOUND
        location = response["Location"]
        assert location.startswith("/login?next=")
        assert "/integrations/github/callback" in location
        for forbidden in must_not_contain:
            assert forbidden not in location

    def test_github_error_redirects_with_setup_error(self, client: HttpClient):
        client.force_login(self.user)
        next_path = f"/project/{self.team.pk}/integrations/github"
        store_unified_authorize_state(
            GitHubAuthorizeState(
                token="t",
                flow=FlowKind.TEAM_INSTALL,
                user_id=self.user.id,
                team_id=self.team.pk,
                next_url=next_path,
            ),
        )

        response = client.get("/integrations/github/callback/", {"error": "access_denied"})

        assert response.status_code == status.HTTP_302_FOUND
        assert "github_setup_error=access_denied" in response["Location"]
        assert next_path in response["Location"]

    @override_settings(GITHUB_APP_CLIENT_ID="client_id", SITE_URL="https://us.posthog.com")
    def test_team_install_via_oauth_callback_routes_to_team_not_personal(self, client: HttpClient):
        # "Connect organization" seeds TEAM_INSTALL and sends the user to the App install URL. When
        # the App is already installed, GitHub returns to the OAuth callback URL (/complete/github-link/)
        # rather than the setup URL. The dispatcher must still complete this as a team flow — not hand it
        # to the personal finisher, which would link the installation personally and never create the team
        # Integration (landing on user-personal-integrations).
        client.force_login(self.user)
        next_path = f"/project/{self.team.pk}/settings/environment-integrations"
        store_unified_authorize_state(
            GitHubAuthorizeState(
                token="team-install-token",
                flow=FlowKind.TEAM_INSTALL,
                user_id=self.user.id,
                team_id=self.team.pk,
                next_url=next_path,
            ),
        )

        response = client.get(
            "/complete/github-link/",
            {
                "installation_id": "75826265",
                "setup_action": "update",
                "state": urlencode({"token": "team-install-token"}),
            },
        )

        assert response.status_code == status.HTTP_302_FOUND
        # Installation isn't a team integration yet, so the team flow bounces to team OAuth to mint a
        # code — it must NOT land on the personal success page.
        assert "github.com/login/oauth/authorize" in response["Location"]
        assert "user-personal-integrations" not in response["Location"]

    def test_missing_installation_id_redirects_pending(self, client: HttpClient):
        client.force_login(self.user)
        next_path = f"/project/{self.team.pk}/integrations/github"
        store_unified_authorize_state(
            GitHubAuthorizeState(
                token="t",
                flow=FlowKind.TEAM_INSTALL,
                user_id=self.user.id,
                team_id=self.team.pk,
                next_url=next_path,
            ),
        )

        response = client.get("/integrations/github/callback/")

        assert response.status_code == status.HTTP_302_FOUND
        assert "github_install_pending=1" in response["Location"]

    @patch("posthog.models.github_integration_base.GitHubIntegrationBase.verify_user_installation_access")
    @patch("posthog.models.integration.GitHubIntegration.github_user_from_code")
    @patch("posthog.models.integration.GitHubIntegration.integration_from_installation_id")
    @patch("posthog.models.user_integration.user_github_integration_from_installation")
    def test_success_redirects_to_next_with_integration_id(
        self, mock_user_integration, mock_from_install, mock_from_code, mock_verify, client: HttpClient
    ):
        client.force_login(self.user)
        next_path = (
            f"/account-connected/github-integration?provider=github&project_id={self.team.pk}&connect_from=posthog_code"
        )
        state_token = "valid-token"
        store_unified_authorize_state(
            GitHubAuthorizeState(
                token=state_token,
                flow=FlowKind.TEAM_INSTALL,
                user_id=self.user.id,
                team_id=self.team.pk,
                next_url=next_path or None,
            ),
        )

        mock_from_code.return_value = self._github_user_authorization()
        mock_verify.return_value = True
        mock_from_install.return_value = self._team_github_integration()

        response = client.get(
            "/integrations/github/callback/",
            {
                "installation_id": "12345",
                "code": "oauth-code-abc",
                "setup_action": "install",
                "state": urlencode({"next": next_path, "token": state_token}),
            },
        )

        assert response.status_code == status.HTTP_302_FOUND
        location = response["Location"]
        assert "account-connected/github-integration" in location
        assert "integration_id=" in location
        assert "installation_id=12345" in location
        assert cache.get(f"github_authorize:{state_token}") is None
        assert cache.get(f"github_authorize_pending:{self.user.id}") is None

    def test_forged_state_cannot_complete_team_install(self, client: HttpClient):
        member = User.objects.create_and_join(
            self.organization, "member@posthog.com", "test", level=OrganizationMembership.Level.MEMBER
        )
        client.force_login(member)

        # No valid authorize state — the member supplies the team via the user-controlled `state` `next`,
        # which resolves team_id purely from the path. Membership now suffices to *add* an integration, so
        # state-token validation (not the permission gate) is what must stop a forged callback from creating one.
        next_path = f"/project/{self.team.pk}/integrations/github"
        response = client.get(
            "/integrations/github/callback/",
            {
                "installation_id": "12345",
                "code": "oauth-code-abc",
                "setup_action": "install",
                "state": urlencode({"next": next_path, "token": "no-such-token"}),
            },
        )

        assert response.status_code == status.HTTP_302_FOUND
        assert "github_setup_error=invalid_state" in response["Location"]
        assert not Integration.objects.filter(team=self.team, kind="github").exists()

    @patch("posthog.models.github_integration_base.GitHubIntegrationBase.verify_user_installation_access")
    @patch("posthog.models.integration.GitHubIntegration.github_user_from_code")
    @patch("posthog.models.integration.GitHubIntegration.integration_from_installation_id")
    @patch("posthog.models.user_integration.user_github_integration_from_installation")
    def test_member_can_complete_fresh_team_install(
        self, mock_user_integration, mock_from_install, mock_from_code, mock_verify, client: HttpClient
    ):
        # Adding a brand-new integration only requires project membership.
        member = User.objects.create_and_join(
            self.organization, "member@posthog.com", "test", level=OrganizationMembership.Level.MEMBER
        )
        client.force_login(member)
        next_path = f"/project/{self.team.pk}/settings/environment-integrations"
        state_token = "member-install-token"
        store_unified_authorize_state(
            GitHubAuthorizeState(
                token=state_token,
                flow=FlowKind.TEAM_INSTALL,
                user_id=member.id,
                team_id=self.team.pk,
                next_url=next_path,
            ),
        )
        mock_from_code.return_value = self._github_user_authorization()
        mock_verify.return_value = True
        # side_effect (not return_value) so the row is created when execute runs — after the
        # permission check — matching a genuine first-time install where nothing exists yet.
        mock_from_install.side_effect = lambda *args, **kwargs: self._team_github_integration()

        response = client.get(
            "/integrations/github/callback/",
            {
                "installation_id": "12345",
                "code": "oauth-code-abc",
                "setup_action": "install",
                "state": urlencode({"next": next_path, "token": state_token}),
            },
        )

        assert response.status_code == status.HTTP_302_FOUND
        assert "github_setup_error" not in response["Location"]
        assert Integration.objects.filter(team=self.team, kind="github", integration_id="12345").exists()

    def test_member_cannot_modify_existing_team_integration(self, client: HttpClient):
        # An integration already exists, so completing the callback would *modify* it — that still needs admin.
        existing = self._team_github_integration()
        member = User.objects.create_and_join(
            self.organization, "member@posthog.com", "test", level=OrganizationMembership.Level.MEMBER
        )
        client.force_login(member)
        next_path = f"/project/{self.team.pk}/integrations/github"

        response = client.get(
            "/integrations/github/callback/",
            {
                "installation_id": "12345",
                "setup_action": "update",
                "state": urlencode({"next": next_path, "token": "no-such-token"}),
            },
        )

        assert response.status_code == status.HTTP_302_FOUND
        assert "github_setup_error=insufficient_permissions" in response["Location"]
        # The existing integration must be untouched — no member-driven reconnect.
        assert Integration.objects.filter(id=existing.id).count() == 1

    @patch("posthog.models.github_integration_base.GitHubIntegrationBase.verify_user_installation_access")
    @patch("posthog.models.integration.GitHubIntegration.github_user_from_code")
    @patch("posthog.models.integration.GitHubIntegration.integration_from_installation_id")
    @patch("posthog.models.user_integration.user_github_integration_from_installation")
    def test_environment_integrations_flow_uses_team_id_from_authorize_cache(
        self, mock_user_integration, mock_from_install, mock_from_code, mock_verify, client: HttpClient
    ):
        client.force_login(self.user)

        next_path = f"/project/{self.team.pk}/settings/environment-integrations"
        state_token = "legacy-token"
        store_unified_authorize_state(
            GitHubAuthorizeState(
                token=state_token,
                flow=FlowKind.TEAM_INSTALL,
                user_id=self.user.id,
                team_id=self.team.pk,
                next_url=next_path or None,
            ),
        )

        mock_from_code.return_value = self._github_user_authorization()
        mock_verify.return_value = True
        mock_from_install.return_value = self._team_github_integration()

        response = client.get(
            "/integrations/github/callback/",
            {
                "installation_id": "12345",
                "code": "oauth-code-abc",
                "setup_action": "install",
                "state": urlencode({"next": next_path, "token": state_token}),
            },
        )

        assert response.status_code == status.HTTP_302_FOUND
        assert "github_setup_error=invalid_state" not in response["Location"]
        assert "integration_id=" in response["Location"]

    @patch("posthog.models.integration.GitHubIntegration.verify_user_installation_access", return_value=True)
    @patch("posthog.models.integration.GitHubIntegration.client_request")
    @patch("posthog.models.integration.GitHubIntegration.github_user_from_code")
    def test_personal_github_setup_finishes_inline(
        self, mock_user_from_code, mock_client_request, mock_verify, client: HttpClient
    ):
        client.force_login(self.user)
        state_token = "personal-install-token"
        state = urlencode({"token": state_token, "source": "user_integration"})
        store_unified_authorize_state(
            GitHubAuthorizeState(token=state_token, flow=FlowKind.PERSONAL_INSTALL, user_id=self.user.id),
        )

        mock_user_from_code.return_value = GitHubUserAuthorization(
            gh_id=99,
            gh_login="octocat",
            access_token="gho_access",
            refresh_token="ghr_refresh",
            access_token_expires_in=28800,
            refresh_token_expires_in=15897600,
        )
        mock_install_info = MagicMock()
        mock_install_info.json.return_value = {
            "account": {"type": "User", "login": "octocat"},
        }
        mock_access_token = MagicMock()
        mock_access_token.json.return_value = {
            "token": "ghs_install_token",
            "expires_at": "2099-01-01T00:00:00Z",
            "repository_selection": "selected",
        }
        mock_client_request.side_effect = [mock_install_info, mock_access_token]

        response = client.get(
            "/integrations/github/callback/",
            {
                "installation_id": "12345",
                "code": "oauth-code-abc",
                "setup_action": "install",
                "state": state,
            },
        )

        assert response.status_code == status.HTTP_302_FOUND
        assert "github_link_success=1" in response["Location"]
        assert "/complete/github-link" not in response["Location"]
        mock_user_from_code.assert_called_once_with("oauth-code-abc")

    @patch("posthog.models.integration.GitHubIntegration.verify_user_installation_access", return_value=True)
    @patch("posthog.models.integration.GitHubIntegration.client_request")
    @patch("posthog.models.integration.GitHubIntegration.github_user_from_code")
    def test_personal_github_setup_with_forged_team_next_still_finishes_personal(
        self, mock_user_from_code, mock_client_request, mock_verify, client: HttpClient
    ):
        # A personal install whose callback `state` has been tampered — `source=user_integration`
        # stripped and a team `next` injected — must route by the server-side cached flow to the
        # personal finisher, never fall through to team setup. self.user is an org admin, so without
        # flow-based routing the forged `next` would otherwise reach team setup and pass its admin gate.
        client.force_login(self.user)
        state_token = "personal-install-token"
        forged_state = urlencode({"token": state_token, "next": f"/project/{self.team.pk}/integrations/github"})
        store_unified_authorize_state(
            GitHubAuthorizeState(token=state_token, flow=FlowKind.PERSONAL_INSTALL, user_id=self.user.id),
        )

        mock_user_from_code.return_value = GitHubUserAuthorization(
            gh_id=99,
            gh_login="octocat",
            access_token="gho_access",
            refresh_token="ghr_refresh",
            access_token_expires_in=28800,
            refresh_token_expires_in=15897600,
        )
        mock_install_info = MagicMock()
        mock_install_info.json.return_value = {"account": {"type": "User", "login": "octocat"}}
        mock_access_token = MagicMock()
        mock_access_token.json.return_value = {
            "token": "ghs_install_token",
            "expires_at": "2099-01-01T00:00:00Z",
            "repository_selection": "selected",
        }
        mock_client_request.side_effect = [mock_install_info, mock_access_token]

        response = client.get(
            "/integrations/github/callback/",
            {
                "installation_id": "12345",
                "code": "oauth-code-abc",
                "setup_action": "install",
                "state": forged_state,
            },
        )

        assert response.status_code == status.HTTP_302_FOUND
        assert "github_link_success=1" in response["Location"]
        # Personal install exchanges the code without the OAuth redirect_uri — proving the personal path ran.
        mock_user_from_code.assert_called_once_with("oauth-code-abc")
        # The forged team `next` created no team integration; only the user's personal one exists.
        assert not Integration.objects.filter(team=self.team, kind="github").exists()
        assert UserIntegration.objects.filter(user=self.user, kind="github", integration_id="12345").exists()

    @patch("posthog.models.integration.GitHubIntegration.client_request")
    def test_personal_github_setup_update_redirects_to_personal_settings(self, mock_client_request, client: HttpClient):
        client.force_login(self.user)
        UserIntegration.objects.create(
            user=self.user,
            kind="github",
            integration_id="12345",
            config={"installation_id": "12345", "repository_selection": "selected"},
            sensitive_config={"access_token": "ghs_old", "user_access_token": "gho_user"},
        )
        mock_install_info = MagicMock()
        mock_install_info.json.return_value = {
            "account": {"type": "User", "login": "octocat"},
        }
        mock_access_token = MagicMock()
        mock_access_token.json.return_value = {
            "token": "ghs_install_token",
            "expires_at": "2099-01-01T00:00:00Z",
            "repository_selection": "all",
        }
        mock_client_request.side_effect = [mock_install_info, mock_access_token]

        response = client.get(
            "/integrations/github/callback/",
            {"installation_id": "12345", "setup_action": "update"},
        )

        assert response.status_code == status.HTTP_302_FOUND
        assert "github_link_success=1" in response["Location"]
        assert "user-personal-integrations" in response["Location"]
        assert "github_setup_error" not in response["Location"]
        assert "project-integrations" not in response["Location"]

        integration = UserIntegration.objects.get(user=self.user, integration_id="12345")
        assert integration.config["repository_selection"] == "all"
        assert integration.sensitive_config["access_token"] == "ghs_install_token"
        assert integration.sensitive_config["user_access_token"] == "gho_user"

    @patch("posthog.models.integration.GitHubIntegration.integration_from_installation_id")
    def test_team_github_setup_update_without_state_redirects_to_project_integrations(
        self, mock_refresh, client: HttpClient
    ):
        client.force_login(self.user)
        mock_refresh.return_value = self._team_github_integration()

        response = client.get(
            "/integrations/github/callback/",
            {"installation_id": "12345", "setup_action": "update"},
        )

        assert response.status_code == status.HTTP_302_FOUND
        assert f"project/{self.team.pk}/integrations/github" in response["Location"]
        assert "integration_id=" in response["Location"]
        assert "github_setup_error" not in response["Location"]
        mock_refresh.assert_called_once_with("12345", self.team.pk, self.user)

    @patch("posthog.models.integration.GitHubIntegration.integration_from_installation_id")
    def test_update_setup_action_via_callback_redirects_successfully(self, mock_refresh, client: HttpClient):
        client.force_login(self.user)
        mock_refresh.return_value = self._team_github_integration(installation_id="98797544")
        next_path = f"/project/{self.team.pk}/settings/environment-integrations"
        state_token = "ad89fbef5ced409fa055f4918b4a06b664f938506ed7aa8007cdc6cfd819be1055"
        store_unified_authorize_state(
            GitHubAuthorizeState(
                token=state_token,
                flow=FlowKind.TEAM_INSTALL,
                user_id=self.user.id,
                team_id=self.team.pk,
                next_url=next_path or None,
            ),
        )

        response = client.get(
            "/integrations/github/callback/",
            {
                "installation_id": "98797544",
                "code": "5e9f6928598ebb891367",
                "setup_action": "update",
                "state": urlencode({"next": next_path, "token": state_token}),
            },
        )

        assert response.status_code == status.HTTP_302_FOUND
        assert "github_setup_error" not in response["Location"]
        assert "integration_id=" in response["Location"]
        mock_refresh.assert_called_once()

    @patch("posthog.models.integration.GitHubIntegration.integration_from_installation_id")
    def test_prepare_callback_update_without_state_redirects_to_account_connected(
        self, mock_refresh, client: HttpClient
    ):
        client.force_login(self.user)
        mock_refresh.return_value = self._team_github_integration()
        next_path = (
            f"/account-connected/github-integration?provider=github&project_id={self.team.pk}&connect_from=posthog_code"
        )
        store_unified_authorize_state(
            GitHubAuthorizeState(
                token="prepare-token",
                flow=FlowKind.TEAM_UPDATE,
                user_id=self.user.id,
                team_id=self.team.pk,
                next_url=next_path or None,
            ),
        )

        response = client.get(
            "/integrations/github/callback/",
            {"installation_id": "12345", "setup_action": "update"},
        )

        assert response.status_code == status.HTTP_302_FOUND
        assert "account-connected/github-integration" in response["Location"]
        assert "integration_id=" in response["Location"]
        mock_refresh.assert_called_once()

    @pytest.mark.parametrize("callback_installation_id,expect_error", [("12345", False), ("99999", True)])
    @patch("posthog.models.integration.GitHubIntegration.integration_from_installation_id")
    def test_team_update_callback_binds_seeded_installation_id(
        self, mock_refresh, callback_installation_id, expect_error, client: HttpClient
    ):
        client.force_login(self.user)
        mock_refresh.return_value = self._team_github_integration(installation_id="12345")
        store_unified_authorize_state(
            GitHubAuthorizeState(
                token="prepare-token",
                flow=FlowKind.TEAM_UPDATE,
                user_id=self.user.id,
                team_id=self.team.pk,
                installation_id="12345",
            ),
        )

        response = client.get(
            "/integrations/github/callback/",
            {"installation_id": callback_installation_id, "setup_action": "update"},
        )

        assert response.status_code == status.HTTP_302_FOUND
        if expect_error:
            assert "github_setup_error=invalid_state" in response["Location"]
            assert not Integration.objects.filter(team=self.team, integration_id=callback_installation_id).exists()
        else:
            assert "github_setup_error" not in response["Location"]
            assert "integration_id=" in response["Location"]

    def test_install_callback_without_state_redirects_invalid_state(self, client: HttpClient):
        client.force_login(self.user)
        next_path = f"/project/{self.team.pk}/integrations/github"
        store_unified_authorize_state(
            GitHubAuthorizeState(
                token="valid-token",
                flow=FlowKind.TEAM_INSTALL,
                user_id=self.user.id,
                team_id=self.team.pk,
                next_url=next_path,
            ),
        )

        response = client.get(
            "/integrations/github/callback/",
            {"installation_id": "12345", "code": "oauth-code-abc", "setup_action": "install"},
        )

        assert response.status_code == status.HTTP_302_FOUND
        assert "github_setup_error=invalid_state" in response["Location"]

    @patch("posthog.api.github_callback.team_services.build_team_github_oauth_authorize_url")
    def test_orphan_installation_update_redirects_to_oauth(self, mock_build_oauth_url, client: HttpClient):
        mock_build_oauth_url.return_value = "https://github.com/login/oauth/authorize?client_id=test"
        client.force_login(self.user)
        next_path = f"/project/{self.team.pk}/integrations/github"
        state_token = "orphan-token"
        store_unified_authorize_state(
            GitHubAuthorizeState(
                token=state_token,
                flow=FlowKind.TEAM_INSTALL,
                user_id=self.user.id,
                team_id=self.team.pk,
                next_url=next_path,
            ),
        )

        response = client.get(
            "/integrations/github/callback/",
            {
                "installation_id": "99999",
                "setup_action": "update",
                "state": urlencode({"next": next_path, "token": state_token}),
            },
        )

        assert response.status_code == status.HTTP_302_FOUND
        assert response["Location"].startswith("https://github.com/login/oauth/authorize")
        mock_build_oauth_url.assert_called_once()

    @patch("posthog.models.integration.GitHubIntegration.integration_from_installation_id")
    def test_admin_links_existing_org_installation_without_personal_github(self, mock_from_install, client: HttpClient):
        # A GitHub App installs once per org, so a second project hits the Setup URL with
        # setup_action=update and no OAuth code. A team admin must be able to complete that link
        # off the installation already connected to a sibling team, without a personal GitHub link.
        sibling = Team.objects.create(organization=self.organization, name="Sibling Team")
        Integration.objects.create(
            team=sibling,
            kind="github",
            integration_id="12345",
            config={"installation_id": "12345", "connecting_user_github_login": "owneruser"},
            sensitive_config={"access_token": "ghs_sibling"},
        )
        # self.user is an org admin with no UserIntegration (personal GitHub link).
        assert not UserIntegration.objects.filter(user=self.user, kind="github").exists()
        mock_from_install.side_effect = lambda *args, **kwargs: self._team_github_integration()

        client.force_login(self.user)
        next_path = f"/project/{self.team.pk}/integrations/github"
        state_token = "link-existing-token"
        store_unified_authorize_state(
            GitHubAuthorizeState(
                token=state_token,
                flow=FlowKind.TEAM_INSTALL,
                user_id=self.user.id,
                team_id=self.team.pk,
                next_url=next_path,
            ),
        )

        response = client.get(
            "/integrations/github/callback/",
            {
                "installation_id": "12345",
                "setup_action": "update",
                "state": urlencode({"next": next_path, "token": state_token}),
            },
        )

        assert response.status_code == status.HTTP_302_FOUND
        assert "github_setup_error" not in response["Location"]
        assert Integration.objects.filter(team=self.team, kind="github", integration_id="12345").exists()

    def test_authorize_link_existing_requires_personal_github_for_non_admin(self):
        # The admin bypass must not leak to plain members: without team admin access and without a
        # personal GitHub link, linking an existing installation still demands the personal token.
        member = User.objects.create_and_join(
            self.organization, "member-linker@posthog.com", "test", level=OrganizationMembership.Level.MEMBER
        )
        with pytest.raises(ValidationError) as exc_info:
            authorize_link_existing_installation(user=member, team=self.team, source_installation_id="12345")
        codes = exc_info.value.get_codes()
        assert isinstance(codes, list) and GITHUB_LINK_EXISTING_ERROR_PERSONAL_GITHUB_REQUIRED in codes

    def test_cross_user_state_rejected_on_unified_callback(self, client: HttpClient):
        # State tokens are bound to a user via the pending-pointer cache key.
        # Another admin in the same team must not be able to finish a callback
        # by submitting the victim's state token.
        attacker = User.objects.create_and_join(
            self.organization, "attacker@posthog.com", "test", level=OrganizationMembership.Level.ADMIN
        )
        next_path = f"/project/{self.team.pk}/integrations/github"
        state_token = "victim-token"
        store_unified_authorize_state(
            GitHubAuthorizeState(
                token=state_token,
                flow=FlowKind.TEAM_INSTALL,
                user_id=self.user.id,
                team_id=self.team.pk,
                next_url=next_path,
            ),
        )

        client.force_login(attacker)
        response = client.get(
            "/integrations/github/callback/",
            {
                "installation_id": "12345",
                "code": "oauth-code-abc",
                "setup_action": "install",
                "state": urlencode({"next": next_path, "token": state_token}),
            },
        )

        assert response.status_code == status.HTTP_302_FOUND
        assert "github_setup_error=invalid_state" in response["Location"]

    @pytest.mark.parametrize("stored_installation_id", [12345, "12345"])
    @patch("posthog.models.integration.GitHubIntegration.integration_from_installation_id")
    def test_team_update_heuristic_finds_existing_integration_regardless_of_jsonb_id_type(
        self, mock_refresh, stored_installation_id, client: HttpClient
    ):
        # ``config.installation_id`` has historically been written as either a
        # JSONB number or string; the update-without-state heuristic must match
        # either (it previously raised ``MultipleObjectsReturned`` when mixed).
        client.force_login(self.user)
        existing = Integration.objects.create(
            team=self.team,
            kind="github",
            integration_id="12345",
            config={"installation_id": stored_installation_id},
            sensitive_config={"access_token": "ghs_test"},
        )
        mock_refresh.return_value = existing

        response = client.get(
            "/integrations/github/callback/",
            {"installation_id": "12345", "setup_action": "update"},
        )

        assert response.status_code == status.HTTP_302_FOUND
        assert "github_setup_error" not in response["Location"]
        assert f"integration_id={existing.id}" in response["Location"]

    @patch("posthog.models.integration.GitHubIntegration.integration_from_installation_id")
    def test_team_prepare_callback_update_wins_when_personal_integration_also_exists(
        self, mock_refresh, client: HttpClient
    ):
        client.force_login(self.user)
        team_integration = self._team_github_integration()
        UserIntegration.objects.create(
            user=self.user,
            kind="github",
            integration_id="12345",
            config={"installation_id": "12345"},
            sensitive_config={"access_token": "ghs_old", "user_access_token": "gho_user"},
        )
        next_path = f"/project/{self.team.pk}/settings/environment-integrations"
        store_unified_authorize_state(
            GitHubAuthorizeState(
                token="team-update-token",
                flow=FlowKind.TEAM_UPDATE,
                user_id=self.user.id,
                team_id=self.team.pk,
                next_url=next_path,
            ),
        )
        mock_refresh.return_value = team_integration

        response = client.get(
            "/integrations/github/callback/",
            {"installation_id": "12345", "setup_action": "update"},
        )

        assert response.status_code == status.HTTP_302_FOUND
        assert "environment-integrations" in response["Location"]
        assert "user-personal-integrations" not in response["Location"]
        assert "github_link_success" not in response["Location"]
        assert f"integration_id={team_integration.id}" in response["Location"]
        mock_refresh.assert_called_once()


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

    @patch("stripe.StripeClient")
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

    @patch("stripe.StripeClient")
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

    @parameterized.expand(
        [
            ("write", "write_posthog_secrets"),
            ("clear", "clear_posthog_secrets"),
        ]
    )
    @patch("stripe.StripeClient")
    @patch("posthog.models.integration.settings")
    def test_stripe_client_uses_live_secret(self, _name, method_name, mock_settings, MockStripeClient):
        mock_settings.STRIPE_POSTHOG_OAUTH_CLIENT_ID = self.oauth_app.client_id
        mock_settings.STRIPE_APP_SECRET_KEY = "sk_live"
        MockStripeClient.return_value = MagicMock()

        integration = Integration.objects.create(
            team=self.team,
            kind="stripe",
            config={},
            sensitive_config={},
            integration_id=f"acct_{_name}",
            created_by=self.user,
        )
        stripe_int = StripeIntegration(integration)
        if method_name == "write_posthog_secrets":
            stripe_int.write_posthog_secrets(self.team.pk, self.user)
        else:
            stripe_int.clear_posthog_secrets()

        MockStripeClient.assert_called_once_with("sk_live")

    @patch("posthog.models.integration.capture_exception")
    @patch("stripe.StripeClient")
    @patch("posthog.models.integration.settings")
    def test_write_posthog_secrets_skips_when_keys_missing(self, mock_settings, MockStripeClient, mock_capture):
        mock_settings.STRIPE_POSTHOG_OAUTH_CLIENT_ID = self.oauth_app.client_id
        mock_settings.STRIPE_APP_CLIENT_ID = None
        mock_settings.STRIPE_APP_SECRET_KEY = None
        MockStripeClient.return_value = MagicMock()

        integration = Integration.objects.create(
            team=self.team,
            kind="stripe",
            config={},
            sensitive_config={},
            integration_id="acct_missing_write",
            created_by=self.user,
        )
        stripe_int = StripeIntegration(integration)
        stripe_int.write_posthog_secrets(self.team.pk, self.user)

        MockStripeClient.assert_not_called()
        mock_capture.assert_called_once()
        captured_exc = mock_capture.call_args.args[0]
        assert isinstance(captured_exc, NotImplementedError)

    @patch("posthog.models.integration.capture_exception")
    @patch("stripe.StripeClient")
    @patch("posthog.models.integration.settings")
    def test_clear_posthog_secrets_skips_and_revokes_tokens_when_keys_missing(
        self, mock_settings, MockStripeClient, mock_capture
    ):
        mock_settings.STRIPE_POSTHOG_OAUTH_CLIENT_ID = self.oauth_app.client_id
        mock_settings.STRIPE_APP_CLIENT_ID = None
        mock_settings.STRIPE_APP_SECRET_KEY = None
        MockStripeClient.return_value = MagicMock()

        integration, access_token, refresh_token = self._create_integration_with_tokens()

        stripe_int = StripeIntegration(integration)
        stripe_int.clear_posthog_secrets()

        MockStripeClient.assert_not_called()
        mock_capture.assert_called_once()
        assert not OAuthAccessToken.objects.filter(pk=access_token.pk).exists()
        assert not OAuthRefreshToken.objects.filter(pk=refresh_token.pk).exists()


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

    @patch("posthog.egress.transport.transport.requests.request")
    def test_list_branches_returns_first_page(self, mock_request):
        names = [f"branch-{i}" for i in range(100)]
        mock_request.return_value = _make_github_branches_response(names, has_next=True)

        branches, has_more = self.github.list_branches("org/repo", limit=100, offset=0)

        assert branches == names
        assert has_more is True
        mock_request.assert_called_once()
        assert "page=1" in mock_request.call_args[0][1]

    @patch("posthog.egress.transport.transport.requests.request")
    def test_list_branches_offset_skips_pages(self, mock_request):
        """Requesting offset=200 should start fetching from GitHub page 3."""
        page3_names = [f"branch-{i}" for i in range(200, 300)]
        mock_request.return_value = _make_github_branches_response(page3_names, has_next=True)

        branches, has_more = self.github.list_branches("org/repo", limit=100, offset=200)

        assert branches == page3_names
        assert has_more is True
        assert mock_request.call_count == 1
        assert "page=3" in mock_request.call_args[0][1]

    @patch("posthog.egress.transport.transport.requests.request")
    def test_list_branches_last_page_no_more(self, mock_request):
        names = [f"branch-{i}" for i in range(50)]
        mock_request.return_value = _make_github_branches_response(names, has_next=False)

        branches, has_more = self.github.list_branches("org/repo", limit=100, offset=0)

        assert branches == names
        assert has_more is False

    @patch("posthog.egress.transport.transport.requests.request")
    def test_list_branches_spans_two_github_pages(self, mock_request):
        """An offset that doesn't align with per_page=100 requires fetching two GitHub pages."""
        page1_names = [f"branch-{i}" for i in range(100)]
        page2_names = [f"branch-{i}" for i in range(100, 200)]

        mock_request.side_effect = [
            _make_github_branches_response(page1_names, has_next=True),
            _make_github_branches_response(page2_names, has_next=False),
        ]

        branches, has_more = self.github.list_branches("org/repo", limit=100, offset=50)

        assert len(branches) == 100
        assert branches == [f"branch-{i}" for i in range(50, 150)]
        # There are still branches 150-199 beyond this window
        assert has_more is True
        assert mock_request.call_count == 2

    @patch("posthog.egress.transport.transport.requests.request")
    def test_list_branches_empty_repo(self, mock_request):
        mock_request.return_value = _make_github_branches_response([], has_next=False)

        branches, has_more = self.github.list_branches("org/repo")

        assert branches == []
        assert has_more is False

    @patch("posthog.egress.transport.transport.requests.request")
    def test_list_branches_401_triggers_refresh_and_retry(self, mock_request):
        unauthorized = MagicMock()
        unauthorized.status_code = 401

        names = ["main", "develop"]
        success = _make_github_branches_response(names, has_next=False)

        mock_request.side_effect = [unauthorized, success]

        with patch.object(self.github, "refresh_access_token"):
            branches, has_more = self.github.list_branches("org/repo")

        assert branches == names
        assert mock_request.call_count == 2

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

    @patch("posthog.egress.transport.transport.requests.request")
    def test_get_default_branch_is_cached(self, mock_request):
        from django.core.cache import cache

        cache.clear()

        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {"default_branch": "develop"}
        mock_request.return_value = response

        first = self.github.get_default_branch("org/repo-cache-test")
        second = self.github.get_default_branch("org/repo-cache-test")

        assert first == "develop"
        assert second == "develop"
        assert mock_request.call_count == 1


class TestAnthropicIntegration:
    @pytest.fixture(autouse=True)
    def setup_integration(self, db):
        self.organization = Organization.objects.create(name="Test Org")
        self.team = Team.objects.create(organization=self.organization, name="Test Team")
        self.user = User.objects.create_and_join(
            self.organization, "test@posthog.com", "test", level=OrganizationMembership.Level.ADMIN
        )

    @staticmethod
    def _mock_anthropic_validate_key(mock_anthropic_class) -> MagicMock:
        """Configure the patched `Anthropic` class so `validate_key()` (now hits `/v1/agents`) succeeds."""
        mock_client = MagicMock()
        mock_anthropic_class.return_value = mock_client
        mock_client.get.return_value = {"data": []}
        return mock_client

    @patch("anthropic.Anthropic")
    def test_create_with_valid_key(self, mock_anthropic_class, client: HttpClient):
        self._mock_anthropic_validate_key(mock_anthropic_class)

        client.force_login(self.user)
        response = client.post(
            f"/api/environments/{self.team.pk}/integrations",
            {
                "kind": "anthropic",
                "config": {"api_key": "sk-ant-test", "workspace_label": "production"},
            },
            content_type="application/json",
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert response.json()["kind"] == "anthropic"

        integration = Integration.objects.get(id=response.json()["id"])
        assert integration.kind == "anthropic"
        assert integration.team == self.team
        assert integration.config == {"workspace_label": "production"}
        assert integration.sensitive_config == {"api_key": "sk-ant-test"}
        assert integration.integration_id == "production"
        assert integration.created_by == self.user

        # Assert the anthropic-beta was called to validate the key during creation.
        get_call = mock_anthropic_class.return_value.get.call_args
        assert get_call.args[0] == "/v1/agents"
        assert get_call.kwargs["options"]["headers"]["anthropic-beta"] == "managed-agents-2026-04-01"

    @patch("anthropic.Anthropic")
    def test_create_strips_whitespace_from_api_key(self, mock_anthropic_class, client: HttpClient):
        self._mock_anthropic_validate_key(mock_anthropic_class)

        client.force_login(self.user)
        response = client.post(
            f"/api/environments/{self.team.pk}/integrations",
            {"kind": "anthropic", "config": {"api_key": "  sk-ant-test  "}},
            content_type="application/json",
        )

        assert response.status_code == status.HTTP_201_CREATED
        integration = Integration.objects.get(id=response.json()["id"])
        assert integration.sensitive_config == {"api_key": "sk-ant-test"}

    @patch("anthropic.Anthropic")
    def test_create_without_workspace_label_uses_default_id(self, mock_anthropic_class, client: HttpClient):
        self._mock_anthropic_validate_key(mock_anthropic_class)

        client.force_login(self.user)
        response = client.post(
            f"/api/environments/{self.team.pk}/integrations",
            {"kind": "anthropic", "config": {"api_key": "sk-ant-test"}},
            content_type="application/json",
        )

        assert response.status_code == status.HTTP_201_CREATED
        integration = Integration.objects.get(id=response.json()["id"])
        assert integration.config == {}
        assert integration.integration_id == f"workspace-{self.team.pk}"

    @patch("anthropic.Anthropic")
    def test_create_rejects_existing_workspace_without_force(self, mock_anthropic_class, client: HttpClient):
        self._mock_anthropic_validate_key(mock_anthropic_class)

        client.force_login(self.user)
        response = client.post(
            f"/api/environments/{self.team.pk}/integrations",
            {"kind": "anthropic", "config": {"api_key": "sk-ant-first", "workspace_label": "production"}},
            content_type="application/json",
        )
        assert response.status_code == status.HTTP_201_CREATED
        first_id = response.json()["id"]

        response = client.post(
            f"/api/environments/{self.team.pk}/integrations",
            {"kind": "anthropic", "config": {"api_key": "sk-ant-second", "workspace_label": "production"}},
            content_type="application/json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "already exists" in str(response.json())
        # Original key untouched.
        integration = Integration.objects.get(id=first_id)
        assert integration.sensitive_config == {"api_key": "sk-ant-first"}

    @patch("anthropic.Anthropic")
    def test_create_overwrites_with_force_flag(self, mock_anthropic_class, client: HttpClient):
        self._mock_anthropic_validate_key(mock_anthropic_class)

        client.force_login(self.user)
        response = client.post(
            f"/api/environments/{self.team.pk}/integrations",
            {"kind": "anthropic", "config": {"api_key": "sk-ant-first", "workspace_label": "production"}},
            content_type="application/json",
        )
        first_id = response.json()["id"]

        response = client.post(
            f"/api/environments/{self.team.pk}/integrations",
            {
                "kind": "anthropic",
                "config": {"api_key": "sk-ant-second", "workspace_label": "production", "force": True},
            },
            content_type="application/json",
        )

        assert response.status_code == status.HTTP_201_CREATED
        # Same row reused (same (team, kind, integration_id) tuple) with rotated key.
        assert response.json()["id"] == first_id
        integration = Integration.objects.get(id=first_id)
        assert integration.sensitive_config == {"api_key": "sk-ant-second"}

    @pytest.mark.parametrize(
        "config,expected_error_substring",
        [
            ({}, "Anthropic API key"),
            ({"api_key": ""}, "Anthropic API key"),
            ({"api_key": "   "}, "Anthropic API key"),
            ({"api_key": "sk-ant-with\nnewline"}, "must not contain whitespace"),
            ({"api_key": "sk-ant-test", "workspace_label": "x" * 200}, "characters or fewer"),
            ({"api_key": "sk-ant-test", "workspace_label": "workspace-foo"}, "cannot start with"),
            ({"api_key": "sk-ant-test", "workspace_label": 42}, "Workspace label must be a string"),
        ],
    )
    @patch("anthropic.Anthropic")
    def test_create_rejects_invalid_payload(
        self,
        mock_anthropic_class,
        config: dict,
        expected_error_substring: str,
        client: HttpClient,
    ):
        client.force_login(self.user)
        response = client.post(
            f"/api/environments/{self.team.pk}/integrations",
            {"kind": "anthropic", "config": config},
            content_type="application/json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert expected_error_substring in str(response.json())
        assert not Integration.objects.filter(kind="anthropic", team=self.team).exists()
        # Validation never reached the SDK boundary.
        mock_anthropic_class.assert_not_called()

    @pytest.mark.parametrize(
        "error_class_name,expected_error_substring",
        [
            ("AuthenticationError", "Invalid Anthropic API key"),
            ("PermissionDeniedError", "missing required permissions"),
            ("APIConnectionError", "Could not reach Anthropic"),
        ],
    )
    @patch("anthropic.Anthropic")
    def test_create_rejects_anthropic_failures(
        self,
        mock_anthropic_class,
        error_class_name: str,
        expected_error_substring: str,
        client: HttpClient,
    ):
        import anthropic

        error_class = getattr(anthropic, error_class_name)
        mock_client = MagicMock()
        mock_anthropic_class.return_value = mock_client
        if error_class_name == "APIConnectionError":
            mock_client.get.side_effect = error_class(request=MagicMock())
        else:
            mock_client.get.side_effect = error_class(
                message="upstream error",
                response=MagicMock(),
                body=None,
            )

        client.force_login(self.user)
        response = client.post(
            f"/api/environments/{self.team.pk}/integrations",
            {"kind": "anthropic", "config": {"api_key": "sk-ant-bad"}},
            content_type="application/json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert expected_error_substring in str(response.json())
        assert not Integration.objects.filter(kind="anthropic", team=self.team).exists()

    def _make_integration(self, *, integration_id: str = "production") -> Integration:
        return Integration.objects.create(
            team=self.team,
            kind="anthropic",
            integration_id=integration_id,
            config={"workspace_label": integration_id},
            sensitive_config={"api_key": "sk-ant-test"},
            created_by=self.user,
        )

    @patch("anthropic.Anthropic")
    def test_anthropic_managed_agents_action(self, mock_anthropic_class, client: HttpClient):
        from django.core.cache import cache

        cache.clear()
        mock_client = MagicMock()
        mock_anthropic_class.return_value = mock_client
        mock_client.get.return_value = {
            "data": [
                {"id": "agt_1", "name": "Support bot", "version": "v3"},
                {"id": "agt_2", "name": "Sales bot", "version": "v1"},
            ],
            "next_cursor": None,
        }
        integration = self._make_integration()
        client.force_login(self.user)

        response = client.get(
            f"/api/environments/{self.team.pk}/integrations/{integration.id}/anthropic_managed_agents/"
        )

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["agents"] == [
            {"id": "agt_1", "name": "Support bot", "version": "v3"},
            {"id": "agt_2", "name": "Sales bot", "version": "v1"},
        ]
        assert body["has_more"] is False
        assert body["next_cursor"] is None
        path_arg = mock_client.get.call_args.args[0]
        headers = mock_client.get.call_args.kwargs["options"]["headers"]
        assert path_arg == "/v1/agents"
        assert headers["anthropic-beta"] == "managed-agents-2026-04-01"

    @patch("anthropic.Anthropic")
    def test_anthropic_managed_agents_action_caches_default_page(self, mock_anthropic_class, client: HttpClient):
        from django.core.cache import cache

        cache.clear()
        mock_client = MagicMock()
        mock_anthropic_class.return_value = mock_client
        mock_client.get.return_value = {"data": [{"id": "agt_1", "name": "Bot"}], "next_cursor": None}
        integration = self._make_integration()
        client.force_login(self.user)

        url = f"/api/environments/{self.team.pk}/integrations/{integration.id}/anthropic_managed_agents/"
        first = client.get(url)
        second = client.get(url)

        assert first.status_code == status.HTTP_200_OK
        assert second.status_code == status.HTTP_200_OK
        # Second hit served from cache → SDK called only once.
        assert mock_client.get.call_count == 1

    @patch("anthropic.Anthropic")
    def test_anthropic_managed_agents_action_translates_auth_error(self, mock_anthropic_class, client: HttpClient):
        from django.core.cache import cache

        from anthropic import AuthenticationError

        cache.clear()
        mock_client = MagicMock()
        mock_anthropic_class.return_value = mock_client
        mock_client.get.side_effect = AuthenticationError(message="bad key", response=MagicMock(), body=None)
        integration = self._make_integration()
        client.force_login(self.user)

        response = client.get(
            f"/api/environments/{self.team.pk}/integrations/{integration.id}/anthropic_managed_agents/"
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "no longer valid" in str(response.json())
        # Failure is recorded on the integration so the UI can surface "needs reconnect".
        integration.refresh_from_db()
        assert integration.errors == ERROR_TOKEN_REFRESH_FAILED

    @patch("anthropic.Anthropic")
    def test_anthropic_managed_agents_action_rejects_wrong_kind(self, mock_anthropic_class, client: HttpClient):
        slack_integration = Integration.objects.create(
            team=self.team,
            kind="slack",
            integration_id="T123",
            config={"team": {"id": "T123"}},
            sensitive_config={},
            created_by=self.user,
        )
        client.force_login(self.user)

        response = client.get(
            f"/api/environments/{self.team.pk}/integrations/{slack_integration.id}/anthropic_managed_agents/"
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "is not an Anthropic integration" in str(response.json())
        mock_anthropic_class.assert_not_called()

    @patch("anthropic.Anthropic")
    def test_anthropic_managed_agent_environments_action(self, mock_anthropic_class, client: HttpClient):
        from django.core.cache import cache

        cache.clear()
        mock_client = MagicMock()
        mock_anthropic_class.return_value = mock_client
        mock_client.get.return_value = {"data": [{"id": "env_prod", "name": "Production"}], "next_cursor": "abc"}
        integration = self._make_integration()
        client.force_login(self.user)

        response = client.get(
            f"/api/environments/{self.team.pk}/integrations/{integration.id}/anthropic_managed_agent_environments/"
        )

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["environments"] == [{"id": "env_prod", "name": "Production"}]
        assert body["next_cursor"] == "abc"
        assert body["has_more"] is True

    @patch("anthropic.Anthropic")
    def test_anthropic_managed_agent_vaults_action(self, mock_anthropic_class, client: HttpClient):
        from django.core.cache import cache

        cache.clear()
        mock_client = MagicMock()
        mock_anthropic_class.return_value = mock_client
        mock_client.get.return_value = {"data": [{"id": "vault_1", "display_name": "Customer secrets"}]}
        integration = self._make_integration()
        client.force_login(self.user)

        response = client.get(
            f"/api/environments/{self.team.pk}/integrations/{integration.id}/anthropic_managed_agent_vaults/"
        )

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["vaults"] == [{"id": "vault_1", "display_name": "Customer secrets"}]
        assert body["has_more"] is False


class TestSlackPostHogCodeKindDeprecated:
    @pytest.fixture(autouse=True)
    def setup_environment(self, db):
        self.organization = Organization.objects.create(name="Test Org")
        self.team = Team.objects.create(organization=self.organization, name="Test Team")
        self.user = User.objects.create_and_join(
            self.organization, "test@posthog.com", "test", level=OrganizationMembership.Level.ADMIN
        )

    def test_create_slack_posthog_code_integration_rejected(self, client: HttpClient):
        client.force_login(self.user)

        response = client.post(
            f"/api/environments/{self.team.pk}/integrations/",
            {"kind": "slack-posthog-code", "config": {}},
            content_type="application/json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "deprecated" in json.dumps(response.json()).lower()
        assert not Integration.objects.filter(team=self.team, kind="slack-posthog-code").exists()

    def test_validate_kind_rejects_slack_posthog_code(self):
        serializer = IntegrationSerializer(data={"kind": "slack-posthog-code", "config": {}})

        assert not serializer.is_valid()
        assert "kind" in serializer.errors
        assert "deprecated" in str(serializer.errors["kind"]).lower()

    def test_validate_kind_accepts_other_kinds(self):
        # Sanity check — the validator must not reject unrelated kinds.
        serializer = IntegrationSerializer(data={"kind": "slack", "config": {}})

        serializer.is_valid()
        assert "kind" not in serializer.errors


class TestGitHubIntegrationUninstall:
    @pytest.fixture(autouse=True)
    def setup_integration(self, db):
        self.organization = Organization.objects.create(name="Test Org")
        self.team = Team.objects.create(organization=self.organization, name="Test Team")
        self.user = User.objects.create_and_join(
            self.organization, "test@posthog.com", "test", level=OrganizationMembership.Level.ADMIN
        )

    def _create_github_integration(self, installation_id: str = "12345") -> Integration:
        return Integration.objects.create(
            team=self.team,
            kind="github",
            config={"installation_id": installation_id},
            sensitive_config={"access_token": "ghs_token"},
            integration_id=installation_id,
            created_by=self.user,
        )

    @patch("posthog.api.integration.GitHubIntegration.uninstall_app_installation")
    def test_destroy_github_uninstalls_and_cleans_up_personal_when_last_team_reference(
        self, mock_uninstall, client: HttpClient
    ):
        mock_uninstall.return_value = True
        integration = self._create_github_integration("12345")
        personal = UserIntegration.objects.create(
            user=self.user, kind="github", integration_id="12345", config={}, sensitive_config={}
        )

        client.force_login(self.user)
        response = client.delete(f"/api/environments/{self.team.pk}/integrations/{integration.id}/")

        assert response.status_code == status.HTTP_204_NO_CONTENT
        mock_uninstall.assert_called_once_with("12345")
        assert not Integration.objects.filter(id=integration.id).exists()
        # Last team reference removed → the App is uninstalled, so personal integrations go too.
        assert not UserIntegration.objects.filter(id=personal.id).exists()

    @patch("posthog.api.integration.GitHubIntegration.uninstall_app_installation")
    def test_destroy_github_skips_uninstall_when_other_team_reference_exists(self, mock_uninstall, client: HttpClient):
        integration = self._create_github_integration("12345")
        other_team = Team.objects.create(organization=self.organization, name="Other Team")
        Integration.objects.create(
            team=other_team, kind="github", integration_id="12345", config={}, sensitive_config={}
        )
        personal = UserIntegration.objects.create(
            user=self.user, kind="github", integration_id="12345", config={}, sensitive_config={}
        )

        client.force_login(self.user)
        response = client.delete(f"/api/environments/{self.team.pk}/integrations/{integration.id}/")

        assert response.status_code == status.HTTP_204_NO_CONTENT
        mock_uninstall.assert_not_called()
        assert not Integration.objects.filter(id=integration.id).exists()
        # Another team still uses the installation, so it stays installed and personal survives.
        assert UserIntegration.objects.filter(id=personal.id).exists()

    @patch(
        "posthog.api.integration.GitHubIntegration.uninstall_app_installation",
        side_effect=Exception("GitHub API error"),
    )
    def test_destroy_github_still_deletes_when_uninstall_fails(self, _mock_uninstall, client: HttpClient):
        integration = self._create_github_integration("12345")

        client.force_login(self.user)
        response = client.delete(f"/api/environments/{self.team.pk}/integrations/{integration.id}/")

        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert not Integration.objects.filter(id=integration.id).exists()

    @patch("posthog.api.integration.GitHubIntegration.uninstall_app_installation")
    @patch("posthog.api.integration.count_in_progress_runs_for_github_integration")
    def test_destroy_github_blocked_while_background_agent_runs_in_progress(
        self, mock_count, _mock_uninstall, client: HttpClient
    ):
        integration = self._create_github_integration("12345")
        mock_count.return_value = 2

        client.force_login(self.user)
        response = client.delete(f"/api/environments/{self.team.pk}/integrations/{integration.id}/")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "2 in-progress background agent runs" in response.json()["detail"]
        assert Integration.objects.filter(id=integration.id).exists()
        mock_count.assert_called_once_with(team_id=self.team.pk, integration_id=integration.id)

        mock_count.return_value = 0
        response = client.delete(f"/api/environments/{self.team.pk}/integrations/{integration.id}/")

        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert not Integration.objects.filter(id=integration.id).exists()


class TestIntegrationDeletionWorkflowGuard:
    @pytest.fixture(autouse=True)
    def setup_integration(self, db):
        self.organization = Organization.objects.create(name="Test Org")
        self.team = Team.objects.create(organization=self.organization, name="Test Team")
        self.user = User.objects.create_and_join(
            self.organization, "test@posthog.com", "test", level=OrganizationMembership.Level.ADMIN
        )
        self.integration = Integration.objects.create(
            team=self.team,
            kind="email",
            config={"email": "noreply@posthog.com", "name": "Test", "domain": "posthog.com", "verified": True},
            created_by=self.user,
        )

    def _email_actions(self, integration_id: int) -> list[dict]:
        return [
            {"id": "trigger_node", "name": "Trigger", "type": "trigger", "config": {"type": "event", "filters": {}}},
            {
                "id": "action_email_1",
                "name": "Welcome Email",
                "type": "function_email",
                "config": {
                    "inputs": {
                        "email": {
                            "value": {
                                "to": {"email": "{{ person.properties.email }}", "name": ""},
                                "from": {"integrationId": integration_id},
                                "subject": "Welcome!",
                                "html": "",
                                "text": "",
                            }
                        }
                    }
                },
            },
        ]

    def _create_flow(self, status: str = "active", actions: list | None = None) -> HogFlow:
        return HogFlow.objects.create(
            team=self.team,
            name="Welcome Email Sequence",
            status=status,
            actions=actions if actions is not None else self._email_actions(self.integration.id),
            edges=[],
        )

    def _delete(self, client: HttpClient):
        client.force_login(self.user)
        return client.delete(f"/api/environments/{self.team.pk}/integrations/{self.integration.id}/")

    def test_destroy_blocked_when_active_workflow_references_integration(self, client: HttpClient):
        self._create_flow()

        response = self._delete(client)

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "Welcome Email Sequence" in response.content.decode()
        assert Integration.objects.filter(id=self.integration.id).exists()

    @pytest.mark.parametrize("flow_status", ["draft", "archived"])
    def test_destroy_allowed_when_workflow_not_active(self, flow_status: str, client: HttpClient):
        self._create_flow(status=flow_status)

        with patch("posthog.api.integration.EmailIntegration"):
            response = self._delete(client)

        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert not Integration.objects.filter(id=self.integration.id).exists()

    def test_destroy_allowed_when_workflow_references_other_integration(self, client: HttpClient):
        self._create_flow(actions=self._email_actions(self.integration.id + 1))

        with patch("posthog.api.integration.EmailIntegration"):
            response = self._delete(client)

        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert not Integration.objects.filter(id=self.integration.id).exists()

    @pytest.mark.parametrize(
        "reference_kind,template_id",
        [
            # Bare-ID inputs are only identifiable as integrations via the template's inputs_schema
            ("bare_id_via_schema", "template-test-slack"),
            # Dict-form inputs are caught by the recursive config walk, no template needed
            ("dict_value", "template-unknown"),
        ],
    )
    def test_destroy_blocked_when_function_action_references_integration(
        self, reference_kind: str, template_id: str, client: HttpClient
    ):
        input_value: int | dict
        if reference_kind == "bare_id_via_schema":
            HogFunctionTemplate.objects.create(
                template_id=template_id,
                sha="abc123",
                name="Slack",
                code="return event",
                inputs_schema=[{"key": "slack_workspace", "type": "integration", "label": "Slack workspace"}],
                type="destination",
            )
            input_value = self.integration.id
        else:
            input_value = {"integrationId": self.integration.id}
        self._create_flow(
            actions=[
                {
                    "id": "action_function_1",
                    "name": "Notify Slack",
                    "type": "function",
                    "config": {
                        "template_id": template_id,
                        "inputs": {"slack_workspace": {"value": input_value}},
                    },
                },
            ]
        )

        response = self._delete(client)

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert Integration.objects.filter(id=self.integration.id).exists()

    def test_destroy_survives_deeply_nested_action_config(self, client: HttpClient):
        nested: dict = {"integrationId": self.integration.id}
        for _ in range(1500):
            nested = {"_x": nested}
        self._create_flow(
            actions=[{"id": "action_function_1", "name": "Evil", "type": "function", "config": {"inputs": nested}}]
        )

        with patch("posthog.api.integration.EmailIntegration"):
            response = self._delete(client)

        # The reference sits beyond the traversal depth cap: deletion proceeds rather than 500ing
        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert not Integration.objects.filter(id=self.integration.id).exists()

    @pytest.mark.parametrize(
        "action_type,config",
        [
            # Non-function actions don't consume integrations
            ("delay", {"duration": "5m"}),
            # Function actions only consume integrations via config.inputs
            ("function", {"template_id": "template-unknown", "inputs": {}}),
        ],
    )
    def test_destroy_allowed_when_integration_id_in_non_consuming_config(
        self, action_type: str, config: dict, client: HttpClient
    ):
        config = {**config, "integrationId": self.integration.id}
        self._create_flow(actions=[{"id": "action_1", "name": "Planted", "type": action_type, "config": config}])

        with patch("posthog.api.integration.EmailIntegration"):
            response = self._delete(client)

        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert not Integration.objects.filter(id=self.integration.id).exists()


class TestIntegrationDeletionHogFunctionGuard:
    @pytest.fixture(autouse=True)
    def setup_integration(self, db):
        self.organization = Organization.objects.create(name="Test Org")
        self.team = Team.objects.create(organization=self.organization, name="Test Team")
        self.user = User.objects.create_and_join(
            self.organization, "test@posthog.com", "test", level=OrganizationMembership.Level.ADMIN
        )
        self.integration = Integration.objects.create(
            team=self.team,
            kind="slack",
            config={"team": {"id": "T123", "name": "Test workspace"}},
            created_by=self.user,
        )

    def _create_function(
        self,
        *,
        enabled: bool = True,
        deleted: bool = False,
        input_value: int | dict | None = None,
        input_type: str = "integration",
        name: str = "Slack notifier",
    ) -> HogFunction:
        return HogFunction.objects.create(
            team=self.team,
            name=name,
            type="destination",
            hog="return event",
            enabled=enabled,
            deleted=deleted,
            inputs_schema=[{"key": "slack_workspace", "type": input_type, "label": "Slack workspace"}],
            inputs={
                "slack_workspace": {"value": input_value if input_value is not None else self.integration.id},
            },
        )

    def _delete(self, client: HttpClient):
        client.force_login(self.user)
        return client.delete(f"/api/environments/{self.team.pk}/integrations/{self.integration.id}/")

    @pytest.mark.parametrize("value_form", ["bare_id", "dict_value"])
    def test_destroy_blocked_when_enabled_function_references_integration(self, value_form: str, client: HttpClient):
        input_value: int | dict = (
            self.integration.id if value_form == "bare_id" else {"integrationId": self.integration.id}
        )
        self._create_function(input_value=input_value)

        response = self._delete(client)

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "Slack notifier" in response.content.decode()
        assert Integration.objects.filter(id=self.integration.id).exists()

    @pytest.mark.parametrize("enabled,deleted", [(False, False), (True, True)])
    def test_destroy_allowed_when_function_disabled_or_deleted(self, enabled: bool, deleted: bool, client: HttpClient):
        self._create_function(enabled=enabled, deleted=deleted)

        response = self._delete(client)

        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert not Integration.objects.filter(id=self.integration.id).exists()

    def test_destroy_allowed_when_function_references_other_integration(self, client: HttpClient):
        self._create_function(input_value=self.integration.id + 1)

        response = self._delete(client)

        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert not Integration.objects.filter(id=self.integration.id).exists()

    @pytest.mark.parametrize("input_type,value_form", [("string", "bare_id"), ("json", "dict_value")])
    def test_destroy_allowed_when_integration_id_in_non_integration_input(
        self, input_type: str, value_form: str, client: HttpClient
    ):
        # A matching ID in an input the runtime never resolves as an integration must not block deletion
        input_value: int | dict = (
            self.integration.id if value_form == "bare_id" else {"integrationId": self.integration.id}
        )
        self._create_function(input_type=input_type, input_value=input_value)

        response = self._delete(client)

        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert not Integration.objects.filter(id=self.integration.id).exists()

    def test_destroy_blocked_message_includes_workflows_and_functions(self, client: HttpClient):
        self._create_function(name="Slack notifier")
        HogFlow.objects.create(
            team=self.team,
            name="Slack flow",
            status="active",
            actions=[
                {
                    "id": "action_function_1",
                    "name": "Notify",
                    "type": "function",
                    "config": {"inputs": {"slack_workspace": {"value": {"integrationId": self.integration.id}}}},
                }
            ],
            edges=[],
        )

        response = self._delete(client)

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        content = response.content.decode()
        assert "Slack flow" in content
        assert "Slack notifier" in content
        assert Integration.objects.filter(id=self.integration.id).exists()


class TestIntegrationRequestAccessAPI(APIBaseTest):
    def setUp(self):
        super().setUp()
        # The endpoint is members-only, so default the requester to a plain member.
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()

    def _url(self) -> str:
        return f"/api/projects/{self.team.id}/integrations/request_access/"

    @patch("posthog.api.integration.report_user_action")
    @patch("posthog.api.integration.send_integration_access_request")
    def test_member_can_request_access(self, mock_task, mock_report):
        response = self.client.post(self._url(), {"kind": "slack", "reason": "We need Slack alerts"}, format="json")

        assert response.status_code == status.HTTP_200_OK, response.content
        assert response.json() == {"success": True}
        mock_task.delay.assert_called_once_with(
            team_id=self.team.id,
            requesting_user_id=self.user.id,
            kind="slack",
            reason="We need Slack alerts",
        )
        mock_report.assert_called_once_with(
            self.user,
            "integration access requested",
            {
                "integration_kind": "slack",
                "requester_level": OrganizationMembership.Level.MEMBER,
                "reason_length": len("We need Slack alerts"),
            },
            team=self.team,
        )

    @parameterized.expand(
        [
            ("admin", OrganizationMembership.Level.ADMIN),
            ("owner", OrganizationMembership.Level.OWNER),
        ]
    )
    @patch("posthog.api.integration.report_user_action")
    @patch("posthog.api.integration.send_integration_access_request")
    def test_admins_cannot_request_access(self, _name, level, mock_task, mock_report):
        self.organization_membership.level = level
        self.organization_membership.save()

        response = self.client.post(
            self._url(), {"kind": "github", "reason": "Link issues from error tracking"}, format="json"
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN, response.content
        mock_task.delay.assert_not_called()
        mock_report.assert_not_called()

    @parameterized.expand(
        [
            ("missing_reason", {"kind": "slack"}),
            ("blank_reason", {"kind": "slack", "reason": "   "}),
            ("missing_kind", {"reason": "We need it"}),
            ("invalid_kind", {"kind": "not-a-real-kind", "reason": "We need it"}),
        ]
    )
    @patch("posthog.api.integration.report_user_action")
    @patch("posthog.api.integration.send_integration_access_request")
    def test_invalid_payload_is_rejected(self, _name, payload, mock_task, mock_report):
        response = self.client.post(self._url(), payload, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
        mock_task.delay.assert_not_called()
        mock_report.assert_not_called()


class TestIntegrationMembershipPermissions(APIBaseTest):
    def setUp(self):
        super().setUp()
        # A plain project member: allowed to add integrations, but not edit or remove them.
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()

    @patch("posthog.models.integration.AwsS3Integration.validate_credentials", return_value="123456789012")
    def test_member_can_create_integration(self, _mock_validate):
        response = self.client.post(
            f"/api/environments/{self.team.pk}/integrations",
            {
                "kind": "aws-s3",
                "config": {"name": "prod-aws", "aws_access_key_id": "AKIAEXAMPLE", "aws_secret_access_key": "secret"},
            },
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED, response.content
        assert Integration.objects.filter(id=response.json()["id"], team=self.team).exists()

    def test_member_cannot_delete_integration(self):
        integration = Integration.objects.create(team=self.team, kind="slack", integration_id="T123", config={})

        response = self.client.delete(f"/api/environments/{self.team.pk}/integrations/{integration.id}/")

        assert response.status_code == status.HTTP_403_FORBIDDEN, response.content
        assert Integration.objects.filter(id=integration.id).exists()

    def test_member_cannot_overwrite_existing_integration(self):
        # POST is an upsert (update_or_create keyed on team/kind/integration_id), so re-submitting the
        # same resource edits an existing integration. Members may add a new one, but overwriting an
        # existing one is an edit and requires admin — the write must roll back, leaving config intact.
        email = "svc@proj.iam.gserviceaccount.com"
        existing = Integration.objects.create(
            team=self.team,
            kind="google-cloud-service-account",
            integration_id=f"{email}-{self.team.pk}-key-file",
            config={"project_id": "original-project", "service_account_email": email},
            sensitive_config={"private_key": "orig", "private_key_id": "orig", "token_uri": "orig"},
        )

        response = self.client.post(
            f"/api/environments/{self.team.pk}/integrations",
            {
                "kind": "google-cloud-service-account",
                "config": {
                    "service_account_email": email,
                    "project_id": "hijacked-project",
                    "private_key": "new",
                    "private_key_id": "new",
                    "token_uri": "new",
                },
            },
            format="json",
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN, response.content
        existing.refresh_from_db()
        assert existing.config["project_id"] == "original-project"
        assert Integration.objects.filter(team=self.team, kind="google-cloud-service-account").count() == 1
