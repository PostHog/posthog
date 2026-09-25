import json
import tempfile
from pathlib import Path

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.contrib.auth.models import AnonymousUser
from django.contrib.sessions.middleware import SessionMiddleware
from django.http import HttpRequest, HttpResponse
from django.test import RequestFactory, SimpleTestCase, override_settings

from parameterized import parameterized

from posthog.models import User
from posthog.stable_chunks import (
    STABLE_CHUNKS_COOKIE,
    STABLE_CHUNKS_FLAG,
    StableChunks,
    persist_stable_chunks_choice,
    read_stable_chunks_manifest,
    stable_chunks_choice,
)
from posthog.utils import get_context_for_template, render_template

VALID_MANIFEST = {
    "imports": {"@c/eAAAA": "static/index-S0000000000.js"},
    "preload": {"js": ["static/index-S0000000000.js"], "authenticatedJs": ["static/chunk-S1111111111.js"]},
    "eagerCss": ["static/stylesEagerTailwind-AAAA1111.css", "static/stylesEagerApp-BBBB2222.css"],
}
FLAG_ON = {STABLE_CHUNKS_FLAG: True}
FLAG_OFF = {STABLE_CHUNKS_FLAG: False}
SAFARI_MAC = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Safari/605.1.15"
CHROME_IOS = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) CriOS/129.0.0.0 Mobile/15E148 Safari/604.1"
CHROME_MAC = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36"
FIREFOX_MAC = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:131.0) Gecko/20100101 Firefox/131.0"


class TestStableChunks(SimpleTestCase):
    @parameterized.expand(
        [
            ("valid", VALID_MANIFEST, True),
            ("imports is not a mapping", {**VALID_MANIFEST, "imports": ["static/index.js"]}, False),
            ("empty imports", {**VALID_MANIFEST, "imports": {}}, False),
            ("preload url is not a string", {**VALID_MANIFEST, "preload": {"js": [1], "authenticatedJs": []}}, False),
            ("eager css url is not a string", {**VALID_MANIFEST, "eagerCss": [1]}, False),
        ]
    )
    def test_manifest_problems_fall_back_to_the_default_build(self, _name, manifest, expect_stable):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "stable-chunks-manifest.json"
            path.write_text(json.dumps(manifest))

            stable = read_stable_chunks_manifest(str(path))

        assert (stable is not None) == expect_stable
        if stable:
            assert json.loads(stable.import_map_json("https://cdn.example.com")) == {
                "imports": {"@c/eAAAA": "https://cdn.example.com/static/index-S0000000000.js"}
            }
            assert stable.preload_urls(include_authenticated_shell=False) == ("static/index-S0000000000.js",)
            assert stable.eager_css_urls == (
                "static/stylesEagerTailwind-AAAA1111.css",
                "static/stylesEagerApp-BBBB2222.css",
            )

    def test_import_map_cannot_close_its_script_tag(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "stable-chunks-manifest.json"
            path.write_text(json.dumps(VALID_MANIFEST))
            stable = read_stable_chunks_manifest(str(path))

        assert stable is not None
        assert "</script>" not in stable.import_map_json("https://cdn.example.com</script><script>")

    @parameterized.expand(
        [
            ("param on beats a cookie off and the flag off", "?stable_chunks=1", "0", FLAG_OFF, True, True),
            ("param off beats the flag on", "?stable_chunks=0", None, FLAG_ON, True, False),
            ("fallback beats a cookie on", "?stable_chunks=fallback", "1", None, True, False),
            ("fallback beats the flag on", "?stable_chunks=fallback", None, FLAG_ON, True, False),
            ("cookie on beats the flag off", "", "1", FLAG_OFF, True, True),
            ("cookie off beats the flag on", "", "0", FLAG_ON, True, False),
            ("flag on", "", None, FLAG_ON, True, True),
            ("flag off", "", None, FLAG_OFF, True, False),
            ("flag without a local definition", "", None, {}, True, False),
            ("flags not evaluated", "", None, None, True, False),
            ("anonymous with the flag on", "", None, FLAG_ON, False, False),
        ]
    )
    def test_choice_precedence(self, _name, query, cookie, feature_flags, authenticated, expected):
        request = RequestFactory().get(f"/{query}")
        request.user = User() if authenticated else AnonymousUser()
        if cookie:
            request.COOKIES[STABLE_CHUNKS_COOKIE] = cookie

        assert stable_chunks_choice(request, feature_flags) == expected

    @parameterized.expand(
        [
            ("safari with the flag on", "", None, SAFARI_MAC, False),
            ("chrome on ios with the flag on", "", None, CHROME_IOS, False),
            ("chrome with the flag on", "", None, CHROME_MAC, True),
            ("firefox with the flag on", "", None, FIREFOX_MAC, True),
            ("param on still opts safari in", "?stable_chunks=1", None, SAFARI_MAC, True),
            ("cookie on still opts safari in", "", "1", SAFARI_MAC, True),
        ]
    )
    def test_the_flag_skips_webkit(
        self, _name: str, query: str, cookie: str | None, user_agent: str, expected: bool
    ) -> None:
        request = RequestFactory().get(f"/{query}", HTTP_USER_AGENT=user_agent)
        request.user = User()
        if cookie:
            request.COOKIES[STABLE_CHUNKS_COOKIE] = cookie

        assert stable_chunks_choice(request, FLAG_ON) == expected

    @parameterized.expand(
        [
            ("param on stores the choice for 30 days", "?stable_chunks=1", "1", 60 * 60 * 24 * 30),
            ("param off stores the opt-out for 30 days", "?stable_chunks=0", "0", 60 * 60 * 24 * 30),
            ("fallback leaves the cookie alone", "?stable_chunks=fallback", None, None),
            ("no param leaves the cookie alone", "", None, None),
        ]
    )
    def test_the_choice_is_persisted_on_the_response(self, _name, query, expected_value, expected_max_age):
        request = RequestFactory().get(f"/{query}")
        response = HttpResponse()

        persist_stable_chunks_choice(request, response)

        cookie = response.cookies.get(STABLE_CHUNKS_COOKIE)
        assert (cookie.value if cookie else None) == expected_value
        assert (cookie["max-age"] if cookie else None) == expected_max_age
        if expected_value:
            assert cookie is not None
            # Only the server reads the choice, so scripts on the page never need it.
            assert cookie["httponly"] is True

    def _context_with_stable_chunks(self, stable: StableChunks) -> dict:
        # no-preloaded-app-context and E2E_TESTING skip the request's team/user lookups, which need
        # a database that a SimpleTestCase cannot use.
        request = RequestFactory().get("/?no-preloaded-app-context=1")
        request.user = AnonymousUser()
        with (
            override_settings(E2E_TESTING=True),
            patch("posthog.utils.stable_chunks_for_request", return_value=stable),
        ):
            return get_context_for_template("index.html", request)

    def test_eager_css_urls_replace_the_single_preload_link(self):
        stable = StableChunks(
            imports={"@c/eAAAA": "static/index-S0000000000.js"},
            preload_js_urls=(),
            authenticated_preload_js_urls=(),
            eager_css_urls=("static/stylesEagerTailwind-AAAA1111.css", "static/stylesEagerApp-BBBB2222.css"),
        )

        context = self._context_with_stable_chunks(stable)

        assert context["preload_css_url"] == ""
        assert context["stable_preload_css_urls"] == stable.eager_css_urls

    def test_no_eager_css_urls_keeps_the_single_preload_link(self):
        stable = StableChunks(
            imports={"@c/eAAAA": "static/index-S0000000000.js"}, preload_js_urls=(), authenticated_preload_js_urls=()
        )

        context = self._context_with_stable_chunks(stable)

        assert "stable_preload_css_urls" not in context


class TestStableChunksChoiceSurvivesTheRequest(APIBaseTest):
    def _user_request(self, query: str) -> HttpRequest:
        request = RequestFactory().get(f"/{query}")
        SessionMiddleware(lambda _request: HttpResponse()).process_request(request)
        request.user = self.user
        return request

    @parameterized.expand([("opting in", "1"), ("opting out", "0")])
    def test_rendering_a_page_persists_the_choice(self, _name, param):
        # Any template exercises this: render_template persists the choice for every page it
        # returns, and the app shell template only exists after a frontend build.
        request = self._user_request(f"?stable_chunks={param}")

        response = render_template("sso_reauth_complete.html", request)

        assert response.cookies[STABLE_CHUNKS_COOKIE].value == param

    @parameterized.expand(
        [
            ("flag on", "", FLAG_ON, True),
            ("flag off", "", FLAG_OFF, False),
            ("flag without a local definition", "", {}, False),
            ("flag evaluation failed", "", None, False),
            ("fallback with the flag on", "?stable_chunks=fallback", FLAG_ON, False),
        ]
    )
    def test_the_flag_picks_the_build_it_bootstraps(self, _name, query, flags, expect_stable):
        request = self._user_request(query)
        stable = StableChunks(
            imports={"@c/eAAAA": "static/index-S0000000000.js"}, preload_js_urls=(), authenticated_preload_js_urls=()
        )

        with (
            patch("posthoganalytics.get_all_flags", return_value=flags) as get_all_flags,
            patch("posthog.stable_chunks._resolve_stable_chunks", return_value=stable),
        ):
            context = get_context_for_template("index.html", request)

        assert context.get("stable_chunks", False) == expect_stable
        assert json.loads(context["posthog_bootstrap"]).get("featureFlags") == flags
        get_all_flags.assert_called_once()
        assert get_all_flags.call_args.kwargs["only_evaluate_locally"] is True
