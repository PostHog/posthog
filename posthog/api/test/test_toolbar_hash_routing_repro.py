"""
Repro: hash-routed SPAs (e.g. /#/login) get a 404 after toolbar OAuth because
the backend redirects to {base}#{original_fragment}&{toolbar_param}, and the
SPA router sees /login&__posthog_toolbar=... as one path segment.

Run: hogli test posthog/api/test/test_toolbar_hash_routing_repro.py -v
"""

from urllib.parse import parse_qs, urlparse

from posthog.test.base import APIBaseTest

from django.conf import settings
from django.test.utils import override_settings

from posthog.api.oauth.test_dcr import generate_rsa_key


@override_settings(OAUTH2_PROVIDER={**settings.OAUTH2_PROVIDER, "OIDC_RSA_PRIVATE_KEY": generate_rsa_key()})
class TestToolbarHashRoutingRepro(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.team.app_urls = ["https://app.example.com"]
        self.team.save()

    def _authorize_and_get_state(self, redirect_url: str) -> str:
        response = self.client.get(
            "/toolbar_oauth/authorize/",
            {"redirect": redirect_url, "code_challenge": "test_challenge_value"},
        )
        assert response.status_code == 302, response.content
        auth_url = response["Location"]
        return parse_qs(urlparse(auth_url).query)["state"][0]

    def test_hash_route_uses_question_mark_separator(self):
        """
        For a SPA at https://app.example.com/#/login the toolbar OAuth callback
        must produce `/login?__posthog_toolbar=...` so hash routers split on
        `?` into route=/login + hash-query. With `&` the entire post-`#`
        substring is treated as one path and the SPA 404s.
        """
        state = self._authorize_and_get_state(redirect_url="https://app.example.com/#/login")
        response = self.client.get(f"/toolbar_oauth/callback?code=AUTH_CODE_X&state={state}")

        assert response.status_code == 302
        redirect_url = response["Location"]
        parsed = urlparse(redirect_url)
        assert parsed.fragment.startswith("/login?__posthog_toolbar="), (
            f"expected `/login?__posthog_toolbar=...` for SPA hash route, got fragment={parsed.fragment!r}"
        )

    def test_plain_fragment_still_uses_ampersand(self):
        """Non-route fragments like #section1 continue to use & as separator."""
        state = self._authorize_and_get_state(redirect_url="https://app.example.com/page#section1")
        response = self.client.get(f"/toolbar_oauth/callback?code=AUTH_CODE_X&state={state}")
        parsed = urlparse(response["Location"])
        assert parsed.fragment.startswith("section1&__posthog_toolbar="), (
            f"expected `section1&__posthog_toolbar=...` for plain fragment, got fragment={parsed.fragment!r}"
        )
