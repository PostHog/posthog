import json
import tempfile
from pathlib import Path

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.contrib.auth.models import AnonymousUser
from django.contrib.sessions.middleware import SessionMiddleware
from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase, override_settings

from parameterized import parameterized

from posthog.stable_chunks import (
    STABLE_CHUNKS_COOKIE,
    StableChunks,
    persist_stable_chunks_choice,
    read_stable_chunks_manifest,
    stable_chunks_opted_in,
)
from posthog.utils import get_context_for_template, render_template

VALID_MANIFEST = {
    "imports": {"@c/eAAAA": "static/index-S0000000000.js"},
    "preload": {"js": ["static/index-S0000000000.js"], "authenticatedJs": ["static/chunk-S1111111111.js"]},
    "eagerCss": ["static/stylesEagerTailwind-AAAA1111.css", "static/stylesEagerApp-BBBB2222.css"],
}


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
            ("param on", "?stable_chunks=1", None, True),
            ("param off overrides the cookie", "?stable_chunks=0", "1", False),
            ("cookie on", "", "1", True),
            ("nothing set", "", None, False),
        ]
    )
    def test_opt_in(self, _name, query, cookie, expected):
        request = RequestFactory().get(f"/{query}")
        if cookie:
            request.COOKIES[STABLE_CHUNKS_COOKIE] = cookie

        assert stable_chunks_opted_in(request) == expected

    @parameterized.expand(
        [
            ("param on stores the choice for 30 days", "?stable_chunks=1", "1", 60 * 60 * 24 * 30),
            ("param off expires the cookie", "?stable_chunks=0", "", 0),
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
        if expected_value == "1":
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
    @parameterized.expand([("opting in", "1"), ("opting out", "0")])
    def test_rendering_a_page_persists_the_choice(self, _name, param):
        # Any template exercises this: render_template persists the choice for every page it
        # returns, and the app shell template only exists after a frontend build.
        request = RequestFactory().get(f"/?stable_chunks={param}")
        SessionMiddleware(lambda _request: HttpResponse()).process_request(request)
        request.user = self.user

        response = render_template("sso_reauth_complete.html", request)

        assert response.cookies[STABLE_CHUNKS_COOKIE].value == ("1" if param == "1" else "")
