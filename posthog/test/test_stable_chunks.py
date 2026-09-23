import json
import tempfile
from pathlib import Path

from django.test import RequestFactory, SimpleTestCase

from parameterized import parameterized

from posthog.stable_chunks import STABLE_CHUNKS_COOKIE, read_stable_chunks_manifest, stable_chunks_opted_in

VALID_MANIFEST = {
    "imports": {"@c/eAAAA": "static/index-S0000000000.js"},
    "preload": {"js": ["static/index-S0000000000.js"], "authenticatedJs": ["static/chunk-S1111111111.js"]},
}


class TestStableChunks(SimpleTestCase):
    @parameterized.expand(
        [
            ("valid", VALID_MANIFEST, True),
            ("imports is not a mapping", {**VALID_MANIFEST, "imports": ["static/index.js"]}, False),
            ("empty imports", {**VALID_MANIFEST, "imports": {}}, False),
            ("preload url is not a string", {**VALID_MANIFEST, "preload": {"js": [1], "authenticatedJs": []}}, False),
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
