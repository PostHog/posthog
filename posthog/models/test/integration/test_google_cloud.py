"""Tests for the Google Cloud service-account and Pub/Sub / Cloud Storage integrations."""

import time
from datetime import datetime
from typing import Optional

import pytest
from freezegun import freeze_time
from posthog.test.base import BaseTest
from unittest.mock import patch

from rest_framework.exceptions import ValidationError

from posthog.models.integration import GoogleCloudIntegration, GoogleCloudServiceAccountIntegration, Integration
from posthog.models.organization import Organization
from posthog.models.team.team import Team


class TestGoogleCloudIntegrationModel(BaseTest):
    mock_keyfile = {
        "type": "service_account",
        "project_id": "posthog-616",
        "private_key_id": "df3e129a722a865cc3539b4e69507bad",
        "private_key": "-----BEGIN PRIVATE KEY-----\nTHISISTHEKEY==\n-----END PRIVATE KEY-----\n",
        "client_email": "hog-pubsub-test@posthog-301601.iam.gserviceaccount.com",
        "client_id": "11223344556677889900",
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
        "client_x509_cert_url": "https://www.googleapis.com/robot/v1/metadata/x509/not-a-topic%40posthog-616.iam.gserviceaccount.com",
        "universe_domain": "googleapis.com",
    }

    def create_integration(
        self, kind: str, config: Optional[dict] = None, sensitive_config: Optional[dict] = None
    ) -> Integration:
        _config = {"refreshed_at": int(time.time()), "expires_in": 3600}
        _sensitive_config = self.mock_keyfile
        _config.update(config or {})
        _sensitive_config.update(sensitive_config or {})

        return Integration.objects.create(team=self.team, kind=kind, config=_config, sensitive_config=_sensitive_config)

    @patch("google.oauth2.service_account.Credentials.from_service_account_info")
    def test_integration_from_key(self, mock_credentials):
        mock_credentials.return_value.project_id = "posthog-616"
        mock_credentials.return_value.service_account_email = "posthog@"
        mock_credentials.return_value.token = "ACCESS_TOKEN"
        mock_credentials.return_value.expiry = datetime.fromtimestamp(1704110400 + 3600)
        mock_credentials.return_value.refresh = lambda _: None

        with freeze_time("2024-01-01T12:00:00Z"):
            integration = GoogleCloudIntegration.integration_from_key(
                "google-pubsub",
                self.mock_keyfile,
                self.team.id,
                self.user,
            )

        assert integration.team == self.team
        assert integration.created_by == self.user

        assert integration.config == {
            "refreshed_at": 1704110400,
            "expires_in": 3600,
        }
        assert integration.sensitive_config == {
            "key_info": self.mock_keyfile,
            "access_token": "ACCESS_TOKEN",
        }

    @patch("google.oauth2.service_account.Credentials.from_service_account_info")
    def test_integration_refresh_token(self, mock_credentials):
        mock_credentials.return_value.project_id = "posthog-616"
        mock_credentials.return_value.service_account_email = "posthog@"
        mock_credentials.return_value.token = "ACCESS_TOKEN"
        mock_credentials.return_value.expiry = datetime.fromtimestamp(1704110400 + 3600)
        mock_credentials.return_value.refresh = lambda _: None

        with freeze_time("2024-01-01T12:00:00Z"):
            integration = GoogleCloudIntegration.integration_from_key(
                "google-pubsub",
                self.mock_keyfile,
                self.team.id,
                self.user,
            )

        with freeze_time("2024-01-01T12:00:00Z"):
            assert GoogleCloudIntegration(integration).access_token_expired() is False

        with freeze_time("2024-01-01T14:00:00Z"):
            assert GoogleCloudIntegration(integration).access_token_expired() is True

            mock_credentials.return_value.expiry = datetime.fromtimestamp(1704110400 + 3600 * 3)

            GoogleCloudIntegration(integration).refresh_access_token()
            assert GoogleCloudIntegration(integration).access_token_expired() is False

        assert integration.config == {
            "refreshed_at": 1704110400 + 3600 * 2,
            "expires_in": 3600,
        }
        assert integration.sensitive_config["access_token"] == "ACCESS_TOKEN"

        # Verify refresh used the nested key_info, not the whole sensitive_config
        refresh_call = mock_credentials.call_args_list[-1]
        assert refresh_call[0][0] == self.mock_keyfile

    @patch("google.oauth2.service_account.Credentials.from_service_account_info")
    def test_refresh_token_fallback_pre_migration_sensitive_config(self, mock_credentials):
        """Pre-migration integrations store key_info directly in sensitive_config (not nested under 'key_info').
        The refresh logic should fall back to using the entire sensitive_config as key_info."""
        mock_credentials.return_value.project_id = "posthog-616"
        mock_credentials.return_value.service_account_email = "posthog@"
        mock_credentials.return_value.token = "REFRESHED_TOKEN"
        mock_credentials.return_value.expiry = datetime.fromtimestamp(1704110400 + 3600)
        mock_credentials.return_value.refresh = lambda _: None

        # Simulate pre-migration state: key_info stored directly as sensitive_config,
        # access_token in config
        integration = Integration.objects.create(
            team=self.team,
            kind="google-pubsub",
            integration_id="posthog@",
            config={
                "refreshed_at": 1704110400,
                "expires_in": 1,
                "access_token": "OLD_TOKEN",
            },
            sensitive_config=self.mock_keyfile,
        )

        with freeze_time("2024-01-01T14:00:00Z"):
            GoogleCloudIntegration(integration).refresh_access_token()

        # After refresh, sensitive_config should be migrated to the nested structure
        assert integration.sensitive_config == {
            "key_info": self.mock_keyfile,
            "access_token": "REFRESHED_TOKEN",
        }
        assert "access_token" not in integration.config

        # Verify refresh used the whole sensitive_config as key_info (pre-migration fallback)
        assert mock_credentials.call_args[0][0] == self.mock_keyfile

    @patch("google.oauth2.service_account.Credentials.from_service_account_info")
    def test_get_access_token_reads_from_sensitive_config(self, mock_credentials):
        mock_credentials.return_value.project_id = "posthog-616"
        mock_credentials.return_value.service_account_email = "posthog@"
        mock_credentials.return_value.token = "ACCESS_TOKEN"
        mock_credentials.return_value.expiry = datetime.fromtimestamp(1704110400 + 3600)
        mock_credentials.return_value.refresh = lambda _: None

        with freeze_time("2024-01-01T12:00:00Z"):
            integration = GoogleCloudIntegration.integration_from_key(
                "google-pubsub",
                self.mock_keyfile,
                self.team.id,
                self.user,
            )

        with freeze_time("2024-01-01T12:00:00Z"):
            token = GoogleCloudIntegration(integration).get_access_token()

        assert token == "ACCESS_TOKEN"
        assert "access_token" not in integration.config


class TestGoogleCloudServiceAccountIntegration(BaseTest):
    def test_raises_on_duplicate_service_account_email(self):
        _ = GoogleCloudServiceAccountIntegration.integration_from_service_account(
            team_id=self.team.pk,
            organization_id=str(self.team.organization.id),
            service_account_email="test@test.iam.gserviceaccount.com",
            project_id="test",
        )
        with pytest.raises(ValidationError):
            _ = GoogleCloudServiceAccountIntegration.integration_from_service_account(
                team_id=self.team.pk + 1,
                organization_id="a-different-org",
                service_account_email="test@test.iam.gserviceaccount.com",
                project_id="test",
            )

    def test_allows_duplicate_service_account_email_when_using_key(self):
        key_file_integration = GoogleCloudServiceAccountIntegration.integration_from_service_account(
            team_id=self.team.pk,
            organization_id=str(self.team.organization.id),
            service_account_email="test@test.iam.gserviceaccount.com",
            project_id="test",
            private_key="something",
            private_key_id="something",
            token_uri="something",
        )

        other_org = Organization.objects.create(name="other org")
        other_team = Team.objects.create(organization=other_org, name="other team")
        new_impersonated_integration = GoogleCloudServiceAccountIntegration.integration_from_service_account(
            team_id=other_team.id,
            organization_id=other_org.id,
            service_account_email="test@test.iam.gserviceaccount.com",
            project_id="test",
        )

        new_key_file_integration = GoogleCloudServiceAccountIntegration.integration_from_service_account(
            team_id=other_team.pk,
            organization_id=other_org.id,
            service_account_email="test@test.iam.gserviceaccount.com",
            project_id="test",
            private_key="something",
            private_key_id="something",
            token_uri="something",
        )

        assert (
            GoogleCloudServiceAccountIntegration(key_file_integration).service_account_email
            == GoogleCloudServiceAccountIntegration(new_impersonated_integration).service_account_email
            == GoogleCloudServiceAccountIntegration(new_key_file_integration).service_account_email
        )
