"""
Serving of the app build that Vite makes.

`pnpm build:vite-app` writes this build next to the esbuild build, with `vite-app-manifest.json`
(see frontend/bin/viteAppBuild.mjs). It is the same app from a second bundler, and it runs
alongside the esbuild build until it has proven itself.

Only a staff member can choose it, with `?frontend_build=vite`. The choice is kept in a signed
cookie, so it also holds on the pages that the staff member sees while signed out, such as the
login page. `?frontend_build=default` clears it.

A page on this build that fails to load a chunk reloads with `?stable_chunks=fallback`, as a page on
the stable chunk build does, and gets the default esbuild build.
"""

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal, Optional

from django.conf import settings
from django.http import HttpRequest, HttpResponse

import structlog
from prometheus_client import Counter

from posthog.dataclasses import frozen
from posthog.exceptions_capture import capture_exception
from posthog.stable_chunks import STABLE_CHUNKS_PARAM, StableChunks, stable_chunks_for_request

logger = structlog.get_logger(__name__)

FRONTEND_BUILD_PARAM = "frontend_build"
FRONTEND_BUILD_COOKIE = "ph_frontend_build"
VITE_BUILD = "vite"
DEFAULT_BUILD = "default"

_COOKIE_SALT = "posthog.vite_app.frontend_build"
_COOKIE_MAX_AGE_SECONDS = 30 * 24 * 60 * 60

VITE_APP_SHELL_COUNTER = Counter(
    "posthog_vite_app_shell",
    "App shell requests served with the Vite build.",
    labelnames=["authenticated"],
)
VITE_APP_FALLBACK_COUNTER = Counter(
    "posthog_vite_app_fallback",
    "App shell requests that reload on the default build because the Vite build failed to load.",
    labelnames=["authenticated"],
)


@frozen
class ViteApp:
    # Every path is relative to JS_URL.
    entry: str
    # The directory of the build. The chunk map and the build's own code name files relative to it.
    asset_prefix: str
    # import map: placeholder path -> file path
    imports: dict[str, str]
    # The placeholders a logged-out page can reach.
    logged_out_specifiers: frozenset[str]
    # The stylesheets the page links before the entry runs, in cascade order.
    eager_css_urls: tuple[str, ...]
    preload_js_urls: tuple[str, ...]
    authenticated_preload_js_urls: tuple[str, ...]
    preload_css_urls: tuple[str, ...]
    authenticated_preload_css_urls: tuple[str, ...]
    chunk_map: str

    def import_map_json(self, js_url: str, logged_out: bool = False) -> str:
        imports = self.imports
        if logged_out:
            imports = {
                specifier: path for specifier, path in imports.items() if specifier in self.logged_out_specifiers
            }
        # A chunk imports another by a relative URL, which the browser resolves against the chunk's
        # own URL before it looks in the import map. So the keys carry JS_URL too, not only the values.
        import_map = json.dumps(
            {"imports": {f"{js_url}/{specifier}": f"{js_url}/{path}" for specifier, path in imports.items()}}
        )
        # The template renders this inside <script> with |safe, and js_url can follow the request
        # origin (get_js_url), so "<" must never reach the page unescaped.
        return import_map.replace("<", "\\u003c")

    def template_context(self, js_url: str, is_authenticated: bool) -> dict[str, Any]:
        """The keys of the app shell template that this build fills. See frontend/src/index.html."""
        preload_js = [*self.preload_js_urls, *(self.authenticated_preload_js_urls if is_authenticated else ())]
        preload_css = [*self.preload_css_urls, *(self.authenticated_preload_css_urls if is_authenticated else ())]
        return {
            "vite_app": True,
            "vite_app_boot": {
                "entry": self.entry,
                "assetPrefix": self.asset_prefix,
                "eagerCss": self.eager_css_urls,
                "chunkMap": self.chunk_map,
            },
            "stable_chunks_importmap": self.import_map_json(js_url, logged_out=not is_authenticated),
            "preload_js_urls": tuple(dict.fromkeys(preload_js)),
            # The boot script links the eager stylesheets. The page only preloads them here.
            "preload_css_url": "",
            "stable_preload_css_urls": tuple(dict.fromkeys([*self.eager_css_urls, *preload_css])),
        }


def read_vite_app_manifest(manifest_path: Path) -> Optional[ViteApp]:
    """
    Parse the manifest defensively. A missing or malformed manifest serves the esbuild build rather
    than breaking page rendering, and is reported, because the caller caches the result per process.
    """
    try:
        if not manifest_path.is_file():
            return None
        manifest = json.loads(manifest_path.read_text())
        entry = manifest.get("entry")
        asset_prefix = manifest.get("assetPrefix")
        imports = manifest.get("imports")
        chunk_map = manifest.get("chunkMap")
        preload = manifest.get("preload", {})
        url_lists = {
            "loggedOutImports": manifest.get("loggedOutImports", []),
            "eagerCss": manifest.get("eagerCss", []),
            "js": preload.get("js", []),
            "authenticatedJs": preload.get("authenticatedJs", []),
            "css": preload.get("css", []),
            "authenticatedCss": preload.get("authenticatedCss", []),
        }
        if not (
            isinstance(entry, str)
            and entry
            and isinstance(asset_prefix, str)
            and asset_prefix
            and isinstance(chunk_map, str)
            and isinstance(imports, dict)
            and imports
            and all(isinstance(k, str) and isinstance(v, str) for k, v in imports.items())
            and all(isinstance(urls, list) and all(isinstance(url, str) for url in urls) for urls in url_lists.values())
        ):
            raise ValueError("vite app manifest fields have unexpected types")
        return ViteApp(
            entry=entry,
            asset_prefix=asset_prefix,
            imports=imports,
            logged_out_specifiers=frozenset(url_lists["loggedOutImports"]),
            eager_css_urls=tuple(url_lists["eagerCss"]),
            preload_js_urls=tuple(url_lists["js"]),
            authenticated_preload_js_urls=tuple(url_lists["authenticatedJs"]),
            preload_css_urls=tuple(url_lists["css"]),
            authenticated_preload_css_urls=tuple(url_lists["authenticatedCss"]),
            chunk_map=chunk_map,
        )
    except Exception as e:
        logger.warning("vite_app_manifest_unreadable", manifest_path=str(manifest_path), error=str(e))
        capture_exception(e)
        return None


@lru_cache(maxsize=1)
def _resolve_vite_app() -> Optional[ViteApp]:
    return read_vite_app_manifest(Path(settings.BASE_DIR) / "frontend" / "dist" / "vite" / "vite-app-manifest.json")


def chosen_frontend_build(*, param: Optional[str], may_choose: bool) -> Optional[Literal["vite", "default"]]:
    """The build a request asks for in its query string, or None when it asks for none or may not choose."""
    if not may_choose:
        return None
    if param == VITE_BUILD:
        return VITE_BUILD
    if param == DEFAULT_BUILD:
        return DEFAULT_BUILD
    return None


def _is_authenticated(request: HttpRequest) -> bool:
    return bool(request.user and request.user.is_authenticated)


def _may_choose(request: HttpRequest) -> bool:
    # In local development every visitor may choose, so the login page can be checked without a staff account.
    return settings.DEBUG or (_is_authenticated(request) and bool(request.user.is_staff))


def _chosen(request: HttpRequest) -> Optional[Literal["vite", "default"]]:
    return chosen_frontend_build(param=request.GET.get(FRONTEND_BUILD_PARAM), may_choose=_may_choose(request))


def _wants_vite_app(request: HttpRequest) -> bool:
    chosen = _chosen(request)
    if chosen is not None:
        return chosen == VITE_BUILD
    # Only a staff member's request can have set this cookie, because it is signed.
    remembered = request.get_signed_cookie(
        FRONTEND_BUILD_COOKIE, default=None, salt=_COOKIE_SALT, max_age=_COOKIE_MAX_AGE_SECONDS
    )
    return remembered == VITE_BUILD


def app_build_for_request(request: HttpRequest) -> tuple[Optional[ViteApp], Optional[StableChunks]]:
    """
    Which build the app shell boots: the Vite build, the stable chunk build, or (when both are None)
    the default esbuild build.
    """
    if _wants_vite_app(request):
        authenticated = str(_is_authenticated(request)).lower()
        # A page that fell back gets the default build, so the chunk that failed cannot fail it again.
        if request.GET.get(STABLE_CHUNKS_PARAM) == "fallback":
            VITE_APP_FALLBACK_COUNTER.labels(authenticated=authenticated).inc()
            return None, None
        vite_app = _resolve_vite_app()
        if vite_app is not None:
            VITE_APP_SHELL_COUNTER.labels(authenticated=authenticated).inc()
            return vite_app, None
    return None, stable_chunks_for_request(request)


def remember_frontend_build_choice(request: HttpRequest, response: HttpResponse) -> None:
    """Keeps a build chosen in the query string for the visitor's later page loads."""
    chosen = _chosen(request)
    if chosen == VITE_BUILD:
        response.set_signed_cookie(
            FRONTEND_BUILD_COOKIE,
            VITE_BUILD,
            salt=_COOKIE_SALT,
            max_age=_COOKIE_MAX_AGE_SECONDS,
            httponly=True,
            samesite="Lax",
            secure=settings.SESSION_COOKIE_SECURE,
        )
    elif chosen == DEFAULT_BUILD:
        response.delete_cookie(FRONTEND_BUILD_COOKIE)
