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

        self.assertEqual(response.status_code, 200)
        # Should contain an OAuth authorizaion URl pointing to /oauth/authorize
        content = response.content.decode()
        self.assertIn("/oauth/authorize", content)
        self.assertIn("code_challenge", content)
        self.assertNotIn("/api/user/redirect_to_site", content)

    @override_settings(TOOLBAR_OAUTH_ENABLED=False)
    def test_renders_legacy_redirect_when_disabled(self):
        response = self._get_authorize()

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn("/api/user/redirect_to_site", content)
        self.assertNotIn("/oauth/authorize", content)

    def test_still_rejects_disallowed_domain(self):
        response = self._get_authorize(redirect_url="https://evil.com/page")

        self.assertEqual(response.status_code, 403)

    def test_still_requires_referrer_header(self):
        response = self.client.get("/authorize_and_redirect/?redirect=https://mysite.com/page")

        self.assertEqual(response.status_code, 400)

    def test_oauth_url_contains_state_and_pkce_params(self):
        response = self._get_authorize()

        content = response.content.decode()
        # Find the authorization URL in the rendered HTML
        # It should contain the state and PKCE parameters
        self.assertIn("state=", content)
        self.assertIn("code_challenge=", content)
        self.assertIn("code_challenge_method=S256", content)

    def test_oauth_url_contains_correct_redirect_uri(self):
        response = self._get_authorize()

        content = response.content.decode()
        self.assertIn("redirect_uri=", content)
        self.assertIn("toolbar_oauth_callback", content)

    # Tests for PKCE generation
    def test_code_verifier_is_stored_in_session(self):
        response = self._get_authorize()

        # assert status code
        self.assertEqual(response.status_code, 200)

        session = self.client.session
        self.assertIn("toolbar_oauth_code_verifier", session)
        self.assertTrue(len(session["toolbar_oauth_code_verifier"]) >= 43)
