from posthog.test.base import APIBaseTest

from django.test import override_settings


@override_settings(TOOLBAR_OAUTH_ENABLED=True)
class TestAuthorizeAndRedirectOAuth(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.team.app_urls = ["https://mysite.com"]
        self.team.save()

    def _get_authorize(self, redirect_url: str = "https://mysite.com/page"):
        return self.client.get(f"/authorize_and_redirect/?redirect={redirect_url}", HTTP_REFERER=redirect_url)

    def test_renders_oauth_authorize_url_when_enabled(self):
        response = self._get_authorize()

        assert response.status_code == 200
        content = response.content.decode()
        assert "/oauth/authorize" in content
        assert "code_challenge" in content
        assert "/api/user/redirect_to_site" not in content

    @override_settings(TOOLBAR_OAUTH_ENABLED=False)
    def test_renders_legacy_redirect_when_disabled(self):
        response = self._get_authorize()

        assert response.status_code == 200
        content = response.content.decode()
        assert "/api/user/redirect_to_site" in content
        assert "/oauth/authorize" not in content

    def test_still_rejects_disallowed_domain(self):
        response = self._get_authorize(redirect_url="https://evil.com/page")

        assert response.status_code == 403

    def test_still_requires_referrer_header(self):
        response = self.client.get("/authorize_and_redirect/?redirect=https://mysite.com/page")

        assert response.status_code == 400

    def test_oauth_url_contains_state_and_pkce_params(self):
        response = self._get_authorize()

        content = response.content.decode()
        assert "state=" in content
        assert "code_challenge=" in content
        assert "code_challenge_method=S256" in content

    def test_oauth_url_contains_correct_redirect_uri(self):
        response = self._get_authorize()

        content = response.content.decode()
        assert "redirect_uri=" in content
        assert "toolbar_oauth" in content
        assert "callback" in content

    def test_code_verifier_is_stored_in_session(self):
        response = self._get_authorize()

        assert response.status_code == 200

        session = self.client.session
        assert "toolbar_oauth_code_verifier" in session
        assert len(session["toolbar_oauth_code_verifier"]) >= 43
