import json
import tempfile
from pathlib import Path
from typing import Any, Optional

from unittest.mock import patch

from django.contrib.auth.models import AnonymousUser
from django.http import HttpRequest, HttpResponse
from django.test import RequestFactory, SimpleTestCase, override_settings

from parameterized import parameterized
from prometheus_client import REGISTRY

from posthog.models import User
from posthog.stable_chunks import StableChunks
from posthog.vite_app import (
    FRONTEND_BUILD_COOKIE,
    ViteApp,
    app_build_for_request,
    read_vite_app_manifest,
    remember_frontend_build_choice,
)

VALID_MANIFEST: dict[str, Any] = {
    "entry": "static/vite/index-S0000000000.js",
    "assetPrefix": "static/vite/",
    "imports": {
        "static/vite/chunk-login.js": "static/vite/chunk-S1111111111.js",
        "static/vite/chunk-dashboards.js": "static/vite/chunk-S2222222222.js",
    },
    "loggedOutImports": ["static/vite/chunk-login.js"],
    "eagerCss": ["static/vite/assets/index-AAAA.css"],
    "preload": {
        "js": ["static/vite/index-S0000000000.js"],
        "authenticatedJs": ["static/vite/chunk-S3333333333.js"],
        "css": ["static/vite/assets/app-BBBB.css"],
        "authenticatedCss": ["static/vite/assets/shell-CCCC.css"],
    },
    "chunkMap": "static/vite/chunk-map-DDDD.js",
}

STABLE_CHUNKS = StableChunks(
    imports={"@c/eAAAA": "static/index-S0000000000.js"}, preload_js_urls=(), authenticated_preload_js_urls=()
)


def _vite_app(manifest: dict[str, Any] = VALID_MANIFEST) -> Optional[ViteApp]:
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "vite-app-manifest.json"
        path.write_text(json.dumps(manifest))
        return read_vite_app_manifest(path)


def _user(kind: str) -> Any:
    if kind == "anonymous":
        return AnonymousUser()
    return User(is_staff=kind == "staff")


def _request(query: str, user_kind: str, cookie: Optional[str] = None) -> HttpRequest:
    request = RequestFactory().get(f"/{query}")
    request.user = _user(user_kind)
    if cookie is not None:
        request.COOKIES[FRONTEND_BUILD_COOKIE] = cookie
    return request


def _cookie_after(query: str, user_kind: str) -> Optional[str]:
    response = HttpResponse()
    remember_frontend_build_choice(_request(query, user_kind), response)
    morsel = response.cookies.get(FRONTEND_BUILD_COOKIE)
    return morsel.value if morsel is not None and morsel["max-age"] != 0 else None


@override_settings(DEBUG=False)
class TestViteApp(SimpleTestCase):
    @parameterized.expand(
        [
            ("valid", VALID_MANIFEST, True),
            ("no entry", {**VALID_MANIFEST, "entry": ""}, False),
            ("no asset prefix", {**VALID_MANIFEST, "assetPrefix": ""}, False),
            ("imports is not a mapping", {**VALID_MANIFEST, "imports": ["static/vite/index.js"]}, False),
            ("empty imports", {**VALID_MANIFEST, "imports": {}}, False),
            ("no chunk map", {key: value for key, value in VALID_MANIFEST.items() if key != "chunkMap"}, False),
            ("eager css url is not a string", {**VALID_MANIFEST, "eagerCss": [1]}, False),
            ("preload url is not a string", {**VALID_MANIFEST, "preload": {"js": [1]}}, False),
        ]
    )
    def test_manifest_problems_fall_back_to_the_esbuild_build(
        self, _name: str, manifest: dict[str, Any], expect_vite_app: bool
    ) -> None:
        assert (_vite_app(manifest) is not None) == expect_vite_app

    @parameterized.expand(
        [
            (
                "a signed-in page maps every chunk",
                False,
                {
                    "https://cdn.example.com/static/vite/chunk-login.js": "https://cdn.example.com/static/vite/chunk-S1111111111.js",
                    "https://cdn.example.com/static/vite/chunk-dashboards.js": "https://cdn.example.com/static/vite/chunk-S2222222222.js",
                },
            ),
            (
                "a logged-out page maps only what it can reach",
                True,
                {
                    "https://cdn.example.com/static/vite/chunk-login.js": "https://cdn.example.com/static/vite/chunk-S1111111111.js"
                },
            ),
        ]
    )
    def test_import_map_resolves_a_chunk_url_on_the_asset_host(
        self, _name: str, logged_out: bool, expected: dict[str, str]
    ) -> None:
        vite_app = _vite_app()
        assert vite_app is not None

        assert json.loads(vite_app.import_map_json("https://cdn.example.com", logged_out=logged_out)) == {
            "imports": expected
        }

    def test_import_map_cannot_close_its_script_tag(self) -> None:
        vite_app = _vite_app()
        assert vite_app is not None

        assert "</script>" not in vite_app.import_map_json("https://cdn.example.com</script><script>")

    @parameterized.expand(
        [
            ("a visitor who chose nothing", "anonymous", "", None, False, "stable"),
            ("a staff member who asks for it", "staff", "?frontend_build=vite", None, False, "vite"),
            ("a customer who asks for it", "customer", "?frontend_build=vite", None, False, "stable"),
            ("a signed-out visitor who asks for it", "anonymous", "?frontend_build=vite", None, False, "stable"),
            ("anyone in local development", "anonymous", "?frontend_build=vite", None, True, "vite"),
            ("a signed-out page after a staff member chose it", "anonymous", "", "staff choice", False, "vite"),
            ("a customer after a staff member chose it", "customer", "", "staff choice", False, "vite"),
            ("a cookie nobody signed", "anonymous", "", "vite", False, "stable"),
            ("a staff member who goes back", "staff", "?frontend_build=default", "staff choice", False, "stable"),
            ("a page that fell back", "staff", "?stable_chunks=fallback", "staff choice", False, "default"),
        ]
    )
    def test_only_a_choice_a_staff_member_made_gets_the_vite_build(
        self, _name: str, user_kind: str, query: str, cookie: Optional[str], debug: bool, expected_build: str
    ) -> None:
        if cookie == "staff choice":
            cookie = _cookie_after("?frontend_build=vite", "staff")
            assert cookie is not None
        request = _request(query, user_kind, cookie)
        vite_app = _vite_app()

        with (
            override_settings(DEBUG=debug),
            patch("posthog.vite_app._resolve_vite_app", return_value=vite_app),
            patch("posthog.stable_chunks._resolve_stable_chunks", return_value=STABLE_CHUNKS),
        ):
            picked_vite_app, picked_stable_chunks = app_build_for_request(request)

        picked = "vite" if picked_vite_app else "stable" if picked_stable_chunks else "default"
        assert picked == expected_build

    @parameterized.expand(
        [
            ("a staff member who asks for it", "staff", "?frontend_build=vite", True),
            ("a customer who asks for it", "customer", "?frontend_build=vite", False),
            ("a signed-out visitor who asks for it", "anonymous", "?frontend_build=vite", False),
            ("a staff member who goes back", "staff", "?frontend_build=default", False),
            ("a staff member on any other page", "staff", "", False),
        ]
    )
    def test_only_a_staff_member_gets_the_cookie_that_keeps_the_choice(
        self, _name: str, user_kind: str, query: str, expect_cookie: bool
    ) -> None:
        assert (_cookie_after(query, user_kind) is not None) == expect_cookie

    def test_a_missing_vite_build_serves_the_stable_build(self) -> None:
        request = _request("?frontend_build=vite", "staff")

        with (
            patch("posthog.vite_app._resolve_vite_app", return_value=None),
            patch("posthog.stable_chunks._resolve_stable_chunks", return_value=STABLE_CHUNKS),
        ):
            assert app_build_for_request(request) == (None, STABLE_CHUNKS)

    def test_a_fallback_from_the_vite_build_is_counted_as_its_own(self) -> None:
        request = _request("?stable_chunks=fallback", "staff", _cookie_after("?frontend_build=vite", "staff"))
        vite_labels = {"authenticated": "true"}
        stable_labels = {"authenticated": "true", "reason": "load_failed"}
        vite_before = REGISTRY.get_sample_value("posthog_vite_app_fallback_total", vite_labels) or 0
        stable_before = REGISTRY.get_sample_value("posthog_stable_chunks_fallback_total", stable_labels) or 0

        with patch("posthog.vite_app._resolve_vite_app", return_value=_vite_app()):
            app_build_for_request(request)

        assert REGISTRY.get_sample_value("posthog_vite_app_fallback_total", vite_labels) == vite_before + 1
        assert (REGISTRY.get_sample_value("posthog_stable_chunks_fallback_total", stable_labels) or 0) == stable_before
