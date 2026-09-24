"""
Opt-in serving of the frontend build with stable chunk names.

The build writes a second copy of the app's JS in which chunks import each other through identity
specifiers, plus `stable-chunks-manifest.json` with the import map that resolves them (see
common/esbuilder/stableChunkNames.mjs). A chunk's URL then changes only when its own code changes,
so a deploy no longer makes returning users download every chunk that imports a changed one.

Serving it is opt-in per browser while it is tested: `?stable_chunks=1` sets a cookie and
`?stable_chunks=0` clears it. Without the cookie, or without a readable manifest, pages render
exactly as before.
"""

import os
import json
from functools import lru_cache
from typing import Optional

from django.conf import settings
from django.http import HttpRequest, HttpResponse

import structlog

from posthog.dataclasses import frozen
from posthog.exceptions_capture import capture_exception

logger = structlog.get_logger(__name__)

STABLE_CHUNKS_PARAM = "stable_chunks"
STABLE_CHUNKS_COOKIE = "ph_stable_chunks"
_COOKIE_MAX_AGE_SECONDS = 60 * 60 * 24 * 30


@frozen
class StableChunks:
    # import map specifier -> file path relative to JS_URL
    imports: dict[str, str]
    preload_js_urls: tuple[str, ...]
    authenticated_preload_js_urls: tuple[str, ...]
    # The split eager stylesheets, in link order. Empty for a build that does not split its CSS.
    eager_css_urls: tuple[str, ...] = ()

    def import_map_json(self, js_url: str) -> str:
        import_map = json.dumps(
            {"imports": {specifier: f"{js_url}/{path}" for specifier, path in self.imports.items()}}
        )
        # The template renders this inside <script> with |safe, and js_url can follow the request
        # origin (get_js_url), so "<" must never reach the page unescaped.
        return import_map.replace("<", "\\u003c")

    def preload_urls(self, include_authenticated_shell: bool) -> tuple[str, ...]:
        urls = [*self.preload_js_urls, *(self.authenticated_preload_js_urls if include_authenticated_shell else ())]
        return tuple(dict.fromkeys(urls))


def read_stable_chunks_manifest(manifest_path: str) -> Optional[StableChunks]:
    """
    Parse the manifest defensively. A missing or malformed manifest turns the opt-in off rather
    than breaking page rendering, and is reported, because the caller caches the result per process.
    """
    try:
        if not os.path.isfile(manifest_path):
            return None
        with open(manifest_path) as f:
            manifest = json.load(f)
        imports = manifest.get("imports")
        preload = manifest.get("preload", {})
        js = preload.get("js", [])
        authenticated_js = preload.get("authenticatedJs", [])
        eager_css = manifest.get("eagerCss", [])
        if not (
            isinstance(imports, dict)
            and imports
            and all(isinstance(k, str) and isinstance(v, str) for k, v in imports.items())
            and isinstance(js, list)
            and isinstance(authenticated_js, list)
            and isinstance(eager_css, list)
            and all(isinstance(url, str) for url in [*js, *authenticated_js, *eager_css])
        ):
            raise ValueError("stable chunks manifest fields have unexpected types")
        return StableChunks(
            imports=imports,
            preload_js_urls=tuple(js),
            authenticated_preload_js_urls=tuple(authenticated_js),
            eager_css_urls=tuple(eager_css),
        )
    except Exception as e:
        logger.warning("stable_chunks_manifest_unreadable", manifest_path=manifest_path, error=str(e))
        capture_exception(e)
        return None


@lru_cache(maxsize=1)
def _resolve_stable_chunks() -> Optional[StableChunks]:
    if settings.DEBUG or settings.TEST:
        return None
    return read_stable_chunks_manifest(
        os.path.join(settings.BASE_DIR, "frontend", "dist", "stable-chunks-manifest.json")
    )


def stable_chunks_opted_in(request: HttpRequest) -> bool:
    param = request.GET.get(STABLE_CHUNKS_PARAM)
    if param is not None:
        return param == "1"
    return request.COOKIES.get(STABLE_CHUNKS_COOKIE) == "1"


def stable_chunks_for_request(request: HttpRequest) -> Optional[StableChunks]:
    return _resolve_stable_chunks() if stable_chunks_opted_in(request) else None


def persist_stable_chunks_choice(request: HttpRequest, response: HttpResponse) -> None:
    param = request.GET.get(STABLE_CHUNKS_PARAM)
    if param == "1":
        response.set_cookie(
            STABLE_CHUNKS_COOKIE,
            "1",
            max_age=_COOKIE_MAX_AGE_SECONDS,
            secure=request.is_secure(),
            httponly=True,
            samesite="Lax",
        )
    elif param == "0":
        response.delete_cookie(STABLE_CHUNKS_COOKIE)
