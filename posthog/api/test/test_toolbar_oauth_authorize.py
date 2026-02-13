from posthog.test.base import APIBaseTest


class TestToolbarOAuthAuthorize(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.team.app_urls = ["https://mysite.com"]
        self.team.save()
        self.user.current_team = self.team
        self.user.save(update_fields=["current_team"])
        self.client.force_login(self.user)

    def _get_authorize(self, redirect_url: str = "https://mysite.com/page"):
        return self.client.get(f"/toolbar_oauth/authorize/?redirect={redirect_url}")

    def _assert_authorize_ok(self, response):
        assert response.status_code == 200, (
            f"Expected 200 from toolbar_oauth/authorize, got {response.status_code}. Body: {response.content[:500]!r}"
        )

    def test_renders_oauth_authorize_url(self):
        response = self._get_authorize()
        self._assert_authorize_ok(response)
        content = response.content.decode()
        assert "/oauth/authorize" in content
        assert "code_challenge" in content

    def test_rejects_missing_redirect(self):
        response = self.client.get("/toolbar_oauth/authorize/")
        assert response.status_code == 400

    def test_rejects_disallowed_domain(self):
        response = self._get_authorize(redirect_url="https://evil.com/page")
        assert response.status_code == 403

    def test_requires_authentication(self):
        self.client.logout()
        response = self._get_authorize()
        assert response.status_code == 302

    def test_oauth_url_contains_state_and_pkce_params(self):
        response = self._get_authorize()
        self._assert_authorize_ok(response)
        content = response.content.decode()
        assert "state=" in content
        assert "code_challenge=" in content
        assert "code_challenge_method=S256" in content

    def test_oauth_url_contains_correct_redirect_uri(self):
        response = self._get_authorize()
        self._assert_authorize_ok(response)
        content = response.content.decode()
        assert "redirect_uri=" in content
        assert "toolbar_oauth" in content
        assert "callback" in content

    def test_code_verifier_is_stored_in_session(self):
        response = self._get_authorize()
        self._assert_authorize_ok(response)

        session = self.client.session
        assert "toolbar_oauth_code_verifier" in session
        assert len(session["toolbar_oauth_code_verifier"]) >= 43
