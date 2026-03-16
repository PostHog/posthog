from urllib.parse import parse_qs, urlparse

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.conf import settings
from django.test import override_settings

from posthog.api.oauth.test_dcr import generate_rsa_key


@override_settings(OAUTH2_PROVIDER={**settings.OAUTH2_PROVIDER, "OIDC_RSA_PRIVATE_KEY": generate_rsa_key()})
class TestToolbarOAuthAuthorize(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.team.app_urls = ["https://mysite.com"]
        self.team.save()
        self.user.current_team = self.team
        self.user.save(update_fields=["current_team"])
        self.client.force_login(self.user)

    def _get_authorize(
        self, redirect_url: str = "https://mysite.com/page", code_challenge: str = "test_challenge_abc123"
    ):
        return self.client.get(f"/toolbar_oauth/authorize/?redirect={redirect_url}&code_challenge={code_challenge}")

    def _assert_authorize_redirects(self, response):
        assert response.status_code == 302, (
            f"Expected 302 redirect from toolbar_oauth/authorize, got {response.status_code}. Body: {response.content[:500]!r}"
        )

    def _get_authorization_url(self, response) -> str:
        return response["Location"]

    def test_redirects_to_oauth_authorize_url(self):
        response = self._get_authorize()
        self._assert_authorize_redirects(response)
        auth_url = self._get_authorization_url(response)
        assert "/oauth/authorize" in auth_url
        assert "code_challenge" in auth_url

    def test_rejects_missing_redirect(self):
        response = self.client.get("/toolbar_oauth/authorize/")
        assert response.status_code == 400

    def test_disallowed_domain_returns_error_page_with_hostname(self):
        response = self._get_authorize(redirect_url="https://evil.com/page")
        assert response.status_code == 403
        content = response.content.decode()
        assert "Domain not authorized" in content
        assert "evil.com" in content
        assert "authorized URLs" in content
        assert "/settings/project-toolbar#authorized-urls" in content

    def test_requires_authentication(self):
        self.client.logout()
        response = self._get_authorize()
        assert response.status_code == 302

    def test_oauth_url_contains_state_and_pkce_params(self):
        response = self._get_authorize()
        self._assert_authorize_redirects(response)
        auth_url = self._get_authorization_url(response)
        qs = parse_qs(urlparse(auth_url).query)
        assert "state" in qs
        assert "code_challenge" in qs
        assert qs.get("code_challenge_method") == ["S256"]

    def test_oauth_url_contains_correct_redirect_uri(self):
        response = self._get_authorize()
        self._assert_authorize_redirects(response)
        auth_url = self._get_authorization_url(response)
        qs = parse_qs(urlparse(auth_url).query)
        assert "redirect_uri" in qs
        redirect_uri = qs["redirect_uri"][0]
        assert "toolbar_oauth" in redirect_uri
        assert "callback" in redirect_uri

    def test_authorize_redirects_to_oauth_with_state_and_pkce(self):
        response = self._get_authorize()
        self._assert_authorize_redirects(response)

        from urllib.parse import parse_qs, urlparse

        qs = parse_qs(urlparse(response["Location"]).query)
        assert "state" in qs
        assert "code_challenge" in qs

    def test_authorize_does_not_set_session_marker(self):
        response = self._get_authorize()
        self._assert_authorize_redirects(response)
        assert self.client.session.get("toolbar_oauth_redirect_flow") is None

    def test_authorize_multiple_calls_produce_unique_states(self):
        r1 = self._get_authorize()
        r2 = self._get_authorize()
        self._assert_authorize_redirects(r1)
        self._assert_authorize_redirects(r2)
        qs1 = parse_qs(urlparse(r1["Location"]).query)
        qs2 = parse_qs(urlparse(r2["Location"]).query)
        assert qs1["state"][0] != qs2["state"][0]

    def test_authorize_redirect_with_query_params_is_preserved_in_state(self):
        redirect = "https://mysite.com/page?sort=date&page=2"
        import urllib.parse

        response = self.client.get(
            f"/toolbar_oauth/authorize/?redirect={urllib.parse.quote(redirect, safe='')}&code_challenge=abc"
        )
        self._assert_authorize_redirects(response)
        # State is opaque here; full round-trip is tested in test_toolbar_oauth_primitives.py

    def test_authorize_user_without_team_returns_400(self):
        # User.team has a fallback lookup so we must mock at the class level to simulate
        # a user with no resolvable team
        with patch("posthog.models.user.User.team", new_callable=property, fget=lambda self: None):
            response = self._get_authorize()
        assert response.status_code == 400
