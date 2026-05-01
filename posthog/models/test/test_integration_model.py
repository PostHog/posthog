import time
import socket
from datetime import UTC, datetime, timedelta
from typing import Optional

import pytest
from freezegun import freeze_time
from posthog.test.base import BaseTest
from unittest.mock import MagicMock, call, patch

from django.core.cache import cache
from django.db import connection
from django.utils import timezone

import requests
from disposable_email_domains import blocklist as disposable_email_domains_list
from parameterized import parameterized
from prometheus_client import REGISTRY
from rest_framework.exceptions import ValidationError

from posthog.models.github_integration_base import GITHUB_BRANCH_CACHE_TTL_SECONDS, GITHUB_REPOSITORY_CACHE_TTL_SECONDS
from posthog.models.instance_setting import set_instance_setting
from posthog.models.integration import (
    MISSING_CERT_PATH,
    TLS,
    Authority,
    Credentials,
    DatabricksIntegration,
    DatabricksIntegrationError,
    EmailIntegration,
    GitHubIntegration,
    GitHubIntegrationError,
    GitHubRateLimitError,
    GoogleCloudIntegration,
    GoogleCloudServiceAccountIntegration,
    Integration,
    OauthIntegration,
    PostgreSQLIntegration,
    SlackIntegration,
    raise_if_github_rate_limited,
)
from posthog.models.organization import Organization
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
        "LINKEDIN_APP_CLIENT_ID": "linkedin-client-id",
        "LINKEDIN_APP_CLIENT_SECRET": "linkedin-client-secret",
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

    @parameterized.expand(
        [
            (
                "json_error_body",
                400,
                {
                    "error": "invalid_grant",
                    "error_description": "Authorization code does not exist or has expired.",
                },
                None,
                '{"error":"invalid_grant","error_description":"Authorization code does not exist or has expired."}',
                ["invalid_grant", "Authorization code does not exist"],
            ),
            (
                "non_json_error_body",
                502,
                None,
                ValueError("not json"),
                "<html>Bad Gateway</html>",
                ["salesforce"],
            ),
        ]
    )
    @patch("posthog.models.integration.requests.post")
    def test_oauth_token_exchange_failure_raises_validation_error(
        self, _name, status_code, json_return, json_side_effect, body_text, expected_in_message, mock_post
    ):
        """A failed token exchange must surface a ValidationError (→ DRF 400 with `detail`) so the
        frontend toast renders something useful. Covers both well-formed JSON error bodies (where
        we extract `error_description`) and non-JSON bodies (where the helper falls back to the
        raw text or a status-only message)."""
        with self.settings(**self.mock_settings):
            mock_post.return_value.status_code = status_code
            if json_side_effect is not None:
                mock_post.return_value.json.side_effect = json_side_effect
            else:
                mock_post.return_value.json.return_value = json_return
            mock_post.return_value.text = body_text

            with pytest.raises(ValidationError) as e:
                OauthIntegration.integration_from_oauth_response(
                    "salesforce",
                    self.team.id,
                    self.user,
                    {"code": "code", "state": "next=/projects/test"},
                )

            message = str(e.value).lower()
            for fragment in expected_in_message:
                assert fragment.lower() in message

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

    @patch("posthog.models.integration.requests.post")
    def test_linkedin_integration_extracts_user_info_from_id_token(self, mock_post):
        """
        LinkedIn's /v2/userinfo endpoint has intermittent REVOKED_ACCESS_TOKEN errors,
        so we extract user info from the id_token JWT instead.
        """
        import json
        import base64

        # Create a mock JWT id_token with sub and email in the payload
        jwt_payload = {"sub": "linkedin_user_123", "email": "user@example.com", "iat": 1704110400}
        encoded_payload = base64.urlsafe_b64encode(json.dumps(jwt_payload).encode()).decode().rstrip("=")
        mock_id_token = f"eyJhbGciOiJSUzI1NiJ9.{encoded_payload}.fake_signature"

        with self.settings(**self.mock_settings):
            mock_post.return_value.status_code = 200
            mock_post.return_value.json.return_value = {
                "access_token": "FAKE_ACCESS_TOKEN",
                "refresh_token": "FAKE_REFRESH_TOKEN",
                "id_token": mock_id_token,
                "expires_in": 3600,
            }

            with freeze_time("2024-01-01T12:00:00Z"):
                integration = OauthIntegration.integration_from_oauth_response(
                    "linkedin-ads",
                    self.team.id,
                    self.user,
                    {
                        "code": "code",
                        "state": "next=/projects/test",
                    },
                )

            assert integration.team == self.team
            assert integration.created_by == self.user
            # Verify sub and email were extracted from JWT
            assert integration.config["sub"] == "linkedin_user_123"
            assert integration.config["email"] == "user@example.com"
            assert integration.config["refreshed_at"] == 1704110400
            assert integration.config["expires_in"] == 3600

            assert integration.sensitive_config == {
                "access_token": "FAKE_ACCESS_TOKEN",
                "refresh_token": "FAKE_REFRESH_TOKEN",
                "id_token": mock_id_token,
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

    @parameterized.expand(
        [
            (
                "rotated",
                {
                    "access_token": "REFRESHED_ACCESS_TOKEN",
                    "refresh_token": "ROTATED_REFRESH_TOKEN",
                    "expires_in": 1000,
                },
                "ROTATED_REFRESH_TOKEN",
            ),
            ("not_rotated", {"access_token": "REFRESHED_ACCESS_TOKEN", "expires_in": 1000}, "REFRESH"),
        ]
    )
    @patch("posthog.models.integration.reload_integrations_on_workers")
    @patch("posthog.models.integration.requests.post")
    def test_refresh_access_token_refresh_token_handling(
        self, _name, token_response, expected_refresh_token, mock_post, mock_reload
    ):
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = token_response

        integration = self.create_integration(kind="hubspot", config={"expires_in": 1000})

        with freeze_time("2024-01-01T14:00:00Z"):
            with self.settings(**self.mock_settings):
                OauthIntegration(integration).refresh_access_token()

        assert integration.sensitive_config["access_token"] == "REFRESHED_ACCESS_TOKEN"
        assert integration.sensitive_config["refresh_token"] == expected_refresh_token

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

    @patch("posthog.models.integration.requests.post")
    def test_stripe_integration_from_oauth_response_uses_apps_endpoint_and_basic_auth(self, mock_post):
        # Stripe Apps OAuth (api.stripe.com/v1/oauth/token) is a different system from
        # Stripe Connect OAuth (connect.stripe.com/oauth/token): it authenticates the
        # token exchange with HTTP Basic (secret as username, no password) and accepts
        # only `code` + `grant_type` in the body. Codes minted by `marketplace.stripe.com`
        # cannot be redeemed at the Connect endpoint.
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {
            "access_token": "FAKE_ACCESS",
            "refresh_token": "FAKE_REFRESH",
            "stripe_user_id": "acct_123",
            "account_name": "Test Account",
            "expires_in": 3600,
        }

        with self.settings(
            STRIPE_APP_CLIENT_ID="ca_test_clientid",
            STRIPE_APP_SECRET_KEY="sk_test_secret",
        ):
            OauthIntegration.integration_from_oauth_response(
                "stripe",
                self.team.id,
                self.user,
                {"code": "ac_real_code"},
            )

        call = mock_post.call_args
        assert call.args[0] == "https://api.stripe.com/v1/oauth/token"
        assert call.kwargs["data"] == {"code": "ac_real_code", "grant_type": "authorization_code"}
        assert call.kwargs["auth"].username == "sk_test_secret"
        assert call.kwargs["auth"].password == ""

    def test_stripe_authorize_url_uses_live_client_id_by_default(self):
        with self.settings(
            STRIPE_APP_CLIENT_ID="ca_live_clientid",
            STRIPE_APP_SANDBOX_CLIENT_ID="ca_sandbox_clientid",
            STRIPE_APP_SECRET_KEY="sk_live_secret",
            STRIPE_APP_SANDBOX_SECRET_KEY="sk_test_sandbox_secret",
            STRIPE_APP_OVERRIDE_AUTHORIZE_URL="",
        ):
            url = OauthIntegration.authorize_url("stripe", token="state_token", next="/projects/test")
            assert "client_id=ca_live_clientid" in url
            assert "client_id=ca_sandbox_clientid" not in url

    def test_stripe_authorize_url_uses_sandbox_client_id_when_is_sandbox(self):
        with self.settings(
            STRIPE_APP_CLIENT_ID="ca_live_clientid",
            STRIPE_APP_SANDBOX_CLIENT_ID="ca_sandbox_clientid",
            STRIPE_APP_SECRET_KEY="sk_live_secret",
            STRIPE_APP_SANDBOX_SECRET_KEY="sk_test_sandbox_secret",
            STRIPE_APP_OVERRIDE_AUTHORIZE_URL="",
        ):
            url = OauthIntegration.authorize_url("stripe", token="state_token", next="/projects/test", is_sandbox=True)
            assert "client_id=ca_sandbox_clientid" in url
            assert "client_id=ca_live_clientid" not in url

    def test_stripe_oauth_config_uses_sandbox_secret_when_is_sandbox(self):
        with self.settings(
            STRIPE_APP_CLIENT_ID="ca_live_clientid",
            STRIPE_APP_SANDBOX_CLIENT_ID="ca_sandbox_clientid",
            STRIPE_APP_SECRET_KEY="sk_live_secret",
            STRIPE_APP_SANDBOX_SECRET_KEY="sk_test_sandbox_secret",
        ):
            live_cfg = OauthIntegration.oauth_config_for_kind("stripe")
            sandbox_cfg = OauthIntegration.oauth_config_for_kind("stripe", is_sandbox=True)
            assert live_cfg.client_secret == "sk_live_secret"
            assert sandbox_cfg.client_secret == "sk_test_sandbox_secret"

    def test_stripe_authorize_url_raises_when_sandbox_requested_but_not_configured(self):
        with self.settings(
            STRIPE_APP_CLIENT_ID="ca_live_clientid",
            STRIPE_APP_SANDBOX_CLIENT_ID="",
            STRIPE_APP_SANDBOX_SECRET_KEY="",
            STRIPE_APP_SECRET_KEY="sk_live_secret",
        ):
            with pytest.raises(NotImplementedError, match="sandbox"):
                OauthIntegration.authorize_url("stripe", token="state_token", is_sandbox=True)

    def test_stripe_authorize_url_raises_when_sandbox_secret_missing(self):
        with self.settings(
            STRIPE_APP_CLIENT_ID="ca_live_clientid",
            STRIPE_APP_SANDBOX_CLIENT_ID="ca_sandbox_clientid",
            STRIPE_APP_SANDBOX_SECRET_KEY="",
            STRIPE_APP_SECRET_KEY="sk_live_secret",
        ):
            with pytest.raises(NotImplementedError, match="sandbox"):
                OauthIntegration.authorize_url("stripe", token="state_token", is_sandbox=True)

    @patch("posthog.models.integration.requests.post")
    def test_stripe_token_exchange_falls_back_to_sandbox_on_does_not_belong_error(self, mock_post):
        # First call (live secret) returns 400 with the marker error - second call should
        # retry with sandbox config and succeed.
        first_response = MagicMock(
            status_code=400,
            text='{"error":"invalid_grant","error_description":"Authorization code provided does not belong to you"}',
        )
        first_response.json.return_value = {
            "error": "invalid_grant",
            "error_description": "Authorization code provided does not belong to you",
        }
        second_response = MagicMock(status_code=200)
        second_response.json.return_value = {
            "access_token": "FAKE_SANDBOX_ACCESS",
            "refresh_token": "FAKE_SANDBOX_REFRESH",
            "stripe_user_id": "acct_sandbox_123",
            "account_name": "Sandbox Account",
            "expires_in": 3600,
        }
        mock_post.side_effect = [first_response, second_response]

        with self.settings(
            STRIPE_APP_CLIENT_ID="ca_live_clientid",
            STRIPE_APP_SANDBOX_CLIENT_ID="ca_sandbox_clientid",
            STRIPE_APP_SECRET_KEY="sk_live_secret",
            STRIPE_APP_SANDBOX_SECRET_KEY="sk_test_sandbox_secret",
        ):
            OauthIntegration.integration_from_oauth_response(
                "stripe",
                self.team.id,
                self.user,
                {"code": "ac_sandbox_code"},
            )

        assert mock_post.call_count == 2
        first_call_secret = mock_post.call_args_list[0].kwargs["auth"].username
        second_call_secret = mock_post.call_args_list[1].kwargs["auth"].username
        assert first_call_secret == "sk_live_secret"
        assert second_call_secret == "sk_test_sandbox_secret"

    @patch("posthog.models.integration.requests.post")
    def test_stripe_token_exchange_does_not_retry_when_sandbox_secret_unset(self, mock_post):
        first_response = MagicMock(
            status_code=400,
            text='{"error":"invalid_grant","error_description":"Authorization code provided does not belong to you"}',
        )
        first_response.json.return_value = {"error": "invalid_grant"}
        mock_post.return_value = first_response

        with self.settings(
            STRIPE_APP_CLIENT_ID="ca_live_clientid",
            STRIPE_APP_SANDBOX_CLIENT_ID="",
            STRIPE_APP_SECRET_KEY="sk_live_secret",
            STRIPE_APP_SANDBOX_SECRET_KEY="",
        ):
            with pytest.raises(ValidationError, match="OAuth failed"):
                OauthIntegration.integration_from_oauth_response(
                    "stripe",
                    self.team.id,
                    self.user,
                    {"code": "ac_some_code"},
                )

        assert mock_post.call_count == 1

    @patch("posthog.models.integration.requests.post")
    def test_stripe_token_exchange_does_not_retry_when_only_sandbox_secret_set(self, mock_post):
        # If the sandbox secret is set but the sandbox client_id is not, the retry guard
        # must fail closed - oauth_config_for_kind would otherwise raise NotImplementedError
        # and mask the original Stripe error.
        first_response = MagicMock(
            status_code=400,
            text='{"error":"invalid_grant","error_description":"Authorization code provided does not belong to you"}',
        )
        first_response.json.return_value = {"error": "invalid_grant"}
        mock_post.return_value = first_response

        with self.settings(
            STRIPE_APP_CLIENT_ID="ca_live_clientid",
            STRIPE_APP_SANDBOX_CLIENT_ID="",
            STRIPE_APP_SECRET_KEY="sk_live_secret",
            STRIPE_APP_SANDBOX_SECRET_KEY="sk_test_sandbox_secret",
        ):
            with pytest.raises(ValidationError, match="OAuth failed"):
                OauthIntegration.integration_from_oauth_response(
                    "stripe",
                    self.team.id,
                    self.user,
                    {"code": "ac_some_code"},
                )

        assert mock_post.call_count == 1

    @patch("posthog.models.integration.reload_integrations_on_workers")
    @patch("posthog.models.integration.requests.post")
    def test_stripe_refresh_access_token_uses_apps_endpoint_and_basic_auth(self, mock_post, mock_reload):
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {"access_token": "REFRESHED", "expires_in": 1000}

        integration = self.create_integration(kind="stripe", config={"expires_in": 1000})

        with self.settings(
            STRIPE_APP_CLIENT_ID="ca_test_clientid",
            STRIPE_APP_SECRET_KEY="sk_test_secret",
        ):
            OauthIntegration(integration).refresh_access_token()

        call = mock_post.call_args
        assert call.args[0] == "https://api.stripe.com/v1/oauth/token"
        assert call.kwargs["data"] == {"refresh_token": "REFRESH", "grant_type": "refresh_token"}
        assert call.kwargs["auth"].username == "sk_test_secret"
        assert call.kwargs["auth"].password == ""

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


class TestGitHubIntegrationModel(BaseTest):
    def setUp(self):
        super().setUp()
        cache.clear()

    def create_integration(self, config: Optional[dict] = None, sensitive_config: Optional[dict] = None) -> Integration:
        _config = {"expires_at": 3600}
        _sensitive_config = {"token": "REFRESH"}
        _config.update(config or {})
        _sensitive_config.update(sensitive_config or {})

        return Integration.objects.create(
            team=self.team, kind="github", config=_config, sensitive_config=_sensitive_config
        )

    def mock_github_client_request(
        self, status_code=201, token="ACCESS_TOKEN", repository_selection="all", expires_in_hours=1, error_text=None
    ):
        def _client_request(endpoint, method="GET"):
            mock_response = MagicMock()
            if method == "POST":
                mock_response.status_code = status_code
                dt = datetime.now(UTC) + timedelta(hours=expires_in_hours)
                iso_time = dt.replace(tzinfo=None).isoformat(timespec="seconds") + "Z"

                if status_code == 201:
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

    @parameterized.expand(
        [
            (
                "complete_headers",
                {
                    "X-RateLimit-Resource": "core",
                    "X-RateLimit-Remaining": "4998",
                    "X-RateLimit-Limit": "5000",
                    "X-RateLimit-Reset": "1704117600",
                },
                "core",
                4998,
                5000,
                1704117600,
            ),
            ("no_headers", {}, "unknown", None, None, None),
            (
                "no_resource_header",
                {
                    "X-RateLimit-Remaining": "4997",
                    "X-RateLimit-Limit": "5000",
                    "X-RateLimit-Reset": "1704117601",
                },
                "unknown",
                4997,
                5000,
                1704117601,
            ),
        ]
    )
    @patch("posthog.models.github_integration_base.requests.get")
    def test_github_api_request_metrics_include_integration_and_rate_limit_headers(
        self,
        _name: str,
        response_headers: dict[str, str],
        expected_resource: str,
        expected_remaining: int | None,
        expected_limit: int | None,
        expected_reset: int | None,
        mock_get,
    ):
        integration = self.create_integration(
            {"installation_id": "INSTALL", "account": {"name": "PostHog"}},
            {"access_token": "ACCESS_TOKEN"},
        )
        response = MagicMock()
        response.status_code = 200
        response.headers = response_headers
        mock_get.return_value = response

        labels = {
            "integration_id": str(integration.id),
            "method": "GET",
            "endpoint": "/repos/{owner}/{repo}",
            "status_code": "200",
        }
        previous_count = REGISTRY.get_sample_value("github_integration_api_requests_total", labels) or 0

        GitHubIntegration(integration)._github_api_get(
            "https://api.github.com/repos/PostHog/posthog",
            endpoint="/repos/{owner}/{repo}",
            headers={"Accept": "application/vnd.github+json"},
        )

        assert REGISTRY.get_sample_value("github_integration_api_requests_total", labels) == previous_count + 1
        assert (
            REGISTRY.get_sample_value(
                "github_integration_api_rate_limit_remaining",
                {"integration_id": str(integration.id), "resource": expected_resource},
            )
            == expected_remaining
        )
        assert (
            REGISTRY.get_sample_value(
                "github_integration_api_rate_limit_limit",
                {"integration_id": str(integration.id), "resource": expected_resource},
            )
            == expected_limit
        )
        assert (
            REGISTRY.get_sample_value(
                "github_integration_api_rate_limit_reset_timestamp_seconds",
                {"integration_id": str(integration.id), "resource": expected_resource},
            )
            == expected_reset
        )

    @patch("posthog.models.github_integration_base.requests.get")
    def test_github_api_request_metrics_include_request_exceptions(self, mock_get):
        integration = self.create_integration(
            {"installation_id": "INSTALL", "account": {"name": "PostHog"}},
            {"access_token": "ACCESS_TOKEN"},
        )
        mock_get.side_effect = requests.RequestException("network failure")

        labels = {
            "integration_id": str(integration.id),
            "method": "GET",
            "endpoint": "/repos/{owner}/{repo}",
            "status_code": "exception",
        }
        previous_count = REGISTRY.get_sample_value("github_integration_api_requests_total", labels) or 0

        with pytest.raises(requests.RequestException):
            GitHubIntegration(integration)._github_api_get(
                "https://api.github.com/repos/PostHog/posthog",
                endpoint="/repos/{owner}/{repo}",
                headers={"Accept": "application/vnd.github+json"},
            )

        assert REGISTRY.get_sample_value("github_integration_api_requests_total", labels) == previous_count + 1

    @patch("posthog.models.github_integration_base.GitHubIntegrationBase.client_request")
    def test_github_refresh_access_token_metrics_include_request_exceptions(self, mock_client_request):
        integration = self.create_integration(
            {"installation_id": "INSTALL", "account": {"name": "PostHog"}},
            {"access_token": "ACCESS_TOKEN"},
        )
        mock_client_request.side_effect = requests.RequestException("network failure")

        labels = {
            "integration_id": str(integration.id),
            "method": "POST",
            "endpoint": "/app/installations/{installation_id}/access_tokens",
            "status_code": "exception",
        }
        previous_count = REGISTRY.get_sample_value("github_integration_api_requests_total", labels) or 0

        with pytest.raises(requests.RequestException):
            GitHubIntegration(integration).refresh_access_token()

        assert REGISTRY.get_sample_value("github_integration_api_requests_total", labels) == previous_count + 1

    @patch("posthog.models.github_integration_base.GitHubIntegrationBase.client_request")
    def test_github_integration_refresh_token(self, mock_client_request):
        mock_client_request.side_effect = self.mock_github_client_request(status_code=201)

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
    @patch("posthog.models.github_integration_base.GitHubIntegrationBase.client_request")
    def test_github_refresh_access_token_handles_errors(self, mock_client_request, mock_reload):
        """Test that errors field is set if refresh_access_token fails"""
        integration = self.create_integration({"expires_at": 3600}, {"token": "REFRESH"})
        mock_client_request.side_effect = self.mock_github_client_request(status_code=400, error_text="error")

        with freeze_time("2024-01-01T12:00:00Z"):
            integration.errors = ""
            integration.save()

            with pytest.raises(Exception):
                GitHubIntegration(integration).refresh_access_token()

        integration.refresh_from_db()
        assert integration.errors == "TOKEN_REFRESH_FAILED"

    @patch("posthog.models.integration.reload_integrations_on_workers")
    @patch("posthog.models.github_integration_base.GitHubIntegrationBase.client_request")
    def test_github_refresh_access_token_resets_errors(self, mock_client_request, mock_reload):
        """Test that errors field is reset to empty string after successful refresh_access_token"""
        mock_client_request.side_effect = self.mock_github_client_request(status_code=201)

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

    @patch("posthog.models.github_integration_base.requests.get")
    @patch("posthog.models.integration.GitHubIntegration.access_token_expired", return_value=False)
    def test_list_repositories_retries_transient_non_json_response(self, _mock_expired, mock_get):
        integration = self.create_integration(
            {"installation_id": "INSTALL", "account": {"name": "PostHog"}},
            {"access_token": "ACCESS_TOKEN"},
        )

        transient = MagicMock()
        transient.status_code = 502
        transient.json.side_effect = ValueError("not json")

        success = MagicMock()
        success.status_code = 200
        success.json.return_value = {
            "repositories": [
                {"id": 1, "name": "posthog", "full_name": "PostHog/posthog"},
                {"id": 2, "name": "posthog-js", "full_name": "PostHog/posthog-js"},
            ]
        }

        mock_get.side_effect = [transient, success]

        repos, has_more = GitHubIntegration(integration).list_repositories()

        assert repos == [
            {"id": 1, "name": "posthog", "full_name": "PostHog/posthog"},
            {"id": 2, "name": "posthog-js", "full_name": "PostHog/posthog-js"},
        ]
        assert has_more is False
        assert mock_get.call_count == 2

    @patch("posthog.models.github_integration_base.requests.get")
    @patch("posthog.models.integration.GitHubIntegration.access_token_expired", return_value=False)
    def test_list_repositories_raises_after_repeated_transient_non_json(self, _mock_expired, mock_get):
        integration = self.create_integration(
            {"installation_id": "INSTALL", "account": {"name": "PostHog"}},
            {"access_token": "ACCESS_TOKEN"},
        )

        transient_1 = MagicMock()
        transient_1.status_code = 502
        transient_1.json.side_effect = ValueError("not json")

        transient_2 = MagicMock()
        transient_2.status_code = 502
        transient_2.json.side_effect = ValueError("not json")

        mock_get.side_effect = [transient_1, transient_2]

        with pytest.raises(GitHubIntegrationError, match="list_repositories non-JSON response"):
            GitHubIntegration(integration).list_repositories()

        assert mock_get.call_count == 2

    @patch("posthog.models.github_integration_base.requests.get")
    @patch("posthog.models.integration.GitHubIntegration.access_token_expired", return_value=False)
    def test_list_all_repositories_raises_when_later_page_fails(self, _mock_expired, mock_get):
        integration = self.create_integration(
            {"installation_id": "INSTALL", "account": {"name": "PostHog"}},
            {"access_token": "ACCESS_TOKEN"},
        )

        first_page = MagicMock()
        first_page.status_code = 200
        first_page.json.return_value = {
            "repositories": [{"id": i, "name": f"repo-{i}", "full_name": f"PostHog/repo-{i}"} for i in range(100)]
        }

        second_page = MagicMock()
        second_page.status_code = 502
        second_page.json.return_value = {"message": "bad gateway"}

        # Page-1 succeeds. Page-2 fetch is retried once after transient 502.
        mock_get.side_effect = [first_page, second_page, second_page]

        with pytest.raises(GitHubIntegrationError, match="failed to list repositories"):
            GitHubIntegration(integration).list_all_repositories()

        assert mock_get.call_count == 3

    @patch("posthog.models.integration.GitHubIntegration.list_repositories")
    def test_list_all_repositories_fetches_all_pages(self, mock_list):
        integration = self.create_integration(
            {"installation_id": "INSTALL", "account": {"name": "PostHog"}},
            {"access_token": "ACCESS_TOKEN"},
        )

        first_page = [{"id": i, "name": f"repo-{i}", "full_name": f"PostHog/repo-{i}"} for i in range(100)]
        second_page = [{"id": i, "name": f"repo-{i}", "full_name": f"PostHog/repo-{i}"} for i in range(100, 130)]
        mock_list.side_effect = [
            (first_page, True),
            (second_page, False),
        ]

        repos = GitHubIntegration(integration).list_all_repositories()

        assert len(repos) == 130
        assert repos == first_page + second_page
        assert mock_list.call_args_list == [
            call(page=1, per_page=100),
            call(page=2, per_page=100),
        ]

    @patch("posthog.models.integration.GitHubIntegration.list_all_repositories")
    def test_list_cached_repositories_uses_cached_data_when_fresh(self, mock_list_all):
        cached_repositories = [
            {"id": 1, "name": "posthog", "full_name": "PostHog/posthog"},
            {"id": 2, "name": "posthog-js", "full_name": "PostHog/posthog-js"},
        ]
        integration = self.create_integration(
            {"installation_id": "INSTALL", "account": {"name": "PostHog"}},
            {"access_token": "ACCESS_TOKEN"},
        )
        integration.repository_cache = cached_repositories
        integration.repository_cache_updated_at = timezone.now()
        integration.save(update_fields=["repository_cache", "repository_cache_updated_at"])

        labels = {
            "integration_id": str(integration.id),
            "cache": "repositories",
            "repository": "__all__",
            "result": "hit",
        }
        previous_count = REGISTRY.get_sample_value("github_integration_cache_accesses_total", labels) or 0

        repos, has_more = GitHubIntegration(integration).list_cached_repositories(limit=1, offset=1)

        assert repos == [{"id": 2, "name": "posthog-js", "full_name": "PostHog/posthog-js"}]
        assert has_more is False
        mock_list_all.assert_not_called()
        assert REGISTRY.get_sample_value("github_integration_cache_accesses_total", labels) == previous_count + 1

    @patch("posthog.models.integration.GitHubIntegration.list_all_repositories")
    def test_sync_repository_cache_respects_refresh_cooldown(self, mock_list_all):
        cached_repositories = [
            {"id": 1, "name": "posthog", "full_name": "PostHog/posthog"},
            {"id": 2, "name": "posthog-js", "full_name": "PostHog/posthog-js"},
        ]
        integration = self.create_integration(
            {"installation_id": "INSTALL", "account": {"name": "PostHog"}},
            {"access_token": "ACCESS_TOKEN"},
        )
        integration.repository_cache = cached_repositories
        integration.repository_cache_updated_at = timezone.now()
        integration.save(update_fields=["repository_cache", "repository_cache_updated_at"])

        repos = GitHubIntegration(integration).sync_repository_cache(min_refresh_interval_seconds=60)

        assert repos == cached_repositories
        mock_list_all.assert_not_called()

    @patch("posthog.models.integration.GitHubIntegration.list_all_repositories")
    def test_sync_repository_cache_only_updates_timestamp_when_snapshot_unchanged(self, mock_list_all):
        cached_repositories = [
            {"id": 1, "name": "posthog", "full_name": "PostHog/posthog"},
            {"id": 2, "name": "posthog-js", "full_name": "PostHog/posthog-js"},
        ]
        integration = self.create_integration(
            {"installation_id": "INSTALL", "account": {"name": "PostHog"}},
            {"access_token": "ACCESS_TOKEN"},
        )
        original_updated_at = timezone.now() - timedelta(minutes=5)
        integration.repository_cache = cached_repositories
        integration.repository_cache_updated_at = original_updated_at
        integration.save(update_fields=["repository_cache", "repository_cache_updated_at"])
        mock_list_all.return_value = cached_repositories

        with patch.object(integration, "save", wraps=integration.save) as mock_save:
            repos = GitHubIntegration(integration).sync_repository_cache()

        assert repos == cached_repositories
        mock_save.assert_called_once_with(update_fields=["repository_cache_updated_at"])
        integration.refresh_from_db()
        assert integration.repository_cache == cached_repositories
        assert integration.repository_cache_updated_at is not None
        assert integration.repository_cache_updated_at > original_updated_at

    @patch("posthog.models.integration.GitHubIntegration.list_all_repositories")
    def test_list_cached_repositories_populates_cache_on_miss(self, mock_list_all):
        fetched_repositories = [
            {"id": 1, "name": "posthog", "full_name": "PostHog/posthog"},
            {"id": 2, "name": "posthog-js", "full_name": "PostHog/posthog-js"},
        ]
        integration = self.create_integration(
            {"installation_id": "INSTALL", "account": {"name": "PostHog"}},
            {"access_token": "ACCESS_TOKEN"},
        )
        mock_list_all.return_value = fetched_repositories

        labels = {
            "integration_id": str(integration.id),
            "cache": "repositories",
            "repository": "__all__",
            "result": "miss",
        }
        previous_count = REGISTRY.get_sample_value("github_integration_cache_accesses_total", labels) or 0

        repos, has_more = GitHubIntegration(integration).list_cached_repositories(limit=1, offset=0)

        integration.refresh_from_db()
        assert repos == [{"id": 1, "name": "posthog", "full_name": "PostHog/posthog"}]
        assert has_more is True
        assert integration.repository_cache == fetched_repositories
        assert integration.repository_cache_updated_at is not None
        mock_list_all.assert_called_once_with()
        assert REGISTRY.get_sample_value("github_integration_cache_accesses_total", labels) == previous_count + 1

    @patch("posthog.models.integration.GitHubIntegration.list_all_repositories")
    def test_list_cached_repositories_returns_stale_cache_on_refresh_error(self, mock_list_all):
        stale_repositories = [
            {"id": 1, "name": "posthog", "full_name": "PostHog/posthog"},
            {"id": 2, "name": "posthog-js", "full_name": "PostHog/posthog-js"},
        ]
        integration = self.create_integration(
            {"installation_id": "INSTALL", "account": {"name": "PostHog"}},
            {"access_token": "ACCESS_TOKEN"},
        )
        integration.repository_cache = stale_repositories
        integration.repository_cache_updated_at = timezone.now() - timedelta(
            seconds=GITHUB_REPOSITORY_CACHE_TTL_SECONDS + 1
        )
        integration.save(update_fields=["repository_cache", "repository_cache_updated_at"])
        mock_list_all.side_effect = Exception("GitHub is slow")

        repos, has_more = GitHubIntegration(integration).list_cached_repositories(limit=10, offset=0)

        integration.refresh_from_db()
        assert repos == stale_repositories
        assert has_more is False
        assert integration.repository_cache == stale_repositories
        mock_list_all.assert_called_once_with()

    @patch("posthog.models.integration.GitHubIntegration.list_all_repositories")
    def test_list_cached_repositories_raises_on_refresh_error_without_cache(self, mock_list_all):
        integration = self.create_integration(
            {"installation_id": "INSTALL", "account": {"name": "PostHog"}},
            {"access_token": "ACCESS_TOKEN"},
        )
        mock_list_all.side_effect = Exception("GitHub is slow")

        with pytest.raises(Exception, match="GitHub is slow"):
            GitHubIntegration(integration).list_cached_repositories(limit=10, offset=0)

        integration.refresh_from_db()
        assert integration.repository_cache == []
        assert integration.repository_cache_updated_at is None
        mock_list_all.assert_called_once_with()

    @patch("posthog.models.integration.GitHubIntegration.list_all_repositories")
    def test_list_cached_repositories_pages_with_full_cached_snapshot(self, mock_list_all):
        fetched_repositories = [{"id": i, "name": f"repo-{i}", "full_name": f"PostHog/repo-{i}"} for i in range(650)]
        integration = self.create_integration(
            {"installation_id": "INSTALL", "account": {"name": "PostHog"}},
            {"access_token": "ACCESS_TOKEN"},
        )
        mock_list_all.return_value = fetched_repositories

        repos, has_more = GitHubIntegration(integration).list_cached_repositories(limit=25, offset=600)

        assert repos == fetched_repositories[600:625]
        assert has_more is True
        mock_list_all.assert_called_once_with()

    @parameterized.expand(
        [
            ("blank_search_returns_all", "   ", 10, 0, [1, 2, 3, 4], False),
            ("no_match_returns_empty", "missing", 10, 0, [], False),
            ("casefold_matches_owner_prefix", "POSTHOG", 10, 0, [1, 2, 3, 4], False),
            ("pagination_applies_after_filter", "posthog", 1, 1, [2], True),
        ]
    )
    @patch("posthog.models.integration.GitHubIntegration.list_all_repositories")
    def test_list_cached_repositories_filters_search_before_pagination(
        self,
        _name,
        search,
        limit,
        offset,
        expected_ids,
        expected_has_more,
        mock_list_all,
    ):
        fetched_repositories = [
            {"id": 1, "name": "posthog", "full_name": "PostHog/posthog"},
            {"id": 2, "name": "posthog-js", "full_name": "PostHog/posthog-js"},
            {"id": 3, "name": "code", "full_name": "PostHog/code"},
            {"id": 4, "name": "posthog-python", "full_name": "PostHog/posthog-python"},
        ]
        integration = self.create_integration(
            {"installation_id": "INSTALL", "account": {"name": "PostHog"}},
            {"access_token": "ACCESS_TOKEN"},
        )
        mock_list_all.return_value = fetched_repositories

        repos, has_more = GitHubIntegration(integration).list_cached_repositories(
            search=search, limit=limit, offset=offset
        )

        assert [repo["id"] for repo in repos] == expected_ids
        assert has_more is expected_has_more
        mock_list_all.assert_called_once_with()

    @patch("posthog.models.integration.GitHubIntegration.list_branches")
    @patch("posthog.models.integration.GitHubIntegration.get_default_branch")
    def test_list_cached_branches_uses_cached_data_when_fresh(self, mock_default_branch, mock_list_branches):
        integration = self.create_integration(
            {"installation_id": "INSTALL", "account": {"name": "PostHog"}},
            {"access_token": "ACCESS_TOKEN"},
        )
        repo = "posthog/posthog"
        cache.set(
            GitHubIntegration(integration)._get_branch_cache_key(repo),
            {
                "branches": ["main", "develop", "feature/test"],
                "default_branch": "main",
                "updated_at": time.time(),
            },
        )

        labels = {
            "integration_id": str(integration.id),
            "cache": "branches",
            "repository": repo,
            "result": "hit",
        }
        previous_count = REGISTRY.get_sample_value("github_integration_cache_accesses_total", labels) or 0

        branches, default_branch, has_more = GitHubIntegration(integration).list_cached_branches(
            repo, limit=2, offset=1
        )

        assert branches == ["develop", "feature/test"]
        assert default_branch == "main"
        assert has_more is False
        mock_list_branches.assert_not_called()
        mock_default_branch.assert_not_called()
        assert REGISTRY.get_sample_value("github_integration_cache_accesses_total", labels) == previous_count + 1

    @patch("posthog.models.integration.GitHubIntegration.list_branches")
    @patch("posthog.models.integration.GitHubIntegration.get_default_branch")
    def test_list_cached_branches_filters_search_before_pagination(self, mock_default_branch, mock_list_branches):
        integration = self.create_integration(
            {"installation_id": "INSTALL", "account": {"name": "PostHog"}},
            {"access_token": "ACCESS_TOKEN"},
        )
        repo = "posthog/posthog"
        cache.set(
            GitHubIntegration(integration)._get_branch_cache_key(repo),
            {
                "branches": [
                    "main",
                    "feature/agent-cache",
                    "feature/agent-branch-search",
                    "fix/refresh-button",
                ],
                "default_branch": "main",
                "updated_at": time.time(),
            },
        )

        branches, default_branch, has_more = GitHubIntegration(integration).list_cached_branches(
            repo, search="feature/agent", limit=1, offset=1
        )

        assert branches == ["feature/agent-branch-search"]
        assert default_branch == "main"
        assert has_more is False
        mock_list_branches.assert_not_called()
        mock_default_branch.assert_not_called()

    @patch("posthog.models.integration.GitHubIntegration.list_branches")
    @patch("posthog.models.integration.GitHubIntegration.get_default_branch")
    def test_list_cached_branches_populates_cache_on_miss(self, mock_default_branch, mock_list_branches):
        integration = self.create_integration(
            {"installation_id": "INSTALL", "account": {"name": "PostHog"}},
            {"access_token": "ACCESS_TOKEN"},
        )
        repo = "posthog/posthog"
        mock_list_branches.return_value = (["develop", "feature/test"], False)
        mock_default_branch.return_value = "main"

        labels = {
            "integration_id": str(integration.id),
            "cache": "branches",
            "repository": repo,
            "result": "miss",
        }
        previous_count = REGISTRY.get_sample_value("github_integration_cache_accesses_total", labels) or 0

        branches, default_branch, has_more = GitHubIntegration(integration).list_cached_branches(
            repo, limit=2, offset=0
        )

        cached = cache.get(GitHubIntegration(integration)._get_branch_cache_key(repo))
        assert branches == ["develop", "feature/test"]
        assert default_branch == "main"
        assert has_more is False
        assert cached["branches"] == ["develop", "feature/test"]
        assert cached["default_branch"] == "main"
        mock_list_branches.assert_called_once_with(repo, limit=100, offset=0)
        mock_default_branch.assert_called_once_with(repo)
        assert REGISTRY.get_sample_value("github_integration_cache_accesses_total", labels) == previous_count + 1

    @patch("posthog.models.integration.GitHubIntegration.list_branches")
    @patch("posthog.models.integration.GitHubIntegration.get_default_branch")
    def test_list_cached_branches_returns_stale_cache_on_refresh_error(self, mock_default_branch, mock_list_branches):
        integration = self.create_integration(
            {"installation_id": "INSTALL", "account": {"name": "PostHog"}},
            {"access_token": "ACCESS_TOKEN"},
        )
        repo = "posthog/posthog"
        cache.set(
            GitHubIntegration(integration)._get_branch_cache_key(repo),
            {
                "branches": ["main", "develop"],
                "default_branch": "main",
                "updated_at": time.time() - (GITHUB_BRANCH_CACHE_TTL_SECONDS + 1),
            },
        )
        mock_list_branches.side_effect = Exception("GitHub is slow")

        branches, default_branch, has_more = GitHubIntegration(integration).list_cached_branches(
            repo, limit=10, offset=0
        )

        assert branches == ["main", "develop"]
        assert default_branch == "main"
        assert has_more is False
        mock_list_branches.assert_called_once_with(repo, limit=100, offset=0)
        mock_default_branch.assert_not_called()

    @patch("posthog.models.integration.GitHubIntegration.list_branches")
    @patch("posthog.models.integration.GitHubIntegration.get_default_branch")
    def test_list_cached_branches_keeps_cached_default_branch_on_refresh_failure(
        self, mock_default_branch, mock_list_branches
    ):
        integration = self.create_integration(
            {"installation_id": "INSTALL", "account": {"name": "PostHog"}},
            {"access_token": "ACCESS_TOKEN"},
        )
        repo = "posthog/posthog"
        cache.set(
            GitHubIntegration(integration)._get_branch_cache_key(repo),
            {
                "branches": ["main", "develop"],
                "default_branch": "main",
                "updated_at": time.time() - (GITHUB_BRANCH_CACHE_TTL_SECONDS + 1),
            },
        )
        mock_list_branches.return_value = (["main", "develop", "feature/test"], False)
        mock_default_branch.side_effect = Exception("GitHub is slow")

        branches, default_branch, has_more = GitHubIntegration(integration).list_cached_branches(
            repo, limit=10, offset=0
        )

        cached = cache.get(GitHubIntegration(integration)._get_branch_cache_key(repo))
        assert branches == ["main", "develop", "feature/test"]
        assert default_branch == "main"
        assert has_more is False
        assert cached["branches"] == ["main", "develop", "feature/test"]
        assert cached["default_branch"] == "main"
        mock_list_branches.assert_called_once_with(repo, limit=100, offset=0)
        mock_default_branch.assert_called_once_with(repo)

    @patch("posthog.models.integration.GitHubIntegration.list_branches")
    def test_list_cached_branches_raises_on_refresh_error_without_cache(self, mock_list_branches):
        integration = self.create_integration(
            {"installation_id": "INSTALL", "account": {"name": "PostHog"}},
            {"access_token": "ACCESS_TOKEN"},
        )
        repo = "posthog/posthog"
        mock_list_branches.side_effect = Exception("GitHub is slow")

        with pytest.raises(Exception, match="GitHub is slow"):
            GitHubIntegration(integration).list_cached_branches(repo, limit=10, offset=0)

        mock_list_branches.assert_called_once_with(repo, limit=100, offset=0)

    @patch("posthog.models.integration.GitHubIntegration.list_branches")
    def test_list_all_branches_fetches_all_pages(self, mock_list_branches):
        integration = self.create_integration(
            {"installation_id": "INSTALL", "account": {"name": "PostHog"}},
            {"access_token": "ACCESS_TOKEN"},
        )
        repo = "posthog/posthog"
        first_page = [f"branch-{i}" for i in range(100)]
        second_page = [f"branch-{i}" for i in range(100, 230)]
        mock_list_branches.side_effect = [
            (first_page, True),
            (second_page, False),
        ]

        branches = GitHubIntegration(integration).list_all_branches(repo)

        assert branches == first_page + second_page
        assert mock_list_branches.call_args_list == [
            call(repo, limit=100, offset=0),
            call(repo, limit=100, offset=100),
        ]

    @patch("posthog.models.integration.GitHubIntegration.list_branches")
    @patch("posthog.models.integration.GitHubIntegration.get_default_branch")
    def test_list_cached_branches_pages_with_full_cached_snapshot(self, mock_default_branch, mock_list_branches):
        integration = self.create_integration(
            {"installation_id": "INSTALL", "account": {"name": "PostHog"}},
            {"access_token": "ACCESS_TOKEN"},
        )
        repo = "posthog/posthog"
        first_page = [f"branch-{i}" for i in range(100)]
        second_page = [f"branch-{i}" for i in range(100, 200)]
        remaining_branches = [f"branch-{i}" for i in range(200, 1500)]
        mock_list_branches.side_effect = [
            (first_page, True),
            (second_page, True),
            (remaining_branches, False),
        ]
        mock_default_branch.return_value = "branch-1200"

        branches, default_branch, has_more = GitHubIntegration(integration).list_cached_branches(
            repo, limit=25, offset=1200
        )

        expected_branches = ["branch-1199"] + [f"branch-{i}" for i in range(1201, 1225)]
        assert branches == expected_branches
        assert default_branch == "branch-1200"
        assert has_more is True
        assert mock_list_branches.call_args_list == [
            call(repo, limit=100, offset=0),
            call(repo, limit=100, offset=100),
            call(repo, limit=100, offset=200),
        ]

    # --- raise_if_github_rate_limited ---

    @parameterized.expand(
        [
            ("429_no_body", 429, "", True),
            ("403_rate_limit_body", 403, "API rate limit exceeded for installation", True),
            ("403_other_body", 403, "Forbidden", False),
            ("200_ok", 200, "", False),
            ("404_not_found", 404, "", False),
        ]
    )
    def test_raise_if_github_rate_limited_detection(self, _name, status_code, body, should_raise):
        response = MagicMock()
        response.status_code = status_code
        response.text = body
        response.headers = {}

        if should_raise:
            with pytest.raises(GitHubRateLimitError):
                raise_if_github_rate_limited(response)
        else:
            raise_if_github_rate_limited(response)  # must not raise

    @freeze_time("2024-01-01 12:00:00")
    def test_raise_if_github_rate_limited_populates_fields(self):
        reset_timestamp = int(time.time()) + 60
        response = MagicMock()
        response.status_code = 429
        response.text = ""
        response.headers = {
            "x-ratelimit-reset": str(reset_timestamp),
            "retry-after": "30",
        }

        with pytest.raises(GitHubRateLimitError) as exc_info:
            raise_if_github_rate_limited(response)

        assert exc_info.value.reset_at == reset_timestamp
        assert exc_info.value.retry_after == 30

    @freeze_time("2024-01-01 12:00:00")
    def test_raise_if_github_rate_limited_derives_retry_after_from_reset_at(self):
        reset_timestamp = int(time.time()) + 45
        response = MagicMock()
        response.status_code = 429
        response.text = ""
        response.headers = {"x-ratelimit-reset": str(reset_timestamp)}

        with pytest.raises(GitHubRateLimitError) as exc_info:
            raise_if_github_rate_limited(response)

        assert exc_info.value.retry_after == 45

    # --- exception hierarchy ---

    def test_github_rate_limit_error_is_integration_error(self):
        assert isinstance(GitHubRateLimitError("test"), GitHubIntegrationError)

    # --- get_access_token ---

    def test_get_access_token_returns_token_when_not_expired(self):
        integration = self.create_integration(
            config={"expires_in": 3600, "refreshed_at": int(time.time())},
            sensitive_config={"access_token": "valid-token"},
        )
        github = GitHubIntegration(integration)
        assert github.get_access_token() == "valid-token"

    @patch("posthog.models.github_integration_base.GitHubIntegrationBase.client_request")
    @patch("posthog.models.integration.reload_integrations_on_workers")
    def test_get_access_token_refreshes_when_expired(self, mock_reload, mock_client_request):
        integration = self.create_integration(
            config={"expires_in": 3600, "refreshed_at": int(time.time()) - 7200},  # expired: refreshed 2h ago
            sensitive_config={"access_token": "old-token"},
        )
        mock_response = MagicMock()
        mock_response.status_code = 201
        dt = datetime.now(UTC) + timedelta(hours=1)
        mock_response.json.return_value = {
            "token": "new-token",
            "expires_at": dt.replace(tzinfo=None).isoformat(timespec="seconds") + "Z",
        }
        mock_client_request.return_value = mock_response

        github = GitHubIntegration(integration)
        token = github.get_access_token()

        assert token == "new-token"
        mock_client_request.assert_called_once()

    def test_get_access_token_raises_when_token_missing_after_refresh(self):
        integration = self.create_integration(
            config={"expires_in": 3600, "refreshed_at": int(time.time())},
            sensitive_config={},  # no access_token key
        )
        github = GitHubIntegration(integration)

        with pytest.raises(GitHubIntegrationError, match="Access token unavailable"):
            github.get_access_token()


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


class TestEmailIntegrationDomainValidation(BaseTest):
    @patch("products.workflows.backend.providers.SESProvider.create_email_domain")
    def test_successful_domain_creation_ses(self, mock_create_email_domain):
        mock_create_email_domain.return_value = {"status": "success", "domain": "successdomain.com"}
        config = {"email": "user@successdomain.com", "name": "Test User", "provider": "ses"}
        integration = EmailIntegration.create_native_integration(
            config, team_id=self.team.id, organization_id=str(self.organization.id), created_by=self.user
        )
        assert integration.team == self.team
        assert integration.config["email"] == "user@successdomain.com"
        assert integration.config["provider"] == "ses"
        assert integration.config["domain"] == "successdomain.com"
        assert integration.config["name"] == "Test User"
        assert integration.config["verified"] is False

    @patch("products.workflows.backend.providers.SESProvider.create_email_domain")
    @patch("products.workflows.backend.providers.SESProvider.verify_email_domain")
    def test_duplicate_domain_in_another_organization(self, mock_create_email_domain, mock_verify_email_domain):
        mock_create_email_domain.return_value = {"status": "success", "domain": "successdomain.com"}
        mock_verify_email_domain.return_value = {"status": "verified", "domain": "example.com"}
        # Create an integration with a domain in another organization
        other_org = Organization.objects.create(name="other org")
        other_team = Team.objects.create(organization=other_org, name="other team")
        config = {"email": "user@example.com", "name": "Test User"}
        EmailIntegration.create_native_integration(
            config, team_id=other_team.id, organization_id=str(other_org.id), created_by=self.user
        )

        # Attempt to create the same domain in a different organization should raise ValidationError
        with pytest.raises(ValidationError) as exc:
            EmailIntegration.create_native_integration(
                config, team_id=self.team.id, organization_id=str(self.organization.id), created_by=self.user
            )
        assert "already exists in another organization" in str(exc.value)

    @patch("products.workflows.backend.providers.SESProvider.create_email_domain")
    def test_duplicate_domain_in_same_organization_allowed(self, mock_create_email_domain):
        mock_create_email_domain.return_value = {"status": "success", "domain": "example.com"}
        # Create an integration with a domain in one team
        other_team = Team.objects.create(organization=self.organization, name="other team")
        config = {"email": "user@example.com", "name": "Test User"}
        integration1 = EmailIntegration.create_native_integration(
            config, team_id=other_team.id, organization_id=str(self.organization.id), created_by=self.user
        )

        # Creating the same domain in a different team in the same organization should succeed
        integration2 = EmailIntegration.create_native_integration(
            config, team_id=self.team.id, organization_id=str(self.organization.id), created_by=self.user
        )

        assert integration1.config["domain"] == "example.com"
        assert integration2.config["domain"] == "example.com"
        assert integration1.team_id == other_team.id
        assert integration2.team_id == self.team.id

    def test_unsupported_email_domain(self):
        # Test with a free email domain
        config = {"email": "user@gmail.com", "name": "Test User"}

        with pytest.raises(ValidationError) as exc:
            EmailIntegration.create_native_integration(
                config, team_id=self.team.id, organization_id=str(self.organization.id), created_by=self.user
            )
        assert "not supported" in str(exc.value)

        # Test with a disposable email domain
        disposable_domain = next(iter(disposable_email_domains_list))
        config = {"email": f"user@{disposable_domain}", "name": "Test User"}

        with pytest.raises(ValidationError) as exc:
            EmailIntegration.create_native_integration(
                config, team_id=self.team.id, organization_id=str(self.organization.id), created_by=self.user
            )
        assert disposable_domain in str(exc.value)
        assert "not supported" in str(exc.value)


class TestGitLabIntegrationSSRFProtection:
    """Test SSRF protections in GitLabIntegration."""

    @patch("posthog.models.integration.requests.get")
    @patch("posthog.models.integration.is_url_allowed")
    def test_get_uses_allow_redirects_false(self, mock_is_url_allowed, mock_get):
        """GET requests must use allow_redirects=False to prevent redirect-based SSRF bypass."""
        from posthog.models.integration import GitLabIntegration

        mock_is_url_allowed.return_value = (True, None)
        mock_get.return_value.json.return_value = {"data": "test"}

        GitLabIntegration.get("https://gitlab.com", "projects/1", "token123")

        mock_get.assert_called_once()
        call_kwargs = mock_get.call_args.kwargs
        assert call_kwargs.get("allow_redirects") is False, "GET must use allow_redirects=False for SSRF protection"

    @patch("posthog.models.integration.requests.post")
    @patch("posthog.models.integration.is_url_allowed")
    def test_post_uses_allow_redirects_false(self, mock_is_url_allowed, mock_post):
        """POST requests must use allow_redirects=False to prevent redirect-based SSRF bypass."""
        from posthog.models.integration import GitLabIntegration

        mock_is_url_allowed.return_value = (True, None)
        mock_post.return_value.json.return_value = {"data": "test"}

        GitLabIntegration.post("https://gitlab.com", "projects/1/issues", "token123", {"title": "test"})

        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args.kwargs
        assert call_kwargs.get("allow_redirects") is False, "POST must use allow_redirects=False for SSRF protection"

    @patch("posthog.models.integration.requests.get")
    @patch("posthog.models.integration.is_url_allowed")
    def test_get_validates_url_before_request(self, mock_is_url_allowed, mock_get):
        """URL validation must happen before the request is made."""
        from posthog.models.integration import GitLabIntegration, GitLabIntegrationError

        mock_is_url_allowed.return_value = (False, "Private IP address not allowed")

        with pytest.raises(GitLabIntegrationError, match="Invalid GitLab hostname"):
            GitLabIntegration.get("http://192.168.1.1", "projects/1", "token123")

        mock_get.assert_not_called()

    @patch("posthog.models.integration.requests.post")
    @patch("posthog.models.integration.is_url_allowed")
    def test_post_validates_url_before_request(self, mock_is_url_allowed, mock_post):
        """URL validation must happen before the request is made."""
        from posthog.models.integration import GitLabIntegration, GitLabIntegrationError

        mock_is_url_allowed.return_value = (False, "Private IP address not allowed")

        with pytest.raises(GitLabIntegrationError, match="Invalid GitLab hostname"):
            GitLabIntegration.post("http://192.168.1.1", "projects/1/issues", "token123", {"title": "test"})

        mock_post.assert_not_called()


class TestPostgreSQLIntegrationModel(BaseTest):
    @parameterized.expand(
        [
            (
                "require_no_cert",
                {"ssl_mode": "require"},
                {},
                TLS(ssl_mode="require", ssl_root_cert=MISSING_CERT_PATH),
            ),
            (
                "require_system_cert",
                {"ssl_mode": "require", "ssl_root_cert": "system"},
                {},
                TLS(ssl_mode="require", ssl_root_cert="system"),
            ),
            (
                "verify_ca_with_cert",
                {
                    "ssl_mode": "verify-ca",
                    "ssl_root_cert": "-----BEGIN CERTIFICATE-----\nfake\n-----END CERTIFICATE-----",
                },
                {},
                TLS(
                    ssl_mode="verify-ca",
                    ssl_root_cert="-----BEGIN CERTIFICATE-----\nfake\n-----END CERTIFICATE-----",
                ),
            ),
            (
                "prefer_no_cert",
                {"ssl_mode": "prefer"},
                {},
                TLS(ssl_mode="prefer", ssl_root_cert=MISSING_CERT_PATH),
            ),
        ]
    )
    def test_tls_with_ssl_configs(self, _name, config_overrides, sensitive_config_overrides, expected_tls):
        config = {"host": "db.example.com", "port": 5432, "user": "exporter"}
        config.update(config_overrides)

        sensitive_config: dict = {"password": "hunter2"}
        sensitive_config.update(sensitive_config_overrides)

        integration = Integration.objects.create(
            team=self.team,
            kind=Integration.IntegrationKind.POSTGRESQL,
            integration_id=f"{self.team.pk}-db.example.com-5432-exporter",
            config=config,
            sensitive_config=sensitive_config,
        )

        pq = PostgreSQLIntegration(integration)
        assert pq.tls() == expected_tls

    @parameterized.expand(
        [
            (
                "defaults",
                {},
                TLS(ssl_mode="require", ssl_root_cert=MISSING_CERT_PATH),
            ),
            (
                "system_cert",
                {"ssl_root_cert": "system"},
                TLS(ssl_mode="require", ssl_root_cert="system"),
            ),
            (
                "verify_full_with_cert",
                {"ssl_mode": "verify-full", "ssl_root_cert": "cert-data"},
                TLS(ssl_mode="verify-full", ssl_root_cert="cert-data"),
            ),
        ]
    )
    def test_integration_from_config(self, _name, overrides, expected_tls):
        kwargs = {
            "team_id": self.team.pk,
            "host": "db.example.com",
            "port": 5432,
            "user": "exporter",
            "password": "super-secret",
        }
        kwargs.update(overrides)

        integration = PostgreSQLIntegration.integration_from_config(**kwargs)  # type: ignore
        pq = PostgreSQLIntegration(integration)

        assert pq.authority() == Authority(host="db.example.com", port=5432)
        assert pq.credentials() == Credentials(user="exporter", password="super-secret")
        assert pq.tls() == expected_tls

        assert "password" not in integration.config

        assert integration.sensitive_config["password"] == "super-secret"
