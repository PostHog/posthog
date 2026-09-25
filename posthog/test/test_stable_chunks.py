import json
import tempfile
from pathlib import Path

from unittest.mock import patch

from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory, SimpleTestCase, override_settings

from parameterized import parameterized

from posthog.stable_chunks import StableChunks, read_stable_chunks_manifest, stable_chunks_for_request
from posthog.utils import get_context_for_template

VALID_MANIFEST = {
    "imports": {"@c/eAAAA": "static/index-S0000000000.js"},
    "preload": {"js": ["static/index-S0000000000.js"], "authenticatedJs": ["static/chunk-S1111111111.js"]},
    "eagerCss": ["static/stylesEagerTailwind-AAAA1111.css", "static/stylesEagerApp-BBBB2222.css"],
}
STABLE = StableChunks(
    imports={"@c/eAAAA": "static/index-S0000000000.js"}, preload_js_urls=(), authenticated_preload_js_urls=()
)


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
            ("manifest present", "", {}, STABLE, True),
            ("fallback", "?stable_chunks=fallback", {}, STABLE, False),
            ("no manifest", "", {}, None, False),
            ("old opt-out param", "?stable_chunks=0", {}, STABLE, True),
            ("old opt-out cookie", "", {"ph_stable_chunks": "0"}, STABLE, True),
        ]
    )
    def test_which_build_a_request_gets(
        self, _name: str, query: str, cookies: dict[str, str], manifest: StableChunks | None, expect_stable: bool
    ) -> None:
        request = RequestFactory().get(f"/{query}")
        request.COOKIES.update(cookies)

        with patch("posthog.stable_chunks._resolve_stable_chunks", return_value=manifest):
            assert (stable_chunks_for_request(request) is not None) == expect_stable

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
        context = self._context_with_stable_chunks(STABLE)

        assert "stable_preload_css_urls" not in context
