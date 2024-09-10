from datetime import datetime, timedelta
import time
from typing import Optional
from unittest.mock import patch

from freezegun import freeze_time
import pytest
from posthog.models.instance_setting import set_instance_setting
from posthog.models.integration import Integration, OauthIntegration, SlackIntegration, GoogleCloudIntegration
from posthog.test.base import BaseTest


class TestIntegrationModel(BaseTest):
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
            OauthIntegration.authorize_url("salesforce", next="/projects/test")

    def test_authorize_url(self):
        with self.settings(**self.mock_settings):
            url = OauthIntegration.authorize_url("salesforce", next="/projects/test")
            assert (
                url
                == "https://login.salesforce.com/services/oauth2/authorize?client_id=salesforce-client-id&scope=full+refresh_token&redirect_uri=https%3A%2F%2Flocalhost%3A8000%2Fintegrations%2Fsalesforce%2Fcallback&response_type=code&state=next%3D%252Fprojects%252Ftest"
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
