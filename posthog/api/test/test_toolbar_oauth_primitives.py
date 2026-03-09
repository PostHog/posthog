import json
from urllib.parse import parse_qs, urlparse

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.conf import settings
from django.test import override_settings

import requests
from parameterized import parameterized

from posthog.api.oauth.test_dcr import generate_rsa_key
from posthog.api.oauth.toolbar_service import (
    CALLBACK_PATH,
    ToolbarOAuthError,
    ToolbarOAuthState,
    _post_to_token_endpoint,
    build_authorization_url,
    build_toolbar_oauth_state,
    get_or_create_toolbar_oauth_application,
    new_state_nonce,
    toolbar_oauth_state_cache,
)
from posthog.models import Organization, Team, User


@override_settings(OAUTH2_PROVIDER={**settings.OAUTH2_PROVIDER, "OIDC_RSA_PRIVATE_KEY": generate_rsa_key()})
class TestToolbarOAuthPrimitives(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.team.app_urls = ["https://example.com"]
        self.team.save()

    def _signed_state(self) -> str:
        oauth_app = get_or_create_toolbar_oauth_application(user=self.user)
        signed_state, _ = build_toolbar_oauth_state(
            ToolbarOAuthState(
                nonce=new_state_nonce(),
                user_id=self.user.id,
                team_id=self.team.id,
                app_url=self.team.app_urls[0],
            )
        )
        auth_url = build_authorization_url(
            application=oauth_app,
            state=signed_state,
            code_challenge="test_challenge_value",
        )
        return parse_qs(urlparse(auth_url).query)["state"][0]

    def test_callback_anonymous_user_returns_401(self):
        self.client.logout()
        response = self.client.get("/toolbar_oauth/callback?code=c&state=s")
        assert response.status_code == 401

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

    def test_callback_with_invalid_state_returns_error(self):
        response = self.client.get("/toolbar_oauth/callback?code=test_code&state=invalid_state")
        assert response.status_code >= 400

    def test_callback_with_error_returns_plain_text(self):
        response = self.client.get(
            "/toolbar_oauth/callback?error=access_denied&error_description=user+cancelled&state=test_state"
        )
        assert response.status_code == 400
        assert b"user cancelled" in response.content

    def test_callback_rejects_post_method(self):
        response = self.client.post("/toolbar_oauth/callback")
        assert response.status_code == 405

    def test_get_or_create_is_idempotent_within_org(self):
        first = get_or_create_toolbar_oauth_application(user=self.user)
        second = get_or_create_toolbar_oauth_application(user=self.user)
        assert first.pk == second.pk
        assert first.client_id == second.client_id


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


class TestToolbarOAuthRefresh(APIBaseTest):
    @patch("posthog.api.oauth.toolbar_service.external_requests.post")
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

    @patch("posthog.api.oauth.toolbar_service.external_requests.post")
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

    @patch("posthog.api.oauth.toolbar_service.external_requests.post")
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

    @patch("posthog.api.oauth.toolbar_service.external_requests.post")
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

    @patch("posthog.api.oauth.toolbar_service.external_requests.post")
    def test_refresh_handles_network_failure(self, mock_post):
        mock_post.side_effect = requests.RequestException("connection refused")

        response = self.client.post(
            "/api/user/toolbar_oauth_refresh/",
            data=json.dumps({"refresh_token": "phr_old", "client_id": "test_client_id"}),
            content_type="application/json",
        )
        assert response.status_code == 500
        assert response.json()["code"] == "token_refresh_failed"

    @patch("posthog.api.oauth.toolbar_service.external_requests.post")
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


class TestTokenEndpointStatusRemapping(APIBaseTest):
    @parameterized.expand(
        [
            ("401_becomes_400", 401, 400),
            ("403_becomes_400", 403, 400),
            ("400_passes_through", 400, 400),
            ("500_passes_through", 500, 500),
            ("502_passes_through", 502, 502),
        ]
    )
    @patch("posthog.api.oauth.toolbar_service.external_requests.post")
    def test_internal_oauth_status_remapping(self, _name, internal_status, expected_status, mock_post):
        mock_post.return_value.status_code = internal_status
        mock_post.return_value.content = b'{"error": "test_error", "error_description": "test"}'
        mock_post.return_value.json.return_value = {"error": "test_error", "error_description": "test"}

        with self.assertRaises(ToolbarOAuthError) as cm:
            _post_to_token_endpoint({"grant_type": "refresh_token"}, error_code="token_refresh_failed")
        assert cm.exception.status_code == expected_status


@override_settings(OAUTH2_PROVIDER={**settings.OAUTH2_PROVIDER, "OIDC_RSA_PRIVATE_KEY": generate_rsa_key()})
class TestToolbarOAuthCallbackExchange(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.team.app_urls = ["https://example.com"]
        self.team.save()

    def _authorize_and_get_state(self, redirect_url: str = "https://example.com/page") -> str:
        response = self.client.get(
            "/toolbar_oauth/authorize/",
            {"redirect": redirect_url, "code_challenge": "test_challenge_value"},
        )
        assert response.status_code == 302

        auth_url = response["Location"]
        qs = parse_qs(urlparse(auth_url).query)
        return qs["state"][0]

    def test_callback_redirects_with_code_in_redirect_flow(self):
        state = self._authorize_and_get_state()
        response = self.client.get(f"/toolbar_oauth/callback?code=auth_code_123&state={state}")

        assert response.status_code == 302
        redirect_url = response["Location"]
        assert redirect_url.startswith("https://example.com/page#")
        assert "__posthog_toolbar=code:auth_code_123" in redirect_url
        assert "client_id:" in redirect_url

    def test_callback_preserves_original_url_fragment(self):
        state = self._authorize_and_get_state(redirect_url="https://example.com/page#section1")
        response = self.client.get(f"/toolbar_oauth/callback?code=auth_code_123&state={state}")

        assert response.status_code == 302
        redirect_url = response["Location"]
        assert "#section1&__posthog_toolbar=code:auth_code_123" in redirect_url

    def test_callback_strips_posthog_hash_from_redirect(self):
        """__posthog hash params must not survive the OAuth round-trip or they cause a re-init loop."""
        posthog_hash = "%7B%22action%22%3A%22ph_authorize%22%2C%22token%22%3A%22phc_test%22%7D"
        state = self._authorize_and_get_state(redirect_url=f"https://example.com/page#__posthog={posthog_hash}")
        response = self.client.get(f"/toolbar_oauth/callback?code=auth_code_123&state={state}")

        assert response.status_code == 302
        redirect_url = response["Location"]
        assert "__posthog=" not in redirect_url.split("__posthog_toolbar")[0]
        assert "__posthog_toolbar=code:auth_code_123" in redirect_url

    def test_callback_with_invalid_state_returns_error(self):
        response = self.client.get("/toolbar_oauth/callback?code=test_code&state=invalid_state")
        assert response.status_code >= 400

    def test_callback_with_error_returns_plain_text(self):
        response = self.client.get("/toolbar_oauth/callback?error=access_denied&error_description=user+cancelled")

        assert response.status_code == 400
        assert b"user cancelled" in response.content

    def test_callback_state_validation_error_returns_http_error(self):
        state = self._authorize_and_get_state()
        tampered_state = f"{state[:-1]}x"
        response = self.client.get(f"/toolbar_oauth/callback?code=auth_code&state={tampered_state}")

        assert response.status_code >= 400

    def test_callback_escapes_html_in_error_description(self):
        xss_payload = "</script><script>alert(document.cookie)</script>"
        response = self.client.get(f"/toolbar_oauth/callback?error=test&error_description={xss_payload}")
        assert response.status_code == 400
        # django.utils.html.escape converts < and > to &lt; / &gt;
        assert b"<script>alert" not in response.content
        assert b"&lt;script&gt;" in response.content

    def test_authorize_requires_code_challenge(self):
        response = self.client.get(
            "/toolbar_oauth/authorize/",
            {"redirect": "https://example.com/page"},
        )
        assert response.status_code == 400

    def test_authorize_rejects_post_method(self):
        response = self.client.post("/toolbar_oauth/authorize/")
        assert response.status_code == 405

    def test_authorize_rejects_disallowed_redirect(self):
        response = self.client.get(
            "/toolbar_oauth/authorize/",
            {"redirect": "https://evil.com/page", "code_challenge": "test_challenge"},
        )
        assert response.status_code == 403

    def test_authorize_does_not_set_session_marker(self):
        self._authorize_and_get_state()
        assert self.client.session.get("toolbar_oauth_redirect_flow") is None

    def test_authorize_multiple_calls_produce_unique_states(self):
        state_a = self._authorize_and_get_state()
        state_b = self._authorize_and_get_state()
        assert state_a != state_b

    def test_authorize_preserves_redirect_url_with_query_params(self):
        redirect = "https://example.com/page?sort=date&page=2"
        state = self._authorize_and_get_state(redirect_url=redirect)
        response = self.client.get(f"/toolbar_oauth/callback?code=abc&state={state}")
        assert response.status_code == 302
        assert response["Location"].startswith("https://example.com/page?sort=date&page=2#")

    def test_callback_missing_code_returns_400(self):
        state = self._authorize_and_get_state()
        response = self.client.get(f"/toolbar_oauth/callback?state={state}")
        assert response.status_code == 400

    def test_callback_missing_state_returns_400(self):
        response = self.client.get("/toolbar_oauth/callback?code=abc")
        assert response.status_code == 400

    def test_callback_missing_both_returns_400(self):
        response = self.client.get("/toolbar_oauth/callback")
        assert response.status_code == 400

    def test_callback_user_without_team_returns_400(self):
        # Authorize first (user has a team), then simulate the team becoming unavailable
        # User.team has a fallback lookup so we must mock at the class level to simulate
        # a user with no resolvable team at callback time
        state = self._authorize_and_get_state()
        with patch("posthog.models.user.User.team", new_callable=property, fget=lambda self: None):
            response = self.client.get(f"/toolbar_oauth/callback?code=abc&state={state}")
        assert response.status_code == 400

    def test_callback_does_not_embed_redirect_uri_or_token_endpoint(self):
        state = self._authorize_and_get_state()
        response = self.client.get(f"/toolbar_oauth/callback?code=abc&state={state}")
        assert response.status_code == 302
        from urllib.parse import unquote

        location = unquote(response["Location"])
        assert "redirect_uri:" not in location
        assert "token_endpoint:" not in location

    def test_callback_state_user_mismatch_returns_error(self):
        state = self._authorize_and_get_state()
        other_user = User.objects.create_user(
            email="other-callback@example.com",
            first_name="Other",
            password="password",
            current_organization=self.organization,
            current_team=self.team,
        )
        self.organization.members.add(other_user)
        self.client.force_login(other_user)
        response = self.client.get(f"/toolbar_oauth/callback?code=abc&state={state}")
        assert response.status_code >= 400

    def test_callback_state_team_mismatch_returns_error(self):
        state = self._authorize_and_get_state()
        other_team = Team.objects.create(organization=self.organization, name="Other Team")
        self.user.current_team = other_team
        self.user.save(update_fields=["current_team"])
        response = self.client.get(f"/toolbar_oauth/callback?code=abc&state={state}")
        assert response.status_code >= 400

    def test_callback_state_replay_returns_error(self):
        state = self._authorize_and_get_state()
        first = self.client.get(f"/toolbar_oauth/callback?code=abc&state={state}")
        assert first.status_code == 302
        second = self.client.get(f"/toolbar_oauth/callback?code=abc&state={state}")
        assert second.status_code >= 400

    @override_settings(TOOLBAR_OAUTH_STATE_TTL_SECONDS=0)
    def test_callback_expired_state_returns_error(self):
        state = self._authorize_and_get_state()
        response = self.client.get(f"/toolbar_oauth/callback?code=abc&state={state}")
        assert response.status_code >= 400

    def test_callback_app_url_root_domain(self):
        self.team.app_urls = ["https://example.com"]
        self.team.save()
        state = self._authorize_and_get_state(redirect_url="https://example.com")
        response = self.client.get(f"/toolbar_oauth/callback?code=abc&state={state}")
        assert response.status_code == 302
        assert response["Location"].startswith("https://example.com#__posthog_toolbar=")
