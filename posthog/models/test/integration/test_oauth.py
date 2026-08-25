"""Tests for the generic OAuth connect/refresh dispatcher, including kinds with no dedicated business-logic class (Resend, Pardot, YouTube Analytics, PostHog connect)."""

import json
import time
import base64
import hashlib
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import parse_qs, urlencode

import pytest
from freezegun import freeze_time
from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.db import connection
from django.test import override_settings

import requests
from parameterized import parameterized
from rest_framework.exceptions import ValidationError

from posthog.models.integration import (
    CONFIG_LEGACY_OAUTH_CLIENT,
    POSTHOG_CONNECT_DEFAULT_SCOPES,
    POSTHOG_CONNECT_IDENTITY_SCOPES,
    Integration,
    OauthIntegration,
    oauth_refresh_failure_reason,
    oauth_refresh_terminal_counter,
    refresh_backoff_active,
)


def get_db_field_value(field, model_id):
    cursor = connection.cursor()
    cursor.execute(f"select {field} from posthog_integration where id='{model_id}';")
    return cursor.fetchone()[0]


def test_slack_oauth_requests_the_recently_approved_scopes_on_every_instance():
    # These waited on Slack app-directory review and were only requested on DEV/local. They're
    # approved now, so every instance asks for them — the features behind them (DM assistant,
    # canvas and file artifact delivery, inbox channel creation) are dark without them.
    from posthog.models.integration import POSTHOG_SLACK_SCOPE

    requested = set(POSTHOG_SLACK_SCOPE.split(","))

    assert {"assistant:write", "im:history", "canvases:write", "files:write", "channels:manage"} <= requested


class TestOauthIntegrationModel(BaseTest):
    mock_settings = {
        "SALESFORCE_CONSUMER_KEY": "salesforce-client-id",
        "SALESFORCE_CONSUMER_SECRET": "salesforce-client-secret",
        "HUBSPOT_APP_CLIENT_ID": "hubspot-client-id",
        "HUBSPOT_APP_CLIENT_SECRET": "hubspot-client-secret",
        "GOOGLE_ADS_APP_CLIENT_ID": "google-client-id",
        "GOOGLE_ADS_APP_CLIENT_SECRET": "google-client-secret",
        "GOOGLE_CALENDAR_APP_CLIENT_ID": "google-calendar-client-id",
        "GOOGLE_CALENDAR_APP_CLIENT_SECRET": "google-calendar-client-secret",
        "LINKEDIN_APP_CLIENT_ID": "linkedin-client-id",
        "LINKEDIN_APP_CLIENT_SECRET": "linkedin-client-secret",
        "TIKTOK_ADS_CLIENT_ID": "tiktok-app-id",
        "TIKTOK_ADS_CLIENT_SECRET": "tiktok-secret",
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
            base, _, query = url.partition("?")
            params = {k: v[0] for k, v in parse_qs(query).items()}
            assert base == "https://login.salesforce.com/services/oauth2/authorize"
            assert params == {
                "client_id": "salesforce-client-id",
                "scope": "full refresh_token",
                "redirect_uri": "https://localhost:8010/integrations/salesforce/callback",
                "response_type": "code",
                "state": "next=%2Fprojects%2Ftest&token=state_token",
                "code_challenge": params["code_challenge"],
                "code_challenge_method": "S256",
            }

    def test_authorize_url_carries_initiating_team_id_in_state(self):
        with self.settings(**self.mock_settings):
            url = OauthIntegration.authorize_url(
                "salesforce", token="state_token", next="/projects/test", team_id=228502
            )
            params = {k: v[0] for k, v in parse_qs(url.partition("?")[2]).items()}
            state = {k: v[0] for k, v in parse_qs(params["state"]).items()}
            assert state["team_id"] == "228502"

    def test_authorize_url_omits_team_id_when_not_provided(self):
        with self.settings(**self.mock_settings):
            url = OauthIntegration.authorize_url("salesforce", token="state_token", next="/projects/test")
            params = {k: v[0] for k, v in parse_qs(url.partition("?")[2]).items()}
            assert "team_id" not in parse_qs(params["state"])

    def test_authorize_url_pkce_challenge_matches_cached_verifier(self):
        with self.settings(**self.mock_settings):
            url = OauthIntegration.authorize_url("salesforce", token="pkce_state_token", next="/projects/test")
            params = {k: v[0] for k, v in parse_qs(url.partition("?")[2]).items()}
            verifier = cache.get("oauth_pkce_verifier/pkce_state_token")
            assert verifier
            expected_challenge = (
                base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
            )
            assert params["code_challenge"] == expected_challenge

    def test_authorize_url_without_pkce_has_no_challenge(self):
        with self.settings(**self.mock_settings):
            url = OauthIntegration.authorize_url("hubspot", token="no_pkce_state_token", next="/projects/test")
            assert "code_challenge" not in url
            assert cache.get("oauth_pkce_verifier/no_pkce_state_token") is None

    def test_authorize_url_with_additional_authorize_params(self):
        with self.settings(**self.mock_settings):
            url = OauthIntegration.authorize_url("google-ads", token="state_token", next="/projects/test")
            assert (
                url
                == "https://accounts.google.com/o/oauth2/v2/auth?client_id=google-client-id&scope=https%3A%2F%2Fwww.googleapis.com%2Fauth%2Fadwords+https%3A%2F%2Fwww.googleapis.com%2Fauth%2Fuserinfo.email&redirect_uri=https%3A%2F%2Flocalhost%3A8010%2Fintegrations%2Fgoogle-ads%2Fcallback&response_type=code&state=next%3D%252Fprojects%252Ftest%26token%3Dstate_token&access_type=offline&prompt=consent"
            )

    def test_authorize_url_google_calendar(self):
        with self.settings(**self.mock_settings):
            url = OauthIntegration.authorize_url("google-calendar", token="state_token", next="/projects/test")
            assert (
                url
                == "https://accounts.google.com/o/oauth2/v2/auth?client_id=google-calendar-client-id&scope=https%3A%2F%2Fwww.googleapis.com%2Fauth%2Fcalendar.readonly+https%3A%2F%2Fwww.googleapis.com%2Fauth%2Fgmail.readonly+https%3A%2F%2Fwww.googleapis.com%2Fauth%2Fuserinfo.email&redirect_uri=https%3A%2F%2Flocalhost%3A8010%2Fintegrations%2Fgoogle-calendar%2Fcallback&response_type=code&state=next%3D%252Fprojects%252Ftest%26token%3Dstate_token&access_type=offline&prompt=consent"
            )

    @patch("posthog.models.integration.oauth.requests.post")
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

    @patch("posthog.models.integration.oauth.requests.post")
    def test_integration_from_oauth_response_sends_pkce_verifier(self, mock_post):
        with self.settings(**self.mock_settings):
            mock_post.return_value.status_code = 200
            mock_post.return_value.json.return_value = {
                "access_token": "FAKES_ACCESS_TOKEN",
                "instance_url": "https://fake.salesforce.com",
                "expires_in": 3600,
            }

            # authorize_url caches the verifier; the exchange must send that exact value and consume it
            url = OauthIntegration.authorize_url("salesforce", token="exchange_state_token", next="/projects/test")
            challenge = parse_qs(url.partition("?")[2])["code_challenge"][0]
            verifier = cache.get("oauth_pkce_verifier/exchange_state_token")

            OauthIntegration.integration_from_oauth_response(
                "salesforce",
                self.team.id,
                self.user,
                {"code": "code", "state": "next=%2Fprojects%2Ftest&token=exchange_state_token"},
            )

            sent = mock_post.call_args.kwargs["data"]
            assert sent["code_verifier"] == verifier
            assert (
                base64.urlsafe_b64encode(hashlib.sha256(sent["code_verifier"].encode()).digest()).rstrip(b"=").decode()
                == challenge
            )
            assert cache.get("oauth_pkce_verifier/exchange_state_token") is None

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
    @patch("posthog.models.integration.oauth.requests.post")
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

    @patch("posthog.models.integration.oauth.requests.post")
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

    @patch("posthog.models.integration.oauth.requests.post")
    def test_tiktok_ads_oauth_without_advertiser_accounts_raises_validation_error(self, mock_post):
        # TikTok completes OAuth even when the user granted no advertiser account, leaving
        # `advertiser_ids` empty. That must surface as a ValidationError (→ 400 with an actionable
        # message) rather than the bare Exception (→ 500) the missing-id guard would otherwise raise.
        with self.settings(**self.mock_settings):
            mock_post.return_value.status_code = 200
            mock_post.return_value.json.return_value = {
                "code": 0,
                "data": {"access_token": "FAKE_ACCESS_TOKEN", "advertiser_ids": []},
            }

            with pytest.raises(ValidationError, match="ad accounts"):
                OauthIntegration.integration_from_oauth_response(
                    "tiktok-ads",
                    self.team.id,
                    self.user,
                    {"code": "code", "state": "next=/projects/test"},
                )

    @patch("posthog.models.integration.oauth.requests.post")
    @patch("posthog.models.integration.oauth.requests.get")
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

    @patch("posthog.models.integration.oauth.requests.post")
    def test_linkedin_integration_extracts_user_info_from_id_token(self, mock_post):
        """
        LinkedIn's /v2/userinfo endpoint has intermittent REVOKED_ACCESS_TOKEN errors,
        so we extract user info from the id_token JWT instead.
        """
        import json

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

    @patch("posthog.models.integration.oauth.reload_integrations_on_workers")
    @patch("posthog.models.integration.oauth.requests.post")
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
            timeout=10,
            allow_redirects=False,
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
    @patch("posthog.models.integration.oauth.reload_integrations_on_workers")
    @patch("posthog.models.integration.oauth.requests.post")
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

    @patch("posthog.models.integration.oauth.reload_integrations_on_workers")
    @patch("posthog.models.integration.oauth.requests.post")
    def test_tiktok_ads_refresh_uses_business_api_and_unwraps_data(self, mock_post, mock_reload):
        # TikTok Business API refreshes against its own endpoint with app_id/secret (JSON) and nests
        # the refreshed tokens under `data` — not the Login Kit client_key/open.tiktokapis.com flow.
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {
            "code": 0,
            "data": {"access_token": "REFRESHED_ACCESS_TOKEN", "refresh_token": "ROTATED_REFRESH_TOKEN"},
        }

        integration = self.create_integration(kind="tiktok-ads", config={"expires_in": 1000})

        with freeze_time("2024-01-01T14:00:00Z"):
            with self.settings(**self.mock_settings):
                OauthIntegration(integration).refresh_access_token()

        mock_post.assert_called_with(
            "https://business-api.tiktok.com/open_api/v1.3/oauth2/refresh_token/",
            json={
                "app_id": "tiktok-app-id",
                "secret": "tiktok-secret",
                "refresh_token": "REFRESH",
                "grant_type": "refresh_token",
            },
            headers={"Content-Type": "application/json"},
            timeout=10,
        )
        assert integration.sensitive_config["access_token"] == "REFRESHED_ACCESS_TOKEN"
        assert integration.sensitive_config["refresh_token"] == "ROTATED_REFRESH_TOKEN"

    @patch("posthog.models.integration.oauth.reload_integrations_on_workers")
    @patch("posthog.models.integration.oauth.requests.post")
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

    @patch("posthog.models.integration.oauth.reload_integrations_on_workers")
    @patch("posthog.models.integration.oauth.requests.post")
    def test_failed_refresh_leaves_stored_secrets_byte_identical(self, mock_post, mock_reload):
        # A failed refresh has no new secrets to store, and rewriting the ones already there is how
        # a secret that couldn't be decrypted (handed back as raw ciphertext by
        # `ignore_decrypt_errors`) gains a permanent extra encryption layer.
        mock_post.return_value.status_code = 401
        mock_post.return_value.json.return_value = {"error": "BROKEN"}

        integration = self.create_integration(kind="hubspot", config={"expires_in": 1000})
        stored_before = get_db_field_value("sensitive_config", integration.id)

        with self.settings(**self.mock_settings):
            OauthIntegration(integration).refresh_access_token()

        assert get_db_field_value("sensitive_config", integration.id) == stored_before
        assert integration.errors == "TOKEN_REFRESH_FAILED"

    @patch("posthog.models.integration.oauth.requests.post")
    def test_refresh_with_unreadable_secret_goes_terminal_without_calling_the_provider(self, mock_post):
        # Posting ciphertext as the refresh token just earns an invalid_grant every minute forever.
        # Nothing about the stored secret can change, so the sweep must stop and the reconnect
        # prompt must show instead.
        integration = self.create_integration(kind="hubspot", sensitive_config={"refresh_token": "gAAAAAleftover=="})

        with self.settings(**self.mock_settings):
            OauthIntegration(integration).refresh_access_token()

        mock_post.assert_not_called()
        assert integration.errors == "TOKEN_REFRESH_FAILED"
        assert refresh_backoff_active(integration) is True

        integration.refresh_from_db()
        assert integration.config["refresh_terminal"] is True

    def _mock_token_response(self, status_code: int, token: Optional[str]) -> MagicMock:
        response = MagicMock()
        response.status_code = status_code
        response.json.return_value = {"access_token": token, "expires_in": 1000} if token else {}
        response.text = "error"
        return response

    @parameterized.expand(
        [
            # Primary works: the fallback must not fire, even when configured, and the grant is no
            # longer tied to the legacy app - so the reconnect prompt must stop showing.
            ("primary_ok", True, [(200, "primary-token")], "primary-token", "", 1, True, False),
            # A token issued by the previous app only refreshes with the fallback pair. Flagging it
            # is what identifies the connections that break when the legacy app is retired.
            ("fallback_rescues", True, [(401, None), (200, "fallback-token")], "fallback-token", "", 2, False, True),
            # Both credentials failing still marks the integration errored so the reconnect banner shows.
            ("both_fail", True, [(401, None), (401, None)], None, "TOKEN_REFRESH_FAILED", 2, True, True),
            # Without a fallback configured, behavior is identical to before: a single attempt, no retry.
            ("no_fallback_no_retry", False, [(401, None)], None, "TOKEN_REFRESH_FAILED", 1, False, False),
        ]
    )
    def test_refresh_falls_back_to_previous_credentials(
        self,
        _name,
        has_fallback,
        responses,
        expected_token,
        expected_errors,
        expected_calls,
        initial_legacy_flag,
        expected_legacy_flag,
    ):
        fallbacks = {"bing-ads": {"client_id": "old-app-id", "client_secret": "old-app-secret"}} if has_fallback else {}
        config = {"expires_in": 1000}
        if initial_legacy_flag:
            config[CONFIG_LEGACY_OAUTH_CLIENT] = True
        integration = self.create_integration(kind="bing-ads", config=config)

        with (
            self.settings(
                BING_ADS_CLIENT_ID="new-app-id",
                BING_ADS_CLIENT_SECRET="new-app-secret",
                OAUTH_CLIENT_FALLBACKS=fallbacks,
            ),
            patch("posthog.models.integration.oauth.reload_integrations_on_workers"),
            patch(
                "posthog.models.integration.oauth.requests.post",
                side_effect=[self._mock_token_response(status, token) for status, token in responses],
            ) as mock_post,
        ):
            OauthIntegration(integration).refresh_access_token()

        integration.refresh_from_db()
        assert mock_post.call_count == expected_calls
        assert integration.errors == expected_errors
        assert integration.config.get(CONFIG_LEGACY_OAUTH_CLIENT, False) == expected_legacy_flag
        if expected_token is not None:
            assert integration.sensitive_config["access_token"] == expected_token

    @patch("posthog.models.integration.oauth.reload_integrations_on_workers")
    @patch("posthog.models.integration.oauth.requests.post")
    def test_refresh_network_error_marks_failed_without_raising(self, mock_post, mock_reload):
        # A timeout must not escape refresh_access_token: the Celery sweep would error out before
        # recording the failure, leaving the integration without a backoff or the reconnect state.
        mock_post.side_effect = requests.Timeout("timed out")
        integration = self.create_integration(kind="bing-ads", config={"expires_in": 1000})

        with self.settings(BING_ADS_CLIENT_ID="new-app-id", BING_ADS_CLIENT_SECRET="new-app-secret"):
            OauthIntegration(integration).refresh_access_token()

        integration.refresh_from_db()
        assert integration.errors == "TOKEN_REFRESH_FAILED"
        assert integration.config.get("refresh_failure_count") == 1
        assert integration.config.get("refresh_next_attempt_at")

    @patch("posthog.models.integration.oauth.reload_integrations_on_workers")
    @patch("posthog.models.integration.oauth.requests.post")
    def test_refresh_primary_network_error_still_tries_fallback(self, mock_post, mock_reload):
        # A network error on the primary credentials must not skip the fallback attempt.
        mock_post.side_effect = [requests.Timeout("timed out"), self._mock_token_response(200, "fallback-token")]
        integration = self.create_integration(kind="bing-ads", config={"expires_in": 1000})

        with self.settings(
            BING_ADS_CLIENT_ID="new-app-id",
            BING_ADS_CLIENT_SECRET="new-app-secret",
            OAUTH_CLIENT_FALLBACKS={"bing-ads": {"client_id": "old-app-id", "client_secret": "old-app-secret"}},
        ):
            OauthIntegration(integration).refresh_access_token()

        integration.refresh_from_db()
        assert mock_post.call_count == 2
        assert integration.errors == ""
        assert integration.sensitive_config["access_token"] == "fallback-token"

    @patch("posthog.models.integration.oauth.reload_integrations_on_workers")
    @patch("posthog.models.integration.oauth.requests.post")
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

    @parameterized.expand(
        [
            ("first_failure", 0, 120),
            ("second_failure", 1, 240),
            ("capped", 10, 3600),
        ]
    )
    @patch("posthog.models.integration.oauth.reload_integrations_on_workers")
    @patch("posthog.models.integration.oauth.requests.post")
    def test_refresh_failure_schedules_backoff(self, _name, prior_failures, expected_delay, mock_post, mock_reload):
        mock_post.return_value.status_code = 401
        mock_post.return_value.json.return_value = {"error": "BROKEN"}

        config: dict = {"expires_in": 1000}
        if prior_failures:
            config["refresh_failure_count"] = prior_failures
        integration = self.create_integration(kind="hubspot", config=config)

        with freeze_time("2024-01-01T14:00:00Z"):
            with self.settings(**self.mock_settings):
                OauthIntegration(integration).refresh_access_token()

        integration.refresh_from_db()
        assert integration.config["refresh_failure_count"] == prior_failures + 1
        assert integration.config["refresh_next_attempt_at"] == 1704117600 + expected_delay
        assert "refresh_terminal" not in integration.config

    @parameterized.expand(
        [
            # (error, prior total failures, prior invalid_grant streak, expect terminal)
            ("invalid_grant_below_threshold", "invalid_grant", 3, 3, False),
            ("invalid_grant_at_threshold", "invalid_grant", 4, 4, True),
            ("invalid_client_never_terminal", "invalid_client", 10, 0, False),
            # A single invalid_grant after a run of other failures must not go terminal - the
            # streak has to be invalid_grant all the way through
            ("mixed_failures_not_terminal", "invalid_grant", 4, 0, False),
        ]
    )
    @patch("posthog.models.integration.oauth.reload_integrations_on_workers")
    @patch("posthog.models.integration.oauth.requests.post")
    def test_refresh_failure_terminal_state(
        self, _name, error, prior_failures, prior_grant_streak, expected_terminal, mock_post, mock_reload
    ):
        mock_post.return_value.status_code = 400
        mock_post.return_value.json.return_value = {"error": error}

        config: dict = {"expires_in": 1000, "refresh_failure_count": prior_failures}
        if prior_grant_streak:
            config["refresh_invalid_grant_count"] = prior_grant_streak
        integration = self.create_integration(kind="hubspot", config=config)

        terminal_counter = oauth_refresh_terminal_counter.labels(kind="hubspot")
        counter_before = terminal_counter._value.get()

        with self.settings(**self.mock_settings):
            OauthIntegration(integration).refresh_access_token()

        integration.refresh_from_db()
        assert bool(integration.config.get("refresh_terminal")) is expected_terminal
        # The transition is the fleet die-off signal: exactly one increment when a row goes
        # terminal, none otherwise
        assert terminal_counter._value.get() - counter_before == (1 if expected_terminal else 0)

    @patch("posthog.models.integration.oauth.reload_integrations_on_workers")
    @patch("posthog.models.integration.oauth.requests.post")
    def test_already_terminal_row_does_not_recount_on_bypassing_refresh(self, mock_post, mock_reload):
        mock_post.return_value.status_code = 400
        mock_post.return_value.json.return_value = {"error": "invalid_grant"}

        # On-demand refreshes bypass the backoff, so a dead row can keep failing after the
        # transition - it must not inflate the die-off counter again
        integration = self.create_integration(
            kind="hubspot",
            config={
                "expires_in": 1000,
                "refresh_failure_count": 6,
                "refresh_invalid_grant_count": 6,
                "refresh_terminal": True,
            },
        )

        terminal_counter = oauth_refresh_terminal_counter.labels(kind="hubspot")
        counter_before = terminal_counter._value.get()

        with self.settings(**self.mock_settings):
            OauthIntegration(integration).refresh_access_token()

        integration.refresh_from_db()
        assert integration.config.get("refresh_terminal") is True
        assert terminal_counter._value.get() == counter_before

    @patch("posthog.models.integration.oauth.reload_integrations_on_workers")
    @patch("posthog.models.integration.oauth.requests.post")
    def test_non_invalid_grant_failure_resets_grant_streak(self, mock_post, mock_reload):
        mock_post.return_value.status_code = 503
        mock_post.return_value.json.return_value = {"error": "server_error"}

        integration = self.create_integration(
            kind="hubspot",
            config={"expires_in": 1000, "refresh_failure_count": 4, "refresh_invalid_grant_count": 4},
        )

        with self.settings(**self.mock_settings):
            OauthIntegration(integration).refresh_access_token()

        integration.refresh_from_db()
        assert "refresh_invalid_grant_count" not in integration.config
        assert "refresh_terminal" not in integration.config

    @patch("posthog.models.integration.oauth.reload_integrations_on_workers")
    @patch("posthog.models.integration.oauth.requests.post")
    def test_refresh_success_clears_backoff_state(self, mock_post, mock_reload):
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {"access_token": "REFRESHED_ACCESS_TOKEN", "expires_in": 1000}

        integration = self.create_integration(
            kind="hubspot",
            config={
                "expires_in": 1000,
                "refresh_failure_count": 5,
                "refresh_invalid_grant_count": 5,
                "refresh_next_attempt_at": 1704117600,
                "refresh_terminal": True,
            },
        )

        with self.settings(**self.mock_settings):
            OauthIntegration(integration).refresh_access_token()

        integration.refresh_from_db()
        assert "refresh_failure_count" not in integration.config
        assert "refresh_invalid_grant_count" not in integration.config
        assert "refresh_next_attempt_at" not in integration.config
        assert "refresh_terminal" not in integration.config

    @patch("posthog.models.integration.oauth.reload_integrations_on_workers")
    @patch("posthog.models.integration.oauth.requests.post")
    def test_refresh_failure_with_non_json_body_still_backs_off(self, mock_post, mock_reload):
        mock_post.return_value.status_code = 502
        mock_post.return_value.json.side_effect = ValueError("not json")
        mock_post.return_value.text = "<html>Bad Gateway</html>"

        integration = self.create_integration(kind="hubspot", config={"expires_in": 1000})

        with self.settings(**self.mock_settings):
            OauthIntegration(integration).refresh_access_token()

        integration.refresh_from_db()
        assert integration.errors == "TOKEN_REFRESH_FAILED"
        assert integration.config["refresh_failure_count"] == 1

    @parameterized.expand(
        [
            ("invalid_grant", 400, {"error": "invalid_grant"}, None, "invalid_grant"),
            ("invalid_client", 401, {"error": "invalid_client"}, None, "invalid_client"),
            ("server_error", 502, {}, None, "http_5xx"),
            ("other_4xx", 400, {"error": "temporarily_unavailable"}, None, "other"),
            ("non_string_error", 400, {"error": {"code": 1}}, None, "other"),
            ("reddit_dead_grant_shape", 400, {"message": "Bad Request", "error": 400}, "reddit-ads", "invalid_grant"),
            ("reddit_shape_on_other_kind", 400, {"message": "Bad Request", "error": 400}, "hubspot", "other"),
            ("reddit_5xx", 502, {"message": "Bad Gateway", "error": 502}, "reddit-ads", "http_5xx"),
            ("reddit_oauth_error_code", 400, {"error": "invalid_grant"}, "reddit-ads", "invalid_grant"),
            (
                "hubspot_dead_hub_shape",
                400,
                {"status": "BAD_HUB", "message": "missing or unknown hub id", "error": "access_denied"},
                "hubspot",
                "invalid_grant",
            ),
            (
                "hubspot_shape_on_other_kind",
                400,
                {"status": "BAD_HUB", "error": "access_denied"},
                "salesforce",
                "other",
            ),
            ("hubspot_bad_hub_5xx_is_outage", 502, {"status": "BAD_HUB"}, "hubspot", "http_5xx"),
            (
                "hubspot_bad_refresh_token_still_oauth_code",
                400,
                {"status": "BAD_REFRESH_TOKEN", "error": "invalid_grant"},
                "hubspot",
                "invalid_grant",
            ),
            ("rate_limited", 429, {"status": "error", "errorType": "RATE_LIMIT"}, "hubspot", "rate_limited"),
            ("rate_limited_any_kind", 429, {}, None, "rate_limited"),
            (
                "meta_dead_token",
                400,
                {
                    "error": {
                        "message": "Error validating access token: The session has been invalidated because the user changed their password.",
                        "type": "OAuthException",
                        "code": 190,
                        "error_subcode": 460,
                    }
                },
                "meta-ads",
                "invalid_grant",
            ),
            (
                "instagram_dead_token",
                400,
                {"error": {"type": "OAuthException", "code": 190}},
                "instagram",
                "invalid_grant",
            ),
            ("meta_shape_on_other_kind", 400, {"error": {"code": 190}}, "hubspot", "other"),
            ("meta_non_grant_error_code", 400, {"error": {"type": "OAuthException", "code": 10}}, "meta-ads", "other"),
            ("meta_190_5xx_is_outage", 502, {"error": {"code": 190}}, "meta-ads", "http_5xx"),
        ]
    )
    def test_oauth_refresh_failure_reason(self, _name, status_code, body, kind, expected):
        assert oauth_refresh_failure_reason(status_code, body, kind=kind) == expected

    @patch("posthog.models.integration.oauth.requests.post")
    def test_reconnect_clears_backoff_state(self, mock_post):
        # A customer re-authing must un-brick a terminal integration, or "please reconnect"
        # comms leave them permanently dead.
        with self.settings(**self.mock_settings):
            mock_post.return_value.status_code = 200
            # integration_from_oauth_response pops fields out of the response dict, so each call
            # needs a fresh one
            mock_post.return_value.json.side_effect = lambda: {
                "access_token": "FAKES_ACCESS_TOKEN",
                "refresh_token": "FAKE_REFRESH_TOKEN",
                "instance_url": "https://fake.salesforce.com",
                "expires_in": 3600,
            }
            oauth_payload = {"code": "code", "state": "next=/projects/test"}

            integration = OauthIntegration.integration_from_oauth_response(
                "salesforce", self.team.id, self.user, oauth_payload
            )
            integration.config.update(
                {"refresh_failure_count": 5, "refresh_next_attempt_at": 1704117600, "refresh_terminal": True}
            )
            integration.save()

            reconnected = OauthIntegration.integration_from_oauth_response(
                "salesforce", self.team.id, self.user, oauth_payload
            )

        assert reconnected.id == integration.id
        assert "refresh_failure_count" not in reconnected.config
        assert "refresh_next_attempt_at" not in reconnected.config
        assert "refresh_terminal" not in reconnected.config

    @patch("posthog.models.integration.oauth.requests.post")
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

    @patch("posthog.models.integration.oauth.reload_integrations_on_workers")
    @patch("posthog.models.integration.oauth.requests.post")
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

    @patch("posthog.models.integration.oauth.reload_integrations_on_workers")
    @patch("posthog.models.integration.oauth.requests.post")
    def test_salesforce_refresh_uses_instance_url_for_sandbox(self, mock_post, mock_reload):
        # Sandbox integrations are stored as kind="salesforce" (the sandbox is a token-exchange
        # fallback in the OAuth callback), so the config's instance_url is the only signal that
        # the refresh must go to test.salesforce.com or the org's own host rather than the
        # hardcoded prod token URL. Salesforce rejects a sandbox refresh_token posted to
        # login.salesforce.com, which shows up to users as "Authentication token could not be
        # refreshed. Please reconnect." within a few hours of connecting.
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {
            "access_token": "REFRESHED_ACCESS_TOKEN",
            "expires_in": 3600,
        }

        sandbox_instance_url = "https://ryan-co--sandbox.sandbox.my.salesforce.com"
        integration = self.create_integration(
            kind="salesforce",
            config={"instance_url": sandbox_instance_url},
        )

        with self.settings(**self.mock_settings):
            OauthIntegration(integration).refresh_access_token()

        assert integration.errors == ""
        assert integration.sensitive_config["access_token"] == "REFRESHED_ACCESS_TOKEN"

        called_url = mock_post.call_args.args[0]
        assert called_url == f"{sandbox_instance_url}/services/oauth2/token"

    @parameterized.expand(
        [
            ("attacker_https", "https://attacker.example.com"),
            ("attacker_lookalike_suffix", "https://salesforce.com.attacker.example"),
            ("attacker_lookalike_prefix", "https://acmesalesforce.com"),
            ("http_scheme_downgrade", "http://acme.my.salesforce.com"),
            ("with_userinfo", "https://user:pass@acme.my.salesforce.com"),
            ("with_port", "https://acme.my.salesforce.com:8443"),
            ("invalid_port_raises_valueerror", "https://acme.my.salesforce.com:abc"),
            ("garbage_value", "not a url"),
            ("empty_value", ""),
        ]
    )
    @patch("posthog.models.integration.oauth.reload_integrations_on_workers")
    @patch("posthog.models.integration.oauth.requests.post")
    def test_salesforce_refresh_rejects_untrusted_instance_url(self, _name, bad_instance_url, mock_post, mock_reload):
        # If a future write path (a partial_update action, an admin tool, a data migration)
        # lets an attacker set instance_url, the refresh must not POST client_secret +
        # refresh_token to that origin - the client_secret is fleet-wide and its leak forces
        # rotation and reconnect for every Salesforce integration. Any instance_url that isn't
        # an https .salesforce.com host falls back to the hardcoded prod token URL, and the
        # refresh must not follow redirects that would move the secret to another host.
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {
            "access_token": "REFRESHED_ACCESS_TOKEN",
            "expires_in": 3600,
        }

        integration = self.create_integration(
            kind="salesforce",
            config={"instance_url": bad_instance_url},
        )

        with self.settings(**self.mock_settings):
            OauthIntegration(integration).refresh_access_token()

        called_url = mock_post.call_args.args[0]
        assert called_url == "https://login.salesforce.com/services/oauth2/token"

        called_kwargs = mock_post.call_args.kwargs
        assert called_kwargs["allow_redirects"] is False

    @patch("posthog.models.integration.oauth.reload_integrations_on_workers")
    @patch("posthog.models.integration.oauth.requests.post")
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

    @patch("posthog.models.integration.oauth.requests.post")
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
            STRIPE_APP_SECRET_KEY="sk_live_secret",
            STRIPE_APP_OVERRIDE_AUTHORIZE_URL="",
        ):
            url = OauthIntegration.authorize_url("stripe", token="state_token", next="/projects/test")
            assert "client_id=ca_live_clientid" in url

    @patch("posthog.models.integration.oauth.reload_integrations_on_workers")
    @patch("posthog.models.integration.oauth.requests.post")
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

    @patch("posthog.models.integration.oauth.requests.post")
    def test_stripe_oauth_does_not_persist_is_sandbox(self, mock_post):
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {
            "access_token": "FAKE_ACCESS",
            "refresh_token": "FAKE_REFRESH",
            "stripe_user_id": "acct_live_1",
            "account_name": "Live Account",
            "expires_in": 3600,
        }

        with self.settings(
            STRIPE_APP_CLIENT_ID="ca_live_clientid",
            STRIPE_APP_SECRET_KEY="sk_live_secret",
        ):
            integration = OauthIntegration.integration_from_oauth_response(
                "stripe",
                self.team.id,
                self.user,
                {"code": "ac_live_code"},
            )

        assert "is_sandbox" not in integration.config


class TestPosthogConnectIntegration(BaseTest):
    connect_settings = {
        "POSTHOG_CONNECT_BASE_URL_US": "https://us.posthog.com",
        "POSTHOG_CONNECT_OAUTH_CLIENT_ID_US": "us-client-id",
        "POSTHOG_CONNECT_OAUTH_CLIENT_SECRET_US": "us-secret",
        "POSTHOG_CONNECT_BASE_URL_EU": "https://eu.posthog.com",
        "POSTHOG_CONNECT_OAUTH_CLIENT_ID_EU": "eu-client-id",
        "POSTHOG_CONNECT_OAUTH_CLIENT_SECRET_EU": "eu-secret",
        "POSTHOG_CONNECT_BASE_URL_DEV": "http://localhost:8000",
        "POSTHOG_CONNECT_OAUTH_CLIENT_ID_DEV": "dev-client-id",
        "POSTHOG_CONNECT_OAUTH_CLIENT_SECRET_DEV": "dev-secret",
    }

    @parameterized.expand(
        [
            ("US", "https://us.posthog.com/oauth/authorize", "us-client-id"),
            ("EU", "https://eu.posthog.com/oauth/authorize", "eu-client-id"),
            ("DEV", "http://localhost:8000/oauth/authorize", "dev-client-id"),
        ]
    )
    def test_authorize_url_targets_selected_region(self, region, expected_base, expected_client_id):
        with self.settings(**self.connect_settings):
            url = OauthIntegration.authorize_url(
                "posthog", token="tok", next="/projects/test", region=region, scopes=["task:read", "task:write"]
            )
            base, _, query = url.partition("?")
            params = {k: v[0] for k, v in parse_qs(query).items()}
            assert base == expected_base
            assert params["client_id"] == expected_client_id
            # User-selected scopes plus the always-appended identity scopes needed for /oauth/userinfo.
            assert params["scope"] == "task:read task:write openid email"
            # Host comes from SITE_URL, which differs by environment; assert the stable callback suffix.
            assert params["redirect_uri"].endswith("/integrations/posthog/callback")
            # posthog uses PKCE
            assert params["code_challenge_method"] == "S256"
            # Region is carried in state so the callback (on the connecting cell) exchanges the code
            # against the correct target cell.
            state = {k: v[0] for k, v in parse_qs(params["state"]).items()}
            assert state["region"] == region
            assert state["token"] == "tok"

    def test_authorize_url_lowercases_region_input(self):
        with self.settings(**self.connect_settings):
            url = OauthIntegration.authorize_url("posthog", token="tok", region="eu", scopes=["task:read"])
            assert url.startswith("https://eu.posthog.com/oauth/authorize")
            outer = {k: v[0] for k, v in parse_qs(url.partition("?")[2]).items()}
            state = {k: v[0] for k, v in parse_qs(outer["state"]).items()}
            assert state["region"] == "EU"

    def test_authorize_url_defaults_to_task_scopes_when_none_selected(self):
        with self.settings(**self.connect_settings):
            url = OauthIntegration.authorize_url("posthog", token="tok", region="US", scopes=None)
            params = {k: v[0] for k, v in parse_qs(url.partition("?")[2]).items()}
            expected = " ".join([*POSTHOG_CONNECT_DEFAULT_SCOPES, *POSTHOG_CONNECT_IDENTITY_SCOPES])
            assert params["scope"] == expected

    def test_authorize_url_unknown_region_raises(self):
        with self.settings(**self.connect_settings):
            with pytest.raises(NotImplementedError):
                OauthIntegration.authorize_url("posthog", token="tok", region="ASIA", scopes=["task:read"])

    def test_authorize_url_unconfigured_region_raises(self):
        unconfigured = {
            **self.connect_settings,
            "POSTHOG_CONNECT_OAUTH_CLIENT_ID_EU": "",
            "POSTHOG_CONNECT_OAUTH_CLIENT_SECRET_EU": "",
        }
        with self.settings(**unconfigured):
            with pytest.raises(NotImplementedError):
                OauthIntegration.authorize_url("posthog", token="tok", region="EU", scopes=["task:read"])

    @patch("posthog.models.integration.oauth.requests.get")
    @patch("posthog.models.integration.oauth.requests.post")
    def test_integration_from_oauth_response_persists_region_and_namespaces_id(self, mock_post, mock_get):
        with self.settings(**self.connect_settings):
            mock_post.return_value = MagicMock(status_code=200)
            mock_post.return_value.json.return_value = {
                "access_token": "AT",
                "refresh_token": "RT",
                "expires_in": 3600,
                "scope": "task:read task:write openid email",
            }
            mock_get.return_value = MagicMock(status_code=200)
            mock_get.return_value.json.return_value = {"sub": "user-uuid-123", "email": "person@posthog.com"}

            # posthog is a PKCE flow; the authorize step caches a verifier keyed on the state token.
            cache.set("oauth_pkce_verifier/tok", "the-verifier")
            state = urlencode({"next": "/", "token": "tok", "region": "EU"})
            integration = OauthIntegration.integration_from_oauth_response(
                "posthog", self.team.id, self.user, {"code": "auth-code", "state": state}
            )

            # Token exchange must hit the region carried in state.
            assert mock_post.call_args[0][0] == "https://eu.posthog.com/oauth/token"
            assert integration.kind == "posthog"
            assert integration.config["region"] == "EU"
            # Dedup key is namespaced by region so the same account in two cells doesn't collide.
            assert integration.integration_id == "EU:user-uuid-123"
            assert integration.config["email"] == "person@posthog.com"
            # Only the resource scopes are persisted (identity scopes dropped), for the caller-scope check.
            assert integration.config["granted_scopes"] == ["task:read", "task:write"]
            assert integration.sensitive_config["access_token"] == "AT"
            assert integration.sensitive_config["refresh_token"] == "RT"

    @patch("posthog.models.integration.oauth.requests.post")
    def test_integration_from_oauth_response_fails_closed_without_pkce_verifier(self, mock_post):
        # No cached verifier (as if the authorize step was skipped / replayed). A first-party posthog
        # flow must fail closed rather than exchange the code without PKCE.
        with self.settings(**self.connect_settings):
            cache.delete("oauth_pkce_verifier/tok")
            state = urlencode({"next": "/", "token": "tok", "region": "EU"})
            with pytest.raises(ValidationError):
                OauthIntegration.integration_from_oauth_response(
                    "posthog", self.team.id, self.user, {"code": "auth-code", "state": state}
                )
            mock_post.assert_not_called()

    @patch("posthog.models.integration.oauth.requests.post")
    def test_refresh_access_token_uses_persisted_region(self, mock_post):
        with self.settings(**self.connect_settings):
            integration = Integration.objects.create(
                team=self.team,
                kind="posthog",
                integration_id="EU:user-uuid-123",
                config={"region": "EU", "refreshed_at": int(time.time()) - 4000, "expires_in": 3600},
                sensitive_config={"refresh_token": "RT", "access_token": "OLD"},
            )
            mock_post.return_value = MagicMock(status_code=200)
            mock_post.return_value.json.return_value = {
                "access_token": "NEW",
                "refresh_token": "RT2",
                "expires_in": 3600,
            }

            OauthIntegration(integration).refresh_access_token()

            # Refresh must target the persisted region's token endpoint, not a static one.
            assert mock_post.call_args[0][0] == "https://eu.posthog.com/oauth/token"
            integration.refresh_from_db()
            assert integration.sensitive_config["access_token"] == "NEW"


def _make_resend_jwt(payload: dict) -> str:
    body = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()
    return f"header.{body}.signature"


@override_settings(RESEND_APP_CLIENT_ID="resend-client-id", RESEND_APP_CLIENT_SECRET="resend-client-secret")
class TestResendIntegrationModel(BaseTest):
    def test_oauth_config(self):
        config = OauthIntegration.oauth_config_for_kind("resend")
        assert config.authorize_url == "https://resend.com/oauth/authorize"
        assert config.token_url == "https://api.resend.com/oauth/token"
        assert config.token_revoke_url == "https://api.resend.com/oauth/revoke"
        assert config.client_id == "resend-client-id"
        assert config.client_secret == "resend-client-secret"
        assert config.scope == "full_access"
        assert config.pkce is True
        assert config.id_path == "resend_account_id"

    @override_settings(RESEND_APP_CLIENT_ID="", RESEND_APP_CLIENT_SECRET="")
    def test_oauth_config_unconfigured_raises(self):
        with pytest.raises(NotImplementedError, match="Resend app not configured"):
            OauthIntegration.oauth_config_for_kind("resend")

    @patch("posthog.models.integration.oauth.requests.post")
    def test_integration_from_oauth_response_extracts_account_from_jwt(self, mock_post):
        access_token = _make_resend_jwt({"sub": "acct_123", "email": "team@acme.com"})
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {
            "access_token": access_token,
            "refresh_token": "rt_1",
            "expires_in": 900,
            "token_type": "Bearer",
        }

        with freeze_time("2024-01-01T12:00:00Z"):
            integration = OauthIntegration.integration_from_oauth_response(
                "resend",
                self.team.id,
                self.user,
                {"code": "code", "state": "token=state_token"},
            )

        assert integration.kind == "resend"
        assert integration.integration_id == "acct_123"
        assert integration.config["resend_account_id"] == "acct_123"
        assert integration.config["resend_account_name"] == "team@acme.com"
        assert integration.config["expires_in"] == 900
        assert integration.sensitive_config["access_token"] == access_token
        assert integration.sensitive_config["refresh_token"] == "rt_1"

    @patch("posthog.models.integration.oauth.requests.post")
    def test_integration_from_oauth_response_name_falls_back_without_email(self, mock_post):
        access_token = _make_resend_jwt({"sub": "acct_xyz"})
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {
            "access_token": access_token,
            "refresh_token": "rt",
            "expires_in": 900,
        }

        integration = OauthIntegration.integration_from_oauth_response(
            "resend",
            self.team.id,
            self.user,
            {"code": "code", "state": "token=state_token"},
        )

        assert integration.integration_id == "acct_xyz"
        assert integration.config["resend_account_name"] == "Resend account acct_xyz"

    @patch("posthog.models.integration.oauth.requests.post")
    def test_integration_from_oauth_response_without_sub_raises(self, mock_post):
        access_token = _make_resend_jwt({"email": "no-sub@acme.com"})
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {
            "access_token": access_token,
            "refresh_token": "rt",
            "expires_in": 900,
        }

        with pytest.raises(Exception, match="failed to extract integration ID"):
            OauthIntegration.integration_from_oauth_response(
                "resend",
                self.team.id,
                self.user,
                {"code": "code", "state": "token=state_token"},
            )

    @patch("posthog.models.integration.oauth.requests.post")
    def test_authorization_code_exchange_does_not_follow_redirects(self, mock_post):
        # A 307/308 from the token endpoint must not forward client_secret + code to its Location.
        access_token = _make_resend_jwt({"sub": "acct_1"})
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {
            "access_token": access_token,
            "refresh_token": "rt",
            "expires_in": 900,
        }

        OauthIntegration.integration_from_oauth_response(
            "resend",
            self.team.id,
            self.user,
            {"code": "code", "state": "token=state_token"},
        )

        assert mock_post.call_args.kwargs["allow_redirects"] is False

    @patch("posthog.models.integration.oauth.requests.post")
    def test_revoke_token_authenticates_with_client_credentials(self, mock_post):
        integration = Integration.objects.create(
            team=self.team,
            kind="resend",
            config={"resend_account_id": "acct_1"},
            sensitive_config={"refresh_token": "rt_secret", "access_token": "at_secret"},
        )

        OauthIntegration(integration).revoke_token()

        sent = mock_post.call_args.kwargs["data"]
        assert sent["token"] == "rt_secret"
        assert sent["client_id"] == "resend-client-id"
        assert sent["client_secret"] == "resend-client-secret"
        assert sent["token_type_hint"] == "refresh_token"


@override_settings(
    SALESFORCE_CONSUMER_KEY="salesforce-client-id", SALESFORCE_CONSUMER_SECRET="salesforce-client-secret"
)
class TestPardotIntegrationModel(BaseTest):
    def test_oauth_config_requests_the_account_engagement_scope(self):
        config = OauthIntegration.oauth_config_for_kind("pardot")

        assert config.authorize_url == "https://login.salesforce.com/services/oauth2/authorize"
        assert config.token_url == "https://login.salesforce.com/services/oauth2/token"
        assert config.token_revoke_url == "https://login.salesforce.com/services/oauth2/revoke"
        assert config.client_id == "salesforce-client-id"
        assert config.client_secret == "salesforce-client-secret"
        assert config.pkce is True
        assert config.id_path == "instance_url"
        # Salesforce's `full` scope does not cover the Account Engagement API, so a token
        # minted for the CRM kind cannot call it. That is why this kind exists at all.
        assert config.scope == "pardot_api refresh_token"
        assert config.scope != OauthIntegration.oauth_config_for_kind("salesforce").scope

    def test_pardot_is_an_oauth_kind(self):
        # Not being listed makes the authorize + callback endpoints reject the kind and drops
        # it out of the scheduled token refresh sweep.
        assert "pardot" in OauthIntegration.supported_kinds

    @override_settings(SALESFORCE_CONSUMER_KEY="", SALESFORCE_CONSUMER_SECRET="")
    def test_oauth_config_unconfigured_raises(self):
        with pytest.raises(NotImplementedError, match="Salesforce app not configured"):
            OauthIntegration.oauth_config_for_kind("pardot")

    @patch("posthog.models.integration.oauth.reload_integrations_on_workers")
    @patch("posthog.models.integration.oauth.requests.post")
    def test_refresh_uses_the_org_instance_host_and_assumes_an_hour(self, mock_post, mock_reload):
        # Account Engagement business units can live on a sandbox org, whose refresh token
        # login.salesforce.com rejects, and Salesforce often omits expires_in — without the
        # assumed hour the token is never treated as expired and syncs fail on a stale one.
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {"access_token": "REFRESHED_ACCESS_TOKEN"}

        instance_url = "https://acme--sandbox.sandbox.my.salesforce.com"
        integration = Integration.objects.create(
            team=self.team,
            kind="pardot",
            config={"instance_url": instance_url, "refreshed_at": int(time.time())},
            sensitive_config={"refresh_token": "REFRESH"},
        )

        OauthIntegration(integration).refresh_access_token()

        assert integration.errors == ""
        assert mock_post.call_args.args[0] == f"{instance_url}/services/oauth2/token"
        assert integration.sensitive_config["access_token"] == "REFRESHED_ACCESS_TOKEN"
        assert integration.config["expires_in"] == 3600

    @patch("posthog.models.integration.oauth.requests.post")
    def test_expiry_is_assumed_when_the_token_response_omits_it(self, mock_post):
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {
            "access_token": "at",
            "refresh_token": "rt",
            "instance_url": "https://acme.my.salesforce.com",
        }

        integration = OauthIntegration.integration_from_oauth_response(
            "pardot",
            self.team.id,
            self.user,
            {"code": "code", "state": "token=state_token"},
        )

        assert integration.integration_id == "https://acme.my.salesforce.com"
        assert integration.config["expires_in"] == 3600


@override_settings(
    YOUTUBE_ANALYTICS_APP_CLIENT_ID="youtube-client-id",
    YOUTUBE_ANALYTICS_APP_CLIENT_SECRET="youtube-client-secret",
)
class TestYouTubeAnalyticsIntegrationModel(BaseTest):
    def test_oauth_config(self):
        config = OauthIntegration.oauth_config_for_kind("youtube-analytics")

        assert config.authorize_url == "https://accounts.google.com/o/oauth2/v2/auth"
        assert config.token_url == "https://oauth2.googleapis.com/token"
        assert config.client_id == "youtube-client-id"
        assert config.client_secret == "youtube-client-secret"
        assert config.id_path == "sub"
        assert config.name_path == "email"
        # A refresh token only comes back when consent is forced, and the sync depends on one.
        assert config.additional_authorize_params == {"access_type": "offline", "prompt": "consent"}

    def test_oauth_config_requests_analytics_and_channel_read_scopes(self):
        scopes = set(OauthIntegration.oauth_config_for_kind("youtube-analytics").scope.split())

        assert "https://www.googleapis.com/auth/yt-analytics.readonly" in scopes
        assert "https://www.googleapis.com/auth/youtube.readonly" in scopes
        # Channel reports carry no revenue metrics, so the monetary scope is never asked for.
        assert "https://www.googleapis.com/auth/yt-analytics-monetary.readonly" not in scopes

    @override_settings(YOUTUBE_ANALYTICS_APP_CLIENT_ID="", YOUTUBE_ANALYTICS_APP_CLIENT_SECRET="")
    def test_oauth_config_unconfigured_raises(self):
        with pytest.raises(NotImplementedError, match="YouTube Analytics app not configured"):
            OauthIntegration.oauth_config_for_kind("youtube-analytics")
