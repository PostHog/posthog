"""
Flag-gated serving of the frontend build with stable chunk names.

The build writes a second copy of the app's JS in which chunks import each other through identity
specifiers, plus `stable-chunks-manifest.json` with the import map that resolves them (see
frontend/bin/stableChunkNames.mjs). A chunk's URL then changes only when its own code changes,
so a deploy no longer makes returning users download every chunk that imports a changed one.

Which build a request gets is decided by `stable_chunks_choice`. Without a readable manifest,
pages render exactly as before.
"""

import os
import json
from collections.abc import Mapping
from functools import lru_cache
from typing import Any, Optional

from django.conf import settings
from django.http import HttpRequest, HttpResponse

import structlog
import posthoganalytics
from prometheus_client import Counter

from posthog.dataclasses import frozen
from posthog.exceptions_capture import capture_exception

logger = structlog.get_logger(__name__)

STABLE_CHUNKS_PARAM = "stable_chunks"
STABLE_CHUNKS_COOKIE = "ph_stable_chunks"
STABLE_CHUNKS_FLAG = "stable-chunk-names"
_COOKIE_MAX_AGE_SECONDS = 60 * 60 * 24 * 30
# A logged-out request has no person, so every logged-out request evaluates the flag with this one
# ID. A partial rollout therefore switches all logged-out pages on or off together.
LOGGED_OUT_FLAG_DISTINCT_ID = "stable-chunks-logged-out"

STABLE_CHUNKS_FALLBACK_COUNTER = Counter(
    "posthog_stable_chunks_fallback",
    "App shell requests that reload on the hashed build because the stable entry failed to load.",
    labelnames=["authenticated"],
)


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


def stable_chunks_choice(request: HttpRequest, feature_flags: Optional[Mapping[str, Any]]) -> bool:
    """
    The query param wins, then the cookie, then the flag. For a logged-in user, `feature_flags` are
    the ones bootstrapped into posthog-js, so events carry the flag value that picked the build.
    A logged-out request has no bootstrapped flags, so it evaluates the flag locally.
    """
    param = request.GET.get(STABLE_CHUNKS_PARAM)
    if param is not None:
        if param == "fallback":
            STABLE_CHUNKS_FALLBACK_COUNTER.labels(authenticated=str(request.user.is_authenticated).lower()).inc()
        return param == "1"

    cookie = request.COOKIES.get(STABLE_CHUNKS_COOKIE)
    if cookie in ("0", "1"):
        return cookie == "1"

    if not request.user.is_authenticated:
        return _flag_enabled_for_logged_out_requests()

    if not feature_flags:
        return False

    return feature_flags.get(STABLE_CHUNKS_FLAG) is True


def _flag_enabled_for_logged_out_requests() -> bool:
    return (
        posthoganalytics.feature_enabled(
            STABLE_CHUNKS_FLAG,
            LOGGED_OUT_FLAG_DISTINCT_ID,
            only_evaluate_locally=True,
            send_feature_flag_events=False,
        )
        is True
    )


def stable_chunks_for_request(
    request: HttpRequest, feature_flags: Optional[Mapping[str, Any]]
) -> Optional[StableChunks]:
    return _resolve_stable_chunks() if stable_chunks_choice(request, feature_flags) else None


def persist_stable_chunks_choice(request: HttpRequest, response: HttpResponse) -> None:
    param = request.GET.get(STABLE_CHUNKS_PARAM)
    if param in ("0", "1"):
        response.set_cookie(
            STABLE_CHUNKS_COOKIE,
            param,
            max_age=_COOKIE_MAX_AGE_SECONDS,
            secure=request.is_secure(),
            httponly=True,
            samesite="Lax",
        )
