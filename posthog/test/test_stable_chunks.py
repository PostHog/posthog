import json
import tempfile
from pathlib import Path

from unittest.mock import patch

from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory, SimpleTestCase, override_settings

import structlog
from parameterized import parameterized
from prometheus_client import REGISTRY
from structlog.testing import capture_logs

from posthog.models import User
from posthog.stable_chunks import (
    StableChunks,
    _resolve_stable_chunks,
    read_stable_chunks_manifest,
    stable_chunks_for_request,
)
from posthog.utils import get_context_for_template

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
            ("logged-out import is not a string", {**VALID_MANIFEST, "loggedOutImports": [1]}, False),
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
            ("production", False, False, True),
            ("tests", False, True, True),
            ("tests with debug on", True, True, True),
            ("the vite dev server", True, False, False),
        ]
    )
    def test_only_the_vite_dev_server_skips_the_stable_build(
        self, _name: str, debug: bool, test: bool, expect_stable: bool
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            dist = Path(directory) / "frontend" / "dist"
            dist.mkdir(parents=True)
            (dist / "stable-chunks-manifest.json").write_text(json.dumps(VALID_MANIFEST))
            _resolve_stable_chunks.cache_clear()
            self.addCleanup(_resolve_stable_chunks.cache_clear)

            with override_settings(BASE_DIR=directory, DEBUG=debug, TEST=test):
                assert (_resolve_stable_chunks() is not None) == expect_stable

    @parameterized.expand(
        [
            ("a signed-in page", "", None, True, True),
            ("a signed-out page", "", None, False, True),
            ("a page that fell back", "?stable_chunks=fallback", None, True, False),
            ("an old opt-out param", "?stable_chunks=0", None, True, True),
            ("an old opt-out cookie", "", "0", False, True),
        ]
    )
    def test_every_page_gets_the_stable_build_unless_it_fell_back(
        self, _name: str, query: str, cookie: str | None, authenticated: bool, expect_stable: bool
    ) -> None:
        request = RequestFactory().get(f"/{query}")
        request.user = User() if authenticated else AnonymousUser()
        if cookie:
            request.COOKIES["ph_stable_chunks"] = cookie
        stable = StableChunks(
            imports={"@c/eAAAA": "static/index-S0000000000.js"}, preload_js_urls=(), authenticated_preload_js_urls=()
        )

        with patch("posthog.stable_chunks._resolve_stable_chunks", return_value=stable):
            assert (stable_chunks_for_request(request) is not None) == expect_stable

    @parameterized.expand(
        [
            ("a chunk that failed to load", "?stable_chunks=fallback", "load_failed"),
            (
                "a chunk missing from the import map",
                "?stable_chunks=fallback&stable_chunks_unmapped=@c/Abc123",
                "unmapped_specifier",
            ),
            ("a value that is not a specifier", "?stable_chunks=fallback&stable_chunks_unmapped=<b>", "load_failed"),
        ]
    )
    def test_a_fallback_counts_why_it_reloaded(self, _name: str, query: str, reason: str) -> None:
        request = RequestFactory().get(f"/{query}")
        request.user = AnonymousUser()
        labels = {"authenticated": "false", "reason": reason}
        before = REGISTRY.get_sample_value("posthog_stable_chunks_fallback_total", labels) or 0

        assert stable_chunks_for_request(request) is None

        assert REGISTRY.get_sample_value("posthog_stable_chunks_fallback_total", labels) == before + 1

    def test_an_unmapped_specifier_is_logged_without_the_page_path(self) -> None:
        page_path = "/reset/0190a1b2-c3d4-7e5f-8a9b-0c1d2e3f4a5b/fake-reset-token"
        request = RequestFactory().get(
            f"{page_path}?stable_chunks=fallback&stable_chunks_unmapped=@c/Abc123",
            HTTP_REFERER=f"https://app.example.com{page_path}",
        )
        request.user = AnonymousUser()
        # The structlog context is thread-local, so an earlier test's `bind()` on this worker would leak into the event.
        structlog.get_logger().new()

        with capture_logs() as logs:
            stable_chunks_for_request(request)

        # posthog/settings/logs.py configures structlog with one context dict per thread. Nothing clears it between log calls.
        # Keys that earlier code bound on this thread appear on this event. A whole-dict comparison then depends on test order.
        [unmapped] = [log for log in logs if log["event"] == "stable_chunks_unmapped_specifier"]
        assert unmapped["specifier"] == "@c/Abc123"
        assert unmapped["log_level"] == "warning"
        assert "/reset/" not in str(unmapped)
        assert "fake-reset-token" not in str(unmapped)

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

    @parameterized.expand(
        [
            ("only its part of the map", frozenset({"@c/eAAAA"}), {"@c/eAAAA"}),
            ("the whole map from a build with no logged-out part", None, {"@c/eAAAA", "@c/eBBBB"}),
        ]
    )
    def test_a_logged_out_page_renders(self, _name, logged_out_specifiers, expected_specifiers):
        stable = StableChunks(
            imports={"@c/eAAAA": "static/index-S0000000000.js", "@c/eBBBB": "static/Insight-S1111111111.js"},
            preload_js_urls=(),
            authenticated_preload_js_urls=(),
            logged_out_specifiers=logged_out_specifiers,
        )

        context = self._context_with_stable_chunks(stable)

        assert set(json.loads(context["stable_chunks_importmap"])["imports"]) == expected_specifiers

    def test_no_eager_css_urls_keeps_the_single_preload_link(self):
        stable = StableChunks(
            imports={"@c/eAAAA": "static/index-S0000000000.js"}, preload_js_urls=(), authenticated_preload_js_urls=()
        )

        context = self._context_with_stable_chunks(stable)

        assert "stable_preload_css_urls" not in context
