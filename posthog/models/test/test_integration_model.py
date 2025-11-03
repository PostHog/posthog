import time
import socket
from datetime import UTC, datetime, timedelta
from typing import Optional

import pytest
from freezegun import freeze_time
from posthog.test.base import BaseTest, override_settings
from unittest.mock import MagicMock, patch

from django.db import connection

from disposable_email_domains import blocklist as disposable_email_domains_list
from rest_framework.exceptions import ValidationError

from posthog.models.instance_setting import set_instance_setting
from posthog.models.integration import (
    DatabricksIntegration,
    DatabricksIntegrationError,
    EmailIntegration,
    GitHubIntegration,
    GoogleCloudIntegration,
    Integration,
    OauthIntegration,
    SlackIntegration,
)
from posthog.models.team.team import Team


def get_db_field_value(field, model_id):
    cursor = connection.cursor()
    cursor.execute(f"select {field} from posthog_integration where id='{model_id}';")
    return cursor.fetchone()[0]


def update_db_field_value(field, model_id, value):
    cursor = connection.cursor()
    cursor.execute(f"update posthog_integration set {field}='{value}' where id='{model_id}';")


class TestIntegrationModel(BaseTest):
    def create_integration(
        self, kind: str, config: Optional[dict] = None, sensitive_config: Optional[dict] = None
    ) -> Integration:
        _config = {"refreshed_at": int(time.time()), "expires_in": 3600}
        _sensitive_config = {"refresh_token": "REFRESH", "id_token": None}
        _config.update(config or {})
        _sensitive_config.update(sensitive_config or {})

        return Integration.objects.create(team=self.team, kind=kind, config=_config, sensitive_config=_sensitive_config)

    def test_sensitive_config_encrypted(self):
        # Fernet encryption is deterministic, but has a temporal component and utilizes os.urandom() for the IV
        with freeze_time("2024-01-01T00:01:00Z"):
            with patch("os.urandom", return_value=b"\x00" * 16):
                integration = self.create_integration("slack")

                assert integration.sensitive_config == {"refresh_token": "REFRESH", "id_token": None}
                assert (
                    get_db_field_value("sensitive_config", integration.id)
                    == '{"id_token": null, "refresh_token": "gAAAAABlkgC8AAAAAAAAAAAAAAAAAAAAAJgmFh-MNX9haUNHNfYLvULI6vSRYVd3o8xd4f8xBkWEWAa5RJ2ikOM2dsW5_9F7Mw=="}'
                )

                # update the value to non-encrypted and check it still loads

                update_db_field_value(
                    "sensitive_config", integration.id, '{"id_token": null, "refresh_token": "REFRESH2"}'
                )
                integration.refresh_from_db()
                assert integration.sensitive_config == {"id_token": None, "refresh_token": "REFRESH2"}
                assert (
                    get_db_field_value("sensitive_config", integration.id)
                    == '{"id_token": null, "refresh_token": "REFRESH2"}'
                )

                integration.save()
                # The field should now be encrypted
                assert integration.sensitive_config == {"id_token": None, "refresh_token": "REFRESH2"}
                assert (
                    get_db_field_value("sensitive_config", integration.id)
                    == '{"id_token": null, "refresh_token": "gAAAAABlkgC8AAAAAAAAAAAAAAAAAAAAAHlWz9QOMnXDvmix-z5lNG4v0VcO9lGWejmcE_BXHXPZ1wNkb-38JupntWbshBrfFQ=="}'
                )

    def test_slack_integration_config(self):
        set_instance_setting("SLACK_APP_CLIENT_ID", None)
        set_instance_setting("SLACK_APP_CLIENT_SECRET", None)
        set_instance_setting("SLACK_APP_SIGNING_SECRET", None)

        assert not SlackIntegration.slack_config() == {}

        set_instance_setting("SLACK_APP_CLIENT_ID", "client-id")
        set_instance_setting("SLACK_APP_CLIENT_SECRET", "client-secret")
        set_instance_setting("SLACK_APP_SIGNING_SECRET", "not-so-secret")

        assert SlackIntegration.slack_config() == {
            "SLACK_APP_CLIENT_ID": "client-id",
            "SLACK_APP_CLIENT_SECRET": "client-secret",
            "SLACK_APP_SIGNING_SECRET": "not-so-secret",
        }


class TestOauthIntegrationModel(BaseTest):
    mock_settings = {
        "SALESFORCE_CONSUMER_KEY": "salesforce-client-id",
        "SALESFORCE_CONSUMER_SECRET": "salesforce-client-secret",
        "HUBSPOT_APP_CLIENT_ID": "hubspot-client-id",
        "HUBSPOT_APP_CLIENT_SECRET": "hubspot-client-secret",
        "GOOGLE_ADS_APP_CLIENT_ID": "google-client-id",
        "GOOGLE_ADS_APP_CLIENT_SECRET": "google-client-secret",
    }

    def create_integration(
        self, kind: str, config: Optional[dict] = None, sensitive_config: Optional[dict] = None
    ) -> Integration:
        _config = {"refreshed_at": int(time.time()), "expires_in": 3600}
        _sensitive_config = {"refresh_token": "REFRESH"}
        _config.update(config or {})
        _sensitive_config.update(sensitive_config or {})

        return Integration.objects.create(team=self.team, kind=kind, config=_config, sensitive_config=_sensitive_config)

    def test_authorize_url_raises_if_not_configured(self):
        with pytest.raises(NotImplementedError):
            OauthIntegration.authorize_url("salesforce", token="state_token", next="/projects/test")

    def test_authorize_url(self):
        with self.settings(**self.mock_settings):
            url = OauthIntegration.authorize_url("salesforce", token="state_token", next="/projects/test")
            assert (
                url
                == "https://login.salesforce.com/services/oauth2/authorize?client_id=salesforce-client-id&scope=full+refresh_token&redirect_uri=https%3A%2F%2Flocalhost%3A8010%2Fintegrations%2Fsalesforce%2Fcallback&response_type=code&state=next%3D%252Fprojects%252Ftest%26token%3Dstate_token"
            )

    def test_authorize_url_with_additional_authorize_params(self):
        with self.settings(**self.mock_settings):
            url = OauthIntegration.authorize_url("google-ads", token="state_token", next="/projects/test")
            assert (
                url
                == "https://accounts.google.com/o/oauth2/v2/auth?client_id=google-client-id&scope=https%3A%2F%2Fwww.googleapis.com%2Fauth%2Fadwords+https%3A%2F%2Fwww.googleapis.com%2Fauth%2Fuserinfo.email&redirect_uri=https%3A%2F%2Flocalhost%3A8010%2Fintegrations%2Fgoogle-ads%2Fcallback&response_type=code&state=next%3D%252Fprojects%252Ftest%26token%3Dstate_token&access_type=offline&prompt=consent"
            )

    @patch("posthog.models.integration.requests.post")
    def test_integration_from_oauth_response(self, mock_post):
        with self.settings(**self.mock_settings):
            mock_post.return_value.status_code = 200
            mock_post.return_value.json.return_value = {
                "access_token": "FAKES_ACCESS_TOKEN",
                "refresh_token": "FAKE_REFRESH_TOKEN",
                "instance_url": "https://fake.salesforce.com",
                "expires_in": 3600,
            }

            with freeze_time("2024-01-01T12:00:00Z"):
                integration = OauthIntegration.integration_from_oauth_response(
                    "salesforce",
                    self.team.id,
                    self.user,
                    {
                        "code": "code",
                        "state": "next=/projects/test",
                    },
                )

            assert integration.team == self.team
            assert integration.created_by == self.user

            assert integration.config == {
                "instance_url": "https://fake.salesforce.com",
                "refreshed_at": 1704110400,
                "expires_in": 3600,
            }
            assert integration.sensitive_config == {
                "access_token": "FAKES_ACCESS_TOKEN",
                "refresh_token": "FAKE_REFRESH_TOKEN",
                "id_token": None,
            }

    @patch("posthog.models.integration.requests.post")
    def test_integration_errors_if_id_cannot_be_generated(self, mock_post):
        with self.settings(**self.mock_settings):
            mock_post.return_value.status_code = 200
            mock_post.return_value.json.return_value = {
                "access_token": "FAKES_ACCESS_TOKEN",
                "refresh_token": "FAKE_REFRESH_TOKEN",
                "not_instance_url": "https://fake.salesforce.com",
                "expires_in": 3600,
            }

            with pytest.raises(Exception):
                OauthIntegration.integration_from_oauth_response(
                    "salesforce",
                    self.team.id,
                    self.user,
                    {
                        "code": "code",
                        "state": "next=/projects/test",
                    },
                )

    @patch("posthog.models.integration.requests.post")
    @patch("posthog.models.integration.requests.get")
    def test_integration_fetches_info_from_token_info_url(self, mock_get, mock_post):
        with self.settings(**self.mock_settings):
            mock_post.return_value.status_code = 200
            mock_post.return_value.json.return_value = {
                "access_token": "FAKES_ACCESS_TOKEN",
                "refresh_token": "FAKE_REFRESH_TOKEN",
                "expires_in": 3600,
            }

            mock_get.return_value.status_code = 200
            mock_get.return_value.json.return_value = {
                "hub_id": "hub_id",
                "hub_domain": "hub_domain",
                "user": "user",
                "user_id": "user_id",
                "should_not": "be_saved",
                "scopes": [
                    "crm.objects.contacts.read",
                    "crm.objects.contacts.write",
                ],
            }

            with freeze_time("2024-01-01T12:00:00Z"):
                integration = OauthIntegration.integration_from_oauth_response(
                    "hubspot",
                    self.team.id,
                    self.user,
                    {
                        "code": "code",
                        "state": "next=/projects/test",
                    },
                )

            assert integration.config == {
                "expires_in": 3600,
                "hub_id": "hub_id",
                "hub_domain": "hub_domain",
                "user": "user",
                "user_id": "user_id",
                "refreshed_at": 1704110400,
                "scopes": [
                    "crm.objects.contacts.read",
                    "crm.objects.contacts.write",
                ],
            }
            assert integration.sensitive_config == {
                "access_token": "FAKES_ACCESS_TOKEN",
                "refresh_token": "FAKE_REFRESH_TOKEN",
                "id_token": None,
            }

    def test_integration_access_token_expired(self):
        now = datetime.now()
        with freeze_time(now):
            integration = self.create_integration(kind="hubspot", config={"expires_in": 1000})

        with freeze_time(now):
            # Access token is not expired
            assert not OauthIntegration(integration).access_token_expired()

        with freeze_time(now + timedelta(seconds=1000) - timedelta(seconds=501)):
            # After the expiry but before the threshold it is not expired
            assert not OauthIntegration(integration).access_token_expired()

        with freeze_time(now + timedelta(seconds=1000) - timedelta(seconds=499)):
            # After the threshold it is expired
            assert OauthIntegration(integration).access_token_expired()

        with freeze_time(now + timedelta(seconds=1000)):
            # After the threshold it is expired
            assert OauthIntegration(integration).access_token_expired()

    @patch("posthog.models.integration.reload_integrations_on_workers")
    @patch("posthog.models.integration.requests.post")
    def test_refresh_access_token(self, mock_post, mock_reload):
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {
            "access_token": "REFRESHED_ACCESS_TOKEN",
            "expires_in": 1000,
        }

        integration = self.create_integration(kind="hubspot", config={"expires_in": 1000})

        with freeze_time("2024-01-01T14:00:00Z"):
            with self.settings(**self.mock_settings):
                OauthIntegration(integration).refresh_access_token()

        mock_post.assert_called_with(
            "https://api.hubapi.com/oauth/v1/token",
            data={
                "grant_type": "refresh_token",
                "client_id": "hubspot-client-id",
                "client_secret": "hubspot-client-secret",
                "refresh_token": "REFRESH",
            },
        )

        assert integration.config["expires_in"] == 1000
        assert integration.config["refreshed_at"] == 1704117600
        assert integration.sensitive_config["access_token"] == "REFRESHED_ACCESS_TOKEN"

        mock_reload.assert_called_once_with(self.team.id, [integration.id])

    @patch("posthog.models.integration.reload_integrations_on_workers")
    @patch("posthog.models.integration.requests.post")
    def test_refresh_access_token_handles_errors(self, mock_post, mock_reload):
        mock_post.return_value.status_code = 401
        mock_post.return_value.json.return_value = {"error": "BROKEN"}

        integration = self.create_integration(kind="hubspot", config={"expires_in": 1000, "refreshed_at": 1700000000})

        with freeze_time("2024-01-01T14:00:00Z"):
            with self.settings(**self.mock_settings):
                OauthIntegration(integration).refresh_access_token()

        assert integration.config["expires_in"] == 1000
        assert integration.config["refreshed_at"] == 1700000000
        assert integration.errors == "TOKEN_REFRESH_FAILED"

        mock_reload.assert_not_called()

    @patch("posthog.models.integration.reload_integrations_on_workers")
    @patch("posthog.models.integration.requests.post")
    def test_refresh_access_token_resets_errors(self, mock_post, mock_reload):
        """Test that errors field is reset to empty string after successful refresh_access_token"""
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {
            "access_token": "REFRESHED_ACCESS_TOKEN",
            "expires_in": 1000,
        }

        integration = self.create_integration(kind="hubspot", config={"expires_in": 1000})
        integration.errors = "TOKEN_REFRESH_FAILED"
        integration.save()

        with freeze_time("2024-01-01T14:00:00Z"):
            with self.settings(**self.mock_settings):
                OauthIntegration(integration).refresh_access_token()

        integration.refresh_from_db()
        assert integration.errors == ""

    @patch("posthog.models.integration.requests.post")
    def test_salesforce_integration_without_expires_in_initial_response(self, mock_post):
        """Test that Salesforce integrations without expires_in get default 1 hour expiry"""
        with self.settings(**self.mock_settings):
            mock_post.return_value.status_code = 200
            mock_post.return_value.json.return_value = {
                "access_token": "FAKES_ACCESS_TOKEN",
                "refresh_token": "FAKE_REFRESH_TOKEN",
                "instance_url": "https://fake.salesforce.com",
                # Note: no expires_in field
            }

            with freeze_time("2024-01-01T12:00:00Z"):
                integration = OauthIntegration.integration_from_oauth_response(
                    "salesforce",
                    self.team.id,
                    self.user,
                    {
                        "code": "code",
                        "state": "next=/projects/test",
                    },
                )

            # Should have default 1 hour (3600 seconds) expiry
            assert integration.config["expires_in"] == 3600
            assert integration.config["refreshed_at"] == 1704110400

    def test_salesforce_access_token_expired_without_expires_in(self):
        """Test that Salesforce tokens without expires_in info use 1 hour default"""
        now = datetime.now()
        with freeze_time(now):
            # Create integration without expires_in
            integration = self.create_integration(
                kind="salesforce",
                config={"refreshed_at": int(time.time())},  # No expires_in
                sensitive_config={"refresh_token": "REFRESH"},
            )

        oauth_integration = OauthIntegration(integration)

        with freeze_time(now):
            # Token should not be expired initially
            assert not oauth_integration.access_token_expired()

        with freeze_time(now + timedelta(minutes=29)):
            # Should not be expired before 30 minutes (half of 1 hour default)
            assert not oauth_integration.access_token_expired()

        with freeze_time(now + timedelta(minutes=31)):
            # Should be expired after 30 minutes (halfway point of 1 hour)
            assert oauth_integration.access_token_expired()

    def test_non_salesforce_access_token_expired_without_expires_in(self):
        """Test that non-Salesforce integrations without expires_in return False"""
        now = datetime.now()
        with freeze_time(now):
            # Create non-Salesforce integration without expires_in - override the default
            integration = Integration.objects.create(
                team=self.team,
                kind="hubspot",
                config={"refreshed_at": int(time.time())},  # No expires_in
                sensitive_config={"refresh_token": "REFRESH"},
            )

        oauth_integration = OauthIntegration(integration)

        with freeze_time(now + timedelta(hours=5)):
            # Should never expire without expires_in for non-Salesforce
            assert not oauth_integration.access_token_expired()

    @patch("posthog.models.integration.reload_integrations_on_workers")
    @patch("posthog.models.integration.requests.post")
    def test_salesforce_refresh_access_token_without_expires_in_response(self, mock_post, mock_reload):
        """Test that Salesforce refresh without expires_in in response gets 1 hour default"""
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {
            "access_token": "REFRESHED_ACCESS_TOKEN",
            # Note: no expires_in field in refresh response
        }

        integration = self.create_integration(kind="salesforce", config={"expires_in": 1000})

        with freeze_time("2024-01-01T14:00:00Z"):
            with self.settings(**self.mock_settings):
                OauthIntegration(integration).refresh_access_token()

        # Should have default 1 hour (3600 seconds) expiry
        assert integration.config["expires_in"] == 3600
        assert integration.config["refreshed_at"] == 1704117600
        assert integration.sensitive_config["access_token"] == "REFRESHED_ACCESS_TOKEN"

        mock_reload.assert_called_once_with(self.team.id, [integration.id])

    @patch("posthog.models.integration.reload_integrations_on_workers")
    @patch("posthog.models.integration.requests.post")
    def test_non_salesforce_refresh_access_token_preserves_none_expires_in(self, mock_post, mock_reload):
        """Test that non-Salesforce integrations preserve None expires_in from refresh response"""
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {
            "access_token": "REFRESHED_ACCESS_TOKEN",
            # Note: no expires_in field in refresh response
        }

        integration = self.create_integration(kind="hubspot", config={"expires_in": 1000})

        with freeze_time("2024-01-01T14:00:00Z"):
            with self.settings(**self.mock_settings):
                OauthIntegration(integration).refresh_access_token()

        # Should preserve None for non-Salesforce
        assert integration.config["expires_in"] is None
        assert integration.config["refreshed_at"] == 1704117600
        assert integration.sensitive_config["access_token"] == "REFRESHED_ACCESS_TOKEN"

        mock_reload.assert_called_once_with(self.team.id, [integration.id])


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
            "access_token": "ACCESS_TOKEN",
            "refreshed_at": 1704110400,
            "expires_in": 3600,
        }
        assert integration.sensitive_config == self.mock_keyfile

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
            "access_token": "ACCESS_TOKEN",
            "refreshed_at": 1704110400 + 3600 * 2,
            "expires_in": 3600,
        }


class TestGitHubIntegrationModel(BaseTest):
    def _mock_github_client_request(
        self, status_code=201, token="ACCESS_TOKEN", repository_selection="all", expires_in_hours=1, error_text=None
    ):
        def _client_request(endpoint, method="GET"):
            mock_response = MagicMock()
            if method == "POST":
                mock_response.status_code = status_code
                if status_code == 201:
                    dt = datetime.now(UTC) + timedelta(hours=expires_in_hours)
                    iso_time = dt.replace(tzinfo=None).isoformat(timespec="seconds") + "Z"
                    mock_response.json.return_value = {
                        "token": token,
                        "repository_selection": repository_selection,
                        "expires_at": iso_time,
                    }
                else:
                    mock_response.text = error_text or "error"
                    mock_response.json.return_value = {}
            else:
                mock_response.status_code = 200
                mock_response.json.return_value = {"account": {"type": "Organization", "login": "PostHog"}}
            return mock_response

        return _client_request

    @patch("posthog.models.integration.GitHubIntegration.client_request")
    def test_github_integration_refresh_token(self, mock_client_request):
        mock_client_request.side_effect = self._mock_github_client_request(status_code=201)

        with freeze_time("2024-01-01T12:00:00Z"):
            integration = GitHubIntegration.integration_from_installation_id(
                "INSTALLATION_ID",
                self.team.id,
                self.user,
            )

            assert GitHubIntegration(integration).access_token_expired() is False

        with freeze_time("2024-01-01T14:00:00Z"):
            assert GitHubIntegration(integration).access_token_expired() is True

            GitHubIntegration(integration).refresh_access_token()
            assert GitHubIntegration(integration).access_token_expired() is False

        assert integration.config == {
            "installation_id": "INSTALLATION_ID",
            "account": {
                "name": "PostHog",
                "type": "Organization",
            },
            "repository_selection": "all",
            "refreshed_at": 1704117600,
            "expires_in": 3600,
        }

        assert integration.sensitive_config == {
            "access_token": "ACCESS_TOKEN",
        }

    @patch("posthog.models.integration.reload_integrations_on_workers")
    @patch("posthog.models.integration.GitHubIntegration.client_request")
    def test_github_refresh_access_token_handles_errors(self, mock_client_request, mock_reload):
        """Test that errors field is set if refresh_access_token fails"""
        mock_client_request.side_effect = self._mock_github_client_request(status_code=400, error_text="error")

        with freeze_time("2024-01-01T12:00:00Z"):
            integration = GitHubIntegration.integration_from_installation_id(
                "INSTALLATION_ID",
                self.team.id,
                self.user,
            )
            integration.errors = ""
            integration.save()

            with pytest.raises(Exception):
                GitHubIntegration(integration).refresh_access_token()

        integration.refresh_from_db()
        assert integration.errors == "TOKEN_REFRESH_FAILED"

    @patch("posthog.models.integration.reload_integrations_on_workers")
    @patch("posthog.models.integration.GitHubIntegration.client_request")
    def test_github_refresh_access_token_resets_errors(self, mock_client_request, mock_reload):
        """Test that errors field is reset to empty string after successful refresh_access_token"""
        mock_client_request.side_effect = self._mock_github_client_request(status_code=201)

        with freeze_time("2024-01-01T12:00:00Z"):
            integration = GitHubIntegration.integration_from_installation_id(
                "INSTALLATION_ID",
                self.team.id,
                self.user,
            )
            integration.errors = "TOKEN_REFRESH_FAILED"
            integration.save()

            GitHubIntegration(integration).refresh_access_token()

        integration.refresh_from_db()
        assert integration.errors == ""


class TestDatabricksIntegrationModel(BaseTest):
    @patch("posthog.models.integration.socket.socket")
    def test_integration_from_config_with_valid_config(self, mock_socket):
        mock_socket.return_value.connect.return_value = None
        integration = DatabricksIntegration.integration_from_config(
            team_id=self.team.pk,
            server_hostname="databricks.com",
            client_id="client_id",
            client_secret="client_secret",
            created_by=self.user,
        )
        assert integration.team == self.team
        assert integration.created_by == self.user
        assert integration.config == {"server_hostname": "databricks.com"}
        assert integration.sensitive_config == {"client_id": "client_id", "client_secret": "client_secret"}

    @patch("posthog.models.integration.socket.socket")
    def test_integration_from_config_with_invalid_server_hostname(self, mock_socket):
        # this is the error raised when the server hostname is invalid
        mock_socket.return_value.connect.side_effect = socket.gaierror(
            8, "nodename nor servname provided, or not known"
        )
        with pytest.raises(
            DatabricksIntegrationError, match="Databricks integration error: could not connect to hostname 'invalid'"
        ):
            DatabricksIntegration.integration_from_config(
                team_id=self.team.pk,
                server_hostname="invalid",
                client_id="client_id",
                client_secret="client_secret",
                created_by=self.user,
            )


class TestEmailIntegrationDomainValidation(BaseTest):
    @patch("products.workflows.backend.providers.SESProvider.create_email_domain")
    def test_successful_domain_creation_ses(self, mock_create_email_domain):
        mock_create_email_domain.return_value = {"status": "success", "domain": "successdomain.com"}
        config = {"email": "user@successdomain.com", "name": "Test User", "provider": "ses"}
        integration = EmailIntegration.create_native_integration(config, team_id=self.team.id, created_by=self.user)
        assert integration.team == self.team
        assert integration.config["email"] == "user@successdomain.com"
        assert integration.config["provider"] == "ses"
        assert integration.config["domain"] == "successdomain.com"
        assert integration.config["name"] == "Test User"
        assert integration.config["verified"] is False

    @override_settings(MAILJET_PUBLIC_KEY="test_api_key", MAILJET_SECRET_KEY="test_secret_key")
    def test_duplicate_domain_in_another_team(self):
        # Create an integration with a domain in another team
        other_team = Team.objects.create(organization=self.organization, name="other team")
        config = {"email": "user@example.com", "name": "Test User"}
        EmailIntegration.create_native_integration(config, team_id=other_team.id, created_by=self.user)

        # Attempt to create the same domain in this team should raise ValidationError
        with pytest.raises(ValidationError) as exc:
            EmailIntegration.create_native_integration(config, team_id=self.team.id, created_by=self.user)
        assert "already exists in another project" in str(exc.value)

    @override_settings(MAILJET_PUBLIC_KEY="test_api_key", MAILJET_SECRET_KEY="test_secret_key")
    def test_unsupported_email_domain(self):
        # Test with a free email domain
        config = {"email": "user@gmail.com", "name": "Test User"}

        with pytest.raises(ValidationError) as exc:
            EmailIntegration.create_native_integration(config, team_id=self.team.id, created_by=self.user)
        assert "not supported" in str(exc.value)

        # Test with a disposable email domain
        disposable_domain = next(iter(disposable_email_domains_list))
        config = {"email": f"user@{disposable_domain}", "name": "Test User"}

        with pytest.raises(ValidationError) as exc:
            EmailIntegration.create_native_integration(config, team_id=self.team.id, created_by=self.user)
        assert disposable_domain in str(exc.value)
        assert "not supported" in str(exc.value)
