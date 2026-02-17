import json
from urllib.parse import parse_qs, urlparse

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.conf import settings
from django.test import RequestFactory, override_settings

import requests
from parameterized import parameterized
from rest_framework import status
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.request import Request

from posthog.api.oauth.toolbar_service import (
    CALLBACK_PATH,
    ToolbarOAuthError,
    get_or_create_toolbar_oauth_application,
    toolbar_oauth_state_cache,
)
from posthog.auth import TemporaryTokenAuthentication
from posthog.models import Organization, Team, User


class TestToolbarOAuthPrimitives(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.team.app_urls = ["https://example.com"]
        self.team.save()

    def _start(self) -> dict:
        response = self.client.post(
            "/api/user/toolbar_oauth_start/",
            data=json.dumps(
                {
                    "app_url": self.team.app_urls[0],
                    "code_challenge": "test_challenge_value",
                    "code_challenge_method": "S256",
                    "user_intent": "edit-action",
                }
            ),
            content_type="application/json",
        )
        assert response.status_code == status.HTTP_200_OK, response.content
        return response.json()

    def test_start_requires_authentication(self):
        self.client.logout()
        response = self.client.post(
            "/api/user/toolbar_oauth_start/",
            data=json.dumps(
                {
                    "app_url": self.team.app_urls[0],
                    "code_challenge": "x",
                    "code_challenge_method": "S256",
                }
            ),
            content_type="application/json",
        )
        assert response.status_code == 401

    def test_exchange_requires_authentication(self):
        self.client.logout()
        response = self.client.post(
            "/api/user/toolbar_oauth_exchange/",
            data=json.dumps({"code": "c", "state": "s", "code_verifier": "v"}),
            content_type="application/json",
        )
        assert response.status_code == 401

    def test_callback_anonymous_user_gets_relay_not_exchange(self):
        self.client.logout()
        response = self.client.get("/toolbar_oauth/callback?code=c&state=s")
        # Anonymous users hit the relay path (no code_verifier in session), not the exchange path
        assert response.status_code == 200
        assert b'"type": "toolbar_oauth_result"' in response.content

    def test_start_returns_authorization_url(self):
        data = self._start()
        assert "authorization_url" in data

        parsed = urlparse(data["authorization_url"])
        qs = parse_qs(parsed.query)
        expected = urlparse(settings.SITE_URL)
        assert parsed.scheme == expected.scheme
        assert parsed.netloc == expected.netloc
        assert qs["redirect_uri"][0] == f"{settings.SITE_URL}{CALLBACK_PATH}"
        assert "state" in qs
        assert qs["code_challenge_method"][0] == "S256"

    def test_start_rejects_unallowed_url(self):
        response = self.client.post(
            "/api/user/toolbar_oauth_start/",
            data=json.dumps(
                {
                    "app_url": "https://not-allowed.example.com",
                    "code_challenge": "test_challenge_value",
                    "code_challenge_method": "S256",
                }
            ),
            content_type="application/json",
        )
        assert response.status_code == 403

    def test_start_rejects_insecure_non_loopback_app_url(self):
        response = self.client.post(
            "/api/user/toolbar_oauth_start/",
            data=json.dumps(
                {
                    "app_url": "http://example.com",
                    "code_challenge": "test_challenge_value",
                    "code_challenge_method": "S256",
                }
            ),
            content_type="application/json",
        )
        assert response.status_code == 400
        assert response.json()["code"] == "invalid_app_url"

    def test_start_allows_http_loopback_app_url(self):
        self.team.app_urls = [*self.team.app_urls, "http://localhost:3000"]
        self.team.save(update_fields=["app_urls"])

        response = self.client.post(
            "/api/user/toolbar_oauth_start/",
            data=json.dumps(
                {
                    "app_url": "http://localhost:3000",
                    "code_challenge": "test_challenge_value",
                    "code_challenge_method": "S256",
                }
            ),
            content_type="application/json",
        )
        assert response.status_code == 200, response.content

    @parameterized.expand(
        [
            ("invalid_json", "{not-json", "invalid_json"),
            (
                "invalid_code_challenge_method",
                json.dumps({"app_url": "https://example.com", "code_challenge": "x", "code_challenge_method": "plain"}),
                "invalid_request",
            ),
            (
                "missing_app_url",
                json.dumps({"code_challenge": "x", "code_challenge_method": "S256"}),
                "invalid_request",
            ),
            (
                "missing_code_challenge",
                json.dumps({"app_url": "https://example.com", "code_challenge_method": "S256"}),
                "invalid_request",
            ),
        ]
    )
    def test_start_rejects_bad_requests(self, _name, body, expected_code):
        response = self.client.post(
            "/api/user/toolbar_oauth_start/",
            data=body,
            content_type="application/json",
        )
        assert response.status_code == 400
        assert response.json()["code"] == expected_code

    def test_oauth_application_is_scoped_per_organization(self):
        first_app = get_or_create_toolbar_oauth_application(user=self.user)

        other_org = Organization.objects.create(name="Another org")
        other_user = User.objects.create_user(
            email="toolbar-oauth-another-org@example.com",
            first_name="Other",
            password="password",
        )
        other_org.members.add(other_user)
        second_app = get_or_create_toolbar_oauth_application(user=other_user)

        assert first_app.id != second_app.id
        assert first_app.organization == self.organization
        assert second_app.organization == other_org

    def test_oauth_application_uses_site_url_redirect_uri(self):
        app = get_or_create_toolbar_oauth_application(user=self.user)
        assert app.redirect_uris == f"{settings.SITE_URL}{CALLBACK_PATH}"

    def test_get_or_create_raises_for_user_without_organization(self):
        orphan = User.objects.create_user(
            email="toolbar-oauth-no-org@example.com",
            first_name="Orphan",
            password="password",
        )
        with self.assertRaises(ToolbarOAuthError) as cm:
            get_or_create_toolbar_oauth_application(user=orphan)
        assert cm.exception.code == "no_organization"

    def test_callback_renders_bridge_with_code_and_state(self):
        response = self.client.get("/toolbar_oauth/callback?code=test_code&state=test_state")

        assert response.status_code == 200
        assert b"openerWindow.postMessage" in response.content
        assert b'"code": "test_code"' in response.content
        assert b'"state": "test_state"' in response.content

    def test_callback_renders_bridge_with_error_payload(self):
        response = self.client.get(
            "/toolbar_oauth/callback?error=access_denied&error_description=user+cancelled&state=test_state"
        )

        assert response.status_code == 200
        assert b'"error": "access_denied"' in response.content
        assert b'"error_description": "user cancelled"' in response.content

    def test_callback_rejects_post_method(self):
        response = self.client.post("/toolbar_oauth/callback")
        assert response.status_code == 405

    @patch("posthog.api.oauth.toolbar_service.requests.post")
    def test_exchange_success(self, mock_post):
        start_data = self._start()
        state = parse_qs(urlparse(start_data["authorization_url"]).query)["state"][0]

        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {
            "access_token": "pha_abc",
            "refresh_token": "phr_abc",
            "token_type": "Bearer",
            "expires_in": 3600,
            "scope": "openid",
        }

        response = self.client.post(
            "/api/user/toolbar_oauth_exchange/",
            data=json.dumps({"code": "test_code", "state": state, "code_verifier": "test_verifier"}),
            content_type="application/json",
        )
        assert response.status_code == 200, response.content
        assert response.json()["access_token"] == "pha_abc"

    @patch("posthog.api.oauth.toolbar_service.requests.post")
    def test_exchange_rejects_missing_access_token_in_response(self, mock_post):
        start_data = self._start()
        state = parse_qs(urlparse(start_data["authorization_url"]).query)["state"][0]

        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {
            "token_type": "Bearer",
            "expires_in": 3600,
        }

        response = self.client.post(
            "/api/user/toolbar_oauth_exchange/",
            data=json.dumps({"code": "test_code", "state": state, "code_verifier": "test_verifier"}),
            content_type="application/json",
        )
        assert response.status_code == 502
        assert response.json()["code"] == "token_exchange_failed"

    @patch("posthog.api.oauth.toolbar_service.requests.post")
    def test_exchange_handles_network_failure(self, mock_post):
        start_data = self._start()
        state = parse_qs(urlparse(start_data["authorization_url"]).query)["state"][0]
        mock_post.side_effect = requests.RequestException("connection failed")

        response = self.client.post(
            "/api/user/toolbar_oauth_exchange/",
            data=json.dumps({"code": "test_code", "state": state, "code_verifier": "test_verifier"}),
            content_type="application/json",
        )
        assert response.status_code == 500
        assert response.json()["code"] == "token_exchange_failed"

    def test_exchange_rejects_tampered_state(self):
        start_data = self._start()
        state = parse_qs(urlparse(start_data["authorization_url"]).query)["state"][0]
        tampered_state = f"{state[:-1]}x"

        response = self.client.post(
            "/api/user/toolbar_oauth_exchange/",
            data=json.dumps({"code": "test_code", "state": tampered_state, "code_verifier": "test_verifier"}),
            content_type="application/json",
        )
        assert response.status_code == 400
        assert response.json()["code"] == "invalid_state"

    def test_exchange_rejects_state_user_mismatch(self):
        start_data = self._start()
        state = parse_qs(urlparse(start_data["authorization_url"]).query)["state"][0]

        other_user = User.objects.create_user(
            email="toolbar-oauth-other-user@example.com",
            first_name="Other",
            password="password",
            current_organization=self.organization,
            current_team=self.team,
        )
        self.organization.members.add(other_user)
        self.client.force_login(other_user)

        response = self.client.post(
            "/api/user/toolbar_oauth_exchange/",
            data=json.dumps({"code": "test_code", "state": state, "code_verifier": "test_verifier"}),
            content_type="application/json",
        )
        assert response.status_code == 400
        assert response.json()["code"] == "state_user_mismatch"

    def test_exchange_rejects_state_team_mismatch(self):
        start_data = self._start()
        state = parse_qs(urlparse(start_data["authorization_url"]).query)["state"][0]

        other_team = Team.objects.create(organization=self.organization, name="Different Team")
        self.user.current_team = other_team
        self.user.save(update_fields=["current_team"])
        self.client.force_login(self.user)

        response = self.client.post(
            "/api/user/toolbar_oauth_exchange/",
            data=json.dumps({"code": "test_code", "state": state, "code_verifier": "test_verifier"}),
            content_type="application/json",
        )
        assert response.status_code == 400
        assert response.json()["code"] == "state_team_mismatch"

    def test_exchange_rejects_invalid_json_body(self):
        response = self.client.post(
            "/api/user/toolbar_oauth_exchange/",
            data="{not-json",
            content_type="application/json",
        )
        assert response.status_code == 400
        assert response.json()["code"] == "invalid_json"

    @patch("posthog.api.oauth.toolbar_service.requests.post")
    def test_exchange_surfaces_token_error(self, mock_post):
        start_data = self._start()
        state = parse_qs(urlparse(start_data["authorization_url"]).query)["state"][0]

        mock_post.return_value.status_code = 400
        mock_post.return_value.json.return_value = {
            "error": "invalid_grant",
            "error_description": "Authorization code expired",
        }

        response = self.client.post(
            "/api/user/toolbar_oauth_exchange/",
            data=json.dumps({"code": "test_code", "state": state, "code_verifier": "test_verifier"}),
            content_type="application/json",
        )
        assert response.status_code == 400
        assert response.json()["code"] == "invalid_grant"

    @patch("posthog.api.oauth.toolbar_service.requests.post")
    def test_exchange_handles_non_json_token_response(self, mock_post):
        start_data = self._start()
        state = parse_qs(urlparse(start_data["authorization_url"]).query)["state"][0]

        mock_post.return_value.status_code = 502
        mock_post.return_value.content = b"not json"
        mock_post.return_value.json.side_effect = ValueError("No JSON")

        response = self.client.post(
            "/api/user/toolbar_oauth_exchange/",
            data=json.dumps({"code": "test_code", "state": state, "code_verifier": "test_verifier"}),
            content_type="application/json",
        )
        assert response.status_code == 502
        assert response.json()["code"] == "token_exchange_failed"

    @patch("posthog.api.oauth.toolbar_service.requests.post")
    def test_exchange_replay_fails(self, mock_post):
        start_data = self._start()
        state = parse_qs(urlparse(start_data["authorization_url"]).query)["state"][0]

        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {
            "access_token": "pha_abc",
            "refresh_token": "phr_abc",
            "token_type": "Bearer",
            "expires_in": 3600,
            "scope": "openid",
        }

        first = self.client.post(
            "/api/user/toolbar_oauth_exchange/",
            data=json.dumps({"code": "test_code", "state": state, "code_verifier": "test_verifier"}),
            content_type="application/json",
        )
        assert first.status_code == 200

        second = self.client.post(
            "/api/user/toolbar_oauth_exchange/",
            data=json.dumps({"code": "test_code", "state": state, "code_verifier": "test_verifier"}),
            content_type="application/json",
        )
        assert second.status_code == 400
        assert second.json()["code"] == "state_replay"

    @override_settings(TOOLBAR_OAUTH_STATE_TTL_SECONDS=0)
    def test_exchange_rejects_expired_state(self):
        start_data = self._start()
        state = parse_qs(urlparse(start_data["authorization_url"]).query)["state"][0]

        response = self.client.post(
            "/api/user/toolbar_oauth_exchange/",
            data=json.dumps({"code": "test_code", "state": state, "code_verifier": "test_verifier"}),
            content_type="application/json",
        )
        assert response.status_code == 400
        assert response.json()["code"] == "invalid_state"


class TestToolbarOAuthStateCache(APIBaseTest):
    def test_mark_pending_then_claim_succeeds(self):
        nonce = "test-nonce-claim-ok"
        toolbar_oauth_state_cache.mark_pending(nonce)
        toolbar_oauth_state_cache.claim_or_raise(nonce)

    def test_claim_without_pending_raises_state_not_found(self):
        with self.assertRaises(ToolbarOAuthError) as cm:
            toolbar_oauth_state_cache.claim_or_raise("nonce-never-pending")
        assert cm.exception.code == "state_not_found"
        assert cm.exception.status_code == 400

    def test_claim_twice_raises_state_replay_on_second(self):
        nonce = "test-nonce-replay"
        toolbar_oauth_state_cache.mark_pending(nonce)
        toolbar_oauth_state_cache.claim_or_raise(nonce)
        with self.assertRaises(ToolbarOAuthError) as cm:
            toolbar_oauth_state_cache.claim_or_raise(nonce)
        assert cm.exception.code == "state_replay"
        assert cm.exception.status_code == 400

    def test_different_nonces_do_not_interfere(self):
        toolbar_oauth_state_cache.mark_pending("nonce-a")
        toolbar_oauth_state_cache.mark_pending("nonce-b")
        toolbar_oauth_state_cache.claim_or_raise("nonce-a")
        toolbar_oauth_state_cache.claim_or_raise("nonce-b")
        with self.assertRaises(ToolbarOAuthError) as cm:
            toolbar_oauth_state_cache.claim_or_raise("nonce-a")
        assert cm.exception.code == "state_replay"


class TestTemporaryTokenBearerPassthrough(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.factory = RequestFactory()
        self.auth = TemporaryTokenAuthentication()

    def _make_cross_origin_request(self, **extra) -> Request:
        wsgi_request = self.factory.get("/api/some-endpoint/", **extra)
        wsgi_request.META["HTTP_ORIGIN"] = "https://customer-site.example.com"
        return Request(wsgi_request)

    def test_cross_origin_without_temp_token_or_bearer_raises(self):
        request = self._make_cross_origin_request()
        with self.assertRaises(AuthenticationFailed):
            self.auth.authenticate(request)

    def test_cross_origin_with_bearer_header_returns_none(self):
        request = self._make_cross_origin_request(HTTP_AUTHORIZATION="Bearer pha_test123")
        result = self.auth.authenticate(request)
        assert result is None

    def test_cross_origin_with_temp_token_authenticates(self):
        self.user.temporary_token = "test-temp-token-123"
        self.user.save(update_fields=["temporary_token"])

        request = self._make_cross_origin_request(data={"temporary_token": "test-temp-token-123"})
        result = self.auth.authenticate(request)
        assert result is not None
        assert result[0] == self.user


class TestToolbarOAuthRefresh(APIBaseTest):
    @patch("posthog.api.oauth.toolbar_service.requests.post")
    def test_refresh_success(self, mock_post):
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {
            "access_token": "pha_new",
            "refresh_token": "phr_new",
            "token_type": "Bearer",
            "expires_in": 3600,
            "scope": "openid",
        }

        response = self.client.post(
            "/api/user/toolbar_oauth_refresh/",
            data=json.dumps({"refresh_token": "phr_old", "client_id": "test_client_id"}),
            content_type="application/json",
        )
        assert response.status_code == 200
        data = response.json()
        assert data["access_token"] == "pha_new"
        assert data["refresh_token"] == "phr_new"
        assert data["expires_in"] == 3600

    @parameterized.expand(
        [
            ("missing_refresh_token", {"client_id": "test_client_id"}),
            ("missing_client_id", {"refresh_token": "phr_old"}),
            ("missing_both", {}),
        ]
    )
    def test_refresh_rejects_missing_fields(self, _name, body):
        response = self.client.post(
            "/api/user/toolbar_oauth_refresh/",
            data=json.dumps(body),
            content_type="application/json",
        )
        assert response.status_code == 400
        assert response.json()["code"] == "invalid_request"

    def test_refresh_rejects_invalid_json(self):
        response = self.client.post(
            "/api/user/toolbar_oauth_refresh/",
            data="{not-json",
            content_type="application/json",
        )
        assert response.status_code == 400
        assert response.json()["code"] == "invalid_json"

    @patch("posthog.api.oauth.toolbar_service.requests.post")
    def test_refresh_surfaces_token_error(self, mock_post):
        mock_post.return_value.status_code = 400
        mock_post.return_value.json.return_value = {
            "error": "invalid_grant",
            "error_description": "Refresh token expired",
        }

        response = self.client.post(
            "/api/user/toolbar_oauth_refresh/",
            data=json.dumps({"refresh_token": "phr_expired", "client_id": "test_client_id"}),
            content_type="application/json",
        )
        assert response.status_code == 400
        assert response.json()["code"] == "invalid_grant"

    @patch("posthog.api.oauth.toolbar_service.requests.post")
    def test_refresh_handles_non_json_response(self, mock_post):
        mock_post.return_value.status_code = 502
        mock_post.return_value.content = b"not json"
        mock_post.return_value.json.side_effect = ValueError("No JSON")

        response = self.client.post(
            "/api/user/toolbar_oauth_refresh/",
            data=json.dumps({"refresh_token": "phr_old", "client_id": "test_client_id"}),
            content_type="application/json",
        )
        assert response.status_code == 502
        assert response.json()["code"] == "token_refresh_failed"

    @patch("posthog.api.oauth.toolbar_service.requests.post")
    def test_refresh_rejects_missing_access_token_in_response(self, mock_post):
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {
            "token_type": "Bearer",
            "expires_in": 3600,
        }

        response = self.client.post(
            "/api/user/toolbar_oauth_refresh/",
            data=json.dumps({"refresh_token": "phr_old", "client_id": "test_client_id"}),
            content_type="application/json",
        )
        assert response.status_code == 502
        assert response.json()["code"] == "token_refresh_failed"

    def test_refresh_does_not_require_session_auth(self):
        self.client.logout()
        response = self.client.post(
            "/api/user/toolbar_oauth_refresh/",
            data=json.dumps({"refresh_token": "phr_old", "client_id": "test_client_id"}),
            content_type="application/json",
        )
        # Should get 400 (bad client_id) or similar, NOT 401/403
        assert response.status_code not in [401, 403]

    def test_refresh_rejects_get_method(self):
        response = self.client.get("/api/user/toolbar_oauth_refresh/")
        assert response.status_code == 405

    @patch("posthog.api.oauth.toolbar_service.requests.post")
    def test_refresh_rate_limits_after_30_requests(self, mock_post):
        from django.core.cache import cache

        cache.clear()

        mock_post.return_value.status_code = 400
        mock_post.return_value.json.return_value = {"error": "invalid_grant", "error_description": "bad token"}

        for _ in range(30):
            self.client.post(
                "/api/user/toolbar_oauth_refresh/",
                data=json.dumps({"refresh_token": "phr_old", "client_id": "test_client_id"}),
                content_type="application/json",
            )

        response = self.client.post(
            "/api/user/toolbar_oauth_refresh/",
            data=json.dumps({"refresh_token": "phr_old", "client_id": "test_client_id"}),
            content_type="application/json",
        )
        assert response.status_code == 429


class TestToolbarOAuthCallbackExchange(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.team.app_urls = ["https://example.com"]
        self.team.save()

    def _authorize_and_get_state(self) -> str:
        response = self.client.get(
            "/toolbar_oauth/authorize/",
            {"redirect": "https://example.com/page"},
        )
        assert response.status_code == 200

        # Use template context (not rendered HTML) because layout.html isn't available in CI
        auth_url = response.context["authorization_url"]
        qs = parse_qs(urlparse(auth_url).query)
        return qs["state"][0]

    @patch("posthog.api.oauth.toolbar_service.requests.post")
    def test_callback_exchanges_code_when_code_verifier_in_session(self, mock_post):
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {
            "access_token": "pha_toolbar_token",
            "refresh_token": "phr_toolbar_refresh",
            "token_type": "Bearer",
            "expires_in": 3600,
            "scope": "read",
        }

        state = self._authorize_and_get_state()
        response = self.client.get(f"/toolbar_oauth/callback?code=auth_code_123&state={state}")

        assert response.status_code == 200
        assert b'"access_token": "pha_toolbar_token"' in response.content
        assert b'"refresh_token": "phr_toolbar_refresh"' in response.content
        assert b'"expires_in": 3600' in response.content
        assert b'"type": "toolbar_oauth_callback"' in response.content

    @patch("posthog.api.oauth.toolbar_service.requests.post")
    def test_callback_target_origin_is_app_url_origin(self, mock_post):
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {
            "access_token": "pha_abc",
            "refresh_token": "phr_abc",
            "token_type": "Bearer",
            "expires_in": 3600,
            "scope": "read",
        }

        state = self._authorize_and_get_state()
        response = self.client.get(f"/toolbar_oauth/callback?code=auth_code&state={state}")

        assert response.status_code == 200
        assert b"https://example.com" in response.content

    def test_callback_without_code_verifier_relays_code_and_state(self):
        response = self.client.get("/toolbar_oauth/callback?code=test_code&state=test_state")

        assert response.status_code == 200
        assert b'"type": "toolbar_oauth_result"' in response.content
        assert b'"code": "test_code"' in response.content
        assert b'"state": "test_state"' in response.content

    def test_callback_with_error_returns_error_payload(self):
        response = self.client.get("/toolbar_oauth/callback?error=access_denied&error_description=user+cancelled")

        assert response.status_code == 200
        assert b'"type": "toolbar_oauth_callback"' in response.content
        assert b'"error": "access_denied"' in response.content
        assert b'"error_description": "user cancelled"' in response.content

    @patch("posthog.api.oauth.toolbar_service.requests.post")
    def test_callback_exchange_error_returns_error_payload(self, mock_post):
        mock_post.return_value.status_code = 400
        mock_post.return_value.json.return_value = {
            "error": "invalid_grant",
            "error_description": "Code expired",
        }

        state = self._authorize_and_get_state()
        response = self.client.get(f"/toolbar_oauth/callback?code=expired_code&state={state}")

        assert response.status_code == 200
        assert b'"error": "invalid_grant"' in response.content

    @patch("posthog.api.oauth.toolbar_service.requests.post")
    def test_callback_includes_client_id_in_payload(self, mock_post):
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {
            "access_token": "pha_abc",
            "refresh_token": "phr_abc",
            "token_type": "Bearer",
            "expires_in": 3600,
            "scope": "read",
        }

        state = self._authorize_and_get_state()
        response = self.client.get(f"/toolbar_oauth/callback?code=auth_code&state={state}")

        assert response.status_code == 200
        assert b'"client_id":' in response.content
