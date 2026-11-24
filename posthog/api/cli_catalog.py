"""The API tool catalog that hog downloads, so it can run tools added after its own release.

`services/mcp/scripts/build-cli-catalog.ts` writes the file from the MCP tool code of this checkout.
The image build runs it, so each deployment serves the catalog of the code it runs, and the dev
stack runs it when the backend starts.
"""

import re
import gzip
import hashlib
import threading
from dataclasses import field
from pathlib import Path

from django.conf import settings
from django.http import HttpRequest, HttpResponse, HttpResponseBase, JsonResponse
from django.utils.cache import get_conditional_response, patch_cache_control, patch_vary_headers
from django.views.decorators.http import require_safe

from posthog.dataclasses import frozen

CLI_CATALOG_JSON = Path(settings.BASE_DIR) / "services" / "mcp" / "dist" / "cli-catalog.json"
BUILD_COMMAND = "pnpm --filter=@posthog/mcp run build:cli:catalog"

# hog checks for a new catalog once a day, and a deploy is the only thing that changes it.
CACHE_MAX_AGE_SECONDS = 60 * 60


@frozen
class CliCatalogBody:
    path: Path
    modified_ns: int
    etag: str
    json: bytes = field(repr=False)
    gzipped: bytes = field(repr=False)


_lock = threading.Lock()
_cached: CliCatalogBody | None = None


def load_cli_catalog(path: Path) -> CliCatalogBody | None:
    """The catalog file and its gzip, read again only when the file changes, or None without a file."""
    global _cached
    try:
        modified_ns = path.stat().st_mtime_ns
    except FileNotFoundError:
        return None

    with _lock:
        if _cached is None or (_cached.path, _cached.modified_ns) != (path, modified_ns):
            body = path.read_bytes()
            _cached = CliCatalogBody(
                path=path,
                modified_ns=modified_ns,
                etag=f'W/"{hashlib.sha256(body).hexdigest()[:32]}"',
                json=body,
                gzipped=gzip.compress(body, mtime=0),
            )
        return _cached


@require_safe
def cli_catalog(request: HttpRequest) -> HttpResponseBase:
    # Public: the catalog only describes the API tools in this public repo, and hog reads it before login.
    catalog = load_cli_catalog(CLI_CATALOG_JSON)
    if catalog is None:
        return JsonResponse(
            {"detail": f"This PostHog has no CLI tool catalog. Build it with `{BUILD_COMMAND}`."}, status=404
        )

    accepts_gzip = re.search(r"\bgzip\b", request.headers.get("Accept-Encoding", "")) is not None
    response = HttpResponse(catalog.gzipped if accepts_gzip else catalog.json, content_type="application/json")
    if accepts_gzip:
        response["Content-Encoding"] = "gzip"
    response["ETag"] = catalog.etag
    patch_cache_control(response, public=True, max_age=CACHE_MAX_AGE_SECONDS)
    patch_vary_headers(response, ["Accept-Encoding"])
    return get_conditional_response(request, etag=catalog.etag, response=response) or response
