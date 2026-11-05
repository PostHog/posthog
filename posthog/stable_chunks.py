"""
Serving of the frontend build with stable chunk names.

The build writes a second copy of the app's JS in which chunks import each other through identity
specifiers, plus `stable-chunks-manifest.json` with the import map that resolves them (see
frontend/bin/stableChunkNames.mjs). A chunk's URL then changes only when its own code changes,
so a deploy no longer makes returning users download every chunk that imports a changed one.

Every app page gets this build, except a page that reloads after a stable chunk failed to load.
Without a readable manifest, pages render the hashed build.
"""

import os
import re
import json
from functools import lru_cache
from typing import Optional

from django.conf import settings
from django.http import HttpRequest

import structlog
from prometheus_client import Counter

from posthog.dataclasses import frozen
from posthog.exceptions_capture import capture_exception

logger = structlog.get_logger(__name__)

STABLE_CHUNKS_PARAM = "stable_chunks"
STABLE_CHUNKS_UNMAPPED_PARAM = "stable_chunks_unmapped"

STABLE_CHUNKS_FALLBACK_COUNTER = Counter(
    "posthog_stable_chunks_fallback",
    "App shell requests that reload on the hashed build because the stable entry failed to load.",
    labelnames=["authenticated", "reason"],
)
_STABLE_CHUNK_SPECIFIER = re.compile(r"@c/[A-Za-z0-9]+")


@frozen
class StableChunks:
    # import map specifier -> file path relative to JS_URL
    imports: dict[str, str]
    preload_js_urls: tuple[str, ...]
    authenticated_preload_js_urls: tuple[str, ...]
    # The split eager stylesheets, in link order. Empty for a build that does not split its CSS.
    eager_css_urls: tuple[str, ...] = ()
    # The specifiers a logged-out page can reach. None for a build that does not scope its import map.
    logged_out_specifiers: Optional[frozenset[str]] = None

    def import_map_json(self, js_url: str, logged_out: bool = False) -> str:
        imports = self.imports
        if logged_out and self.logged_out_specifiers is not None:
            imports = {
                specifier: path for specifier, path in imports.items() if specifier in self.logged_out_specifiers
            }
        import_map = json.dumps({"imports": {specifier: f"{js_url}/{path}" for specifier, path in imports.items()}})
        # The template renders this inside <script> with |safe, and js_url can follow the request
        # origin (get_js_url), so "<" must never reach the page unescaped.
        return import_map.replace("<", "\\u003c")

    def preload_urls(self, include_authenticated_shell: bool) -> tuple[str, ...]:
        urls = [*self.preload_js_urls, *(self.authenticated_preload_js_urls if include_authenticated_shell else ())]
        return tuple(dict.fromkeys(urls))


def read_stable_chunks_manifest(manifest_path: str) -> Optional[StableChunks]:
    """
    Parse the manifest defensively. A missing or malformed manifest serves the hashed build rather
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
        logged_out_imports = manifest.get("loggedOutImports")
        if not (
            isinstance(imports, dict)
            and imports
            and all(isinstance(k, str) and isinstance(v, str) for k, v in imports.items())
            and isinstance(js, list)
            and isinstance(authenticated_js, list)
            and isinstance(eager_css, list)
            and all(isinstance(url, str) for url in [*js, *authenticated_js, *eager_css])
            and (
                logged_out_imports is None
                or (
                    isinstance(logged_out_imports, list)
                    and all(isinstance(specifier, str) for specifier in logged_out_imports)
                )
            )
        ):
            raise ValueError("stable chunks manifest fields have unexpected types")
        return StableChunks(
            imports=imports,
            preload_js_urls=tuple(js),
            authenticated_preload_js_urls=tuple(authenticated_js),
            eager_css_urls=tuple(eager_css),
            logged_out_specifiers=frozenset(logged_out_imports) if logged_out_imports is not None else None,
        )
    except Exception as e:
        logger.warning("stable_chunks_manifest_unreadable", manifest_path=manifest_path, error=str(e))
        capture_exception(e)
        return None


@lru_cache(maxsize=1)
def _resolve_stable_chunks() -> Optional[StableChunks]:
    # The Vite dev server serves source modules, so a manifest left in dist from an older build is stale.
    if settings.DEBUG and not settings.TEST:
        return None
    return read_stable_chunks_manifest(
        os.path.join(settings.BASE_DIR, "frontend", "dist", "stable-chunks-manifest.json")
    )


def _count_fallback(request: HttpRequest) -> None:
    unmapped = request.GET.get(STABLE_CHUNKS_UNMAPPED_PARAM, "")
    is_unmapped = _STABLE_CHUNK_SPECIFIER.fullmatch(unmapped) is not None
    if is_unmapped:
        # Never log the path: reset and invite links carry their credential in it.
        logger.warning("stable_chunks_unmapped_specifier", specifier=unmapped)
    STABLE_CHUNKS_FALLBACK_COUNTER.labels(
        authenticated=str(request.user.is_authenticated).lower(),
        reason="unmapped_specifier" if is_unmapped else "load_failed",
    ).inc()


def stable_chunks_for_request(request: HttpRequest) -> Optional[StableChunks]:
    # A page that fell back gets the hashed build, so the chunk that failed cannot fail it again.
    if request.GET.get(STABLE_CHUNKS_PARAM) == "fallback":
        _count_fallback(request)
        return None
    return _resolve_stable_chunks()
