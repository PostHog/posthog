"""
Repro: hash-routed SPAs (e.g. /#/login) get a 404 after toolbar OAuth because
the backend redirects to {base}#{original_fragment}&{toolbar_param}, and the
SPA router sees /login&__posthog_toolbar=... as one path segment.

Run: pytest posthog/api/test/test_toolbar_hash_routing_repro.py -v
"""

from urllib.parse import urlparse

from posthog.test.base import APIBaseTest

from parameterized import parameterized

from posthog.api.test.test_toolbar_oauth_primitives import ToolbarOAuthAuthorizeMixin


class TestToolbarHashRoutingRepro(ToolbarOAuthAuthorizeMixin, APIBaseTest):
    def setUp(self):
        super().setUp()
        self.team.app_urls = ["https://app.example.com"]
        self.team.save()

    @parameterized.expand(
        [
            (
                "hash_route_uses_question_mark_separator",
                "https://app.example.com/#/login",
                "/login?__posthog_toolbar=",
            ),
            (
                "plain_fragment_still_uses_ampersand",
                "https://app.example.com/page#section1",
                "section1&__posthog_toolbar=",
            ),
            (
                "hash_route_with_existing_query_uses_ampersand",
                "https://app.example.com/#/login?foo=bar",
                "/login?foo=bar&__posthog_toolbar=",
            ),
        ]
    )
    def test_hash_routing_separator(self, _name, redirect_url, expected_fragment_prefix):
        state = self._authorize_and_get_state(redirect_url=redirect_url)
        response = self.client.get(f"/toolbar_oauth/callback?code=AUTH_CODE_X&state={state}")

        assert response.status_code == 302
        parsed = urlparse(response["Location"])
        assert parsed.fragment.startswith(expected_fragment_prefix), (
            f"expected fragment to start with {expected_fragment_prefix!r}, got {parsed.fragment!r}"
        )
        assert parsed.fragment.count("?") == expected_fragment_prefix.count("?"), (
            f"fragment must have exactly {expected_fragment_prefix.count('?')} `?`, got {parsed.fragment!r}"
        )
