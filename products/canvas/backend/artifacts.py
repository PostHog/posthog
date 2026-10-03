"""The canvas artifact origin: serves built canvas files to sandboxed iframes.

Artifacts are untrusted user content, so they are served from a dedicated
origin (``CANVAS_ARTIFACT_ORIGIN``) that fails closed: in production the view
refuses to answer on any other Host, keeping user code off the application
origin. Access is capability-based — a signed, time-boxed token minted for the
authenticated client is the only credential, so the artifact origin itself
holds no cookies or sessions.

Integrity is verified when artifacts are written and again when they are read
from object storage. The manifest hash is also used as the response ETag.
"""

import re
import math
import time
import hashlib
import functools
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlsplit
from uuid import UUID

from django.conf import settings
from django.core import signing
from django.http import Http404, HttpRequest, HttpResponse, HttpResponseNotModified
from django.views.decorators.clickjacking import xframe_options_exempt

from posthog.csp_middleware import app_frame_ancestor_sources
from posthog.dataclasses import frozen
from posthog.storage import object_storage
from posthog.storage.object_storage import ObjectStorageError

from products.canvas.backend.contract import artifact_csp
from products.canvas.backend.models import CanvasBuild

ARTIFACT_TOKEN_SALT = "posthog.canvas.artifact.v1"
# Tokens embed a coarse time bucket instead of a per-second timestamp, so the
# artifact URL for a build is stable within a bucket (the iframe src doesn't
# churn on every lifecycle poll) while still expiring: a token is accepted for
# its own bucket and the next one, i.e. between one and two hours.
ARTIFACT_TOKEN_BUCKET_SECONDS = 3600

# Generated from the desktop's sandboxRuntime.ts by `pnpm --filter @posthog/ui
# generate-web-sandbox`. Do not edit it by hand.
SANDBOX_DOCUMENT_PATH = Path(__file__).parent / "sandbox" / "sandbox_document.html"
ARTIFACT_PERMISSIONS_POLICY = "camera=(), microphone=(), geolocation=(), payment=(), usb=()"


def _configured_artifact_host() -> str | None:
    origin = urlparse(settings.CANVAS_ARTIFACT_ORIGIN)
    if (
        origin.scheme != "https"
        or not origin.netloc
        or origin.username
        or origin.password
        or origin.path not in {"", "/"}
        or origin.query
        or origin.fragment
    ):
        return None
    return origin.netloc.lower()


def _artifact_signing_keys() -> list[str]:
    configured = settings.CANVAS_ARTIFACT_SIGNING_KEYS
    return configured or [settings.SECRET_KEY, *settings.SECRET_KEY_FALLBACKS]


def _artifact_delivery_enabled(keys: list[str]) -> bool:
    if not keys or (not settings.CANVAS_ARTIFACT_ORIGIN and not (settings.DEBUG or settings.TEST)):
        return False
    return bool(settings.DEBUG or settings.TEST) or (len(keys[0]) >= 32 and _configured_artifact_host() is not None)


def create_canvas_artifact_token(build: CanvasBuild) -> str | None:
    keys = _artifact_signing_keys()
    if not _artifact_delivery_enabled(keys):
        return None
    bucket = int(time.time() // ARTIFACT_TOKEN_BUCKET_SECONDS)
    return signing.Signer(key=keys[0], salt=ARTIFACT_TOKEN_SALT).sign_object(
        {"team_id": build.team_id, "canvas_id": str(build.canvas_id), "build_id": str(build.id), "bucket": bucket},
        compress=True,
    )


def _artifact_origin() -> str:
    """The origin artifacts are linked from and served on.

    DEBUG/TEST with no CANVAS_ARTIFACT_ORIGIN falls back to the application
    origin (SITE_URL) purely as a local-dev convenience: the view's host check
    is skipped in those modes, so the canvas renders without standing up a
    second origin. This must never happen in production — the boot check
    (checks.py) fails the deploy on a half-configured non-DEBUG origin, and the
    view enforces the dedicated host there — because serving built user HTML
    off the app origin would put untrusted markup in the session's origin.
    """
    return settings.CANVAS_ARTIFACT_ORIGIN or settings.SITE_URL


def create_canvas_artifact_url(build: CanvasBuild, artifact_path: str) -> str | None:
    token = create_canvas_artifact_token(build)
    if token is None:
        return None
    return f"{_artifact_origin()}/canvas-artifacts/{token}/{artifact_path}"


def _read_token(token: str) -> dict[str, Any]:
    current_bucket = int(time.time() // ARTIFACT_TOKEN_BUCKET_SECONDS)
    for key in _artifact_signing_keys():
        try:
            value = signing.Signer(key=key, salt=ARTIFACT_TOKEN_SALT).unsign_object(token)
        except signing.BadSignature:
            continue
        if isinstance(value, dict) and value.get("bucket") in (current_bucket, current_bucket - 1):
            return value
    raise Http404


def _require_artifact_host(host: str) -> None:
    configured_host = _configured_artifact_host()
    if settings.CANVAS_ARTIFACT_ORIGIN and (configured_host is None or host.lower() != configured_host):
        raise Http404


@frozen
class _SandboxDocument:
    content: bytes
    content_hash: str


def _parse_sandbox_document(content: bytes) -> _SandboxDocument:
    return _SandboxDocument(
        content=content,
        content_hash=hashlib.sha256(content).hexdigest(),
    )


@functools.cache
def _sandbox_document() -> _SandboxDocument:
    return _parse_sandbox_document(SANDBOX_DOCUMENT_PATH.read_bytes())


@functools.cache
def _publish_sandbox_document(document: _SandboxDocument) -> None:
    object_storage.write(f"canvas_sandbox/{document.content_hash}/index.html", document.content)


def _canvas_sandbox_document_csp() -> str:
    site = urlsplit(settings.SITE_URL)
    ancestors = dict.fromkeys([f"{site.scheme}://{site.netloc}", *app_frame_ancestor_sources()])
    return "; ".join(
        [
            # A stored document's meta policy must not widen the web preview's network access.
            "default-src 'none'",
            "script-src 'unsafe-inline' blob: https://cdn.jsdelivr.net/npm/@tailwindcss/ https://esm.sh",
            "style-src 'unsafe-inline' https://esm.sh",
            "font-src data: https://esm.sh",
            "img-src data: blob:",
            "worker-src blob:",
            "connect-src https://esm.sh https://cdn.jsdelivr.net/npm/@tailwindcss/",
            "form-action 'none'",
            "base-uri 'none'",
            "object-src 'none'",
            # The document runs in an opaque origin even when it opens top-level or in a frame
            # without the sandbox attribute.
            "sandbox allow-scripts",
            f"frame-ancestors {' '.join(ancestors)}",
        ]
    )


def create_canvas_sandbox_document_url() -> str | None:
    """The URL of the draft canvas sandbox document, or None when artifact delivery is off.

    The content hash in the path makes each URL immutable, so a deploy that changes the
    document changes the URL too.
    """
    if not _artifact_delivery_enabled(_artifact_signing_keys()):
        return None
    document = _sandbox_document()
    try:
        _publish_sandbox_document(document)
    except ObjectStorageError:
        return None
    return f"{_artifact_origin()}/canvas-artifacts/sandbox/{document.content_hash}/index.html"


@xframe_options_exempt
def canvas_sandbox_document(request: HttpRequest, content_hash: str) -> HttpResponse:
    """The bootstrap document that renders a draft canvas in a sandboxed iframe.

    The web app cannot use this document as srcdoc, because a srcdoc frame inherits the app's CSP,
    which refuses the CDNs the document transpiles and resolves imports from. It holds no
    credentials: the canvas code arrives later by postMessage.
    """
    _require_artifact_host(request.get_host())
    document = _sandbox_document()
    if not re.fullmatch(r"[0-9a-f]{64}", content_hash):
        raise Http404
    if content_hash != document.content_hash:
        content = object_storage.read_bytes(f"canvas_sandbox/{content_hash}/index.html", missing_ok=True)
        if content is None or hashlib.sha256(content).hexdigest() != content_hash:
            raise Http404
        document = _parse_sandbox_document(content)
    response = HttpResponse(document.content, content_type="text/html; charset=utf-8")
    response["ETag"] = f'"{document.content_hash}"'
    response["Cache-Control"] = "public, max-age=31536000, immutable"
    response["Referrer-Policy"] = "no-referrer"
    response["X-Content-Type-Options"] = "nosniff"
    response["Content-Security-Policy"] = _canvas_sandbox_document_csp()
    response["Permissions-Policy"] = ARTIFACT_PERMISSIONS_POLICY
    return response


@xframe_options_exempt
def canvas_artifact(request: HttpRequest, token: str, artifact_path: str) -> HttpResponse:
    _require_artifact_host(request.get_host())
    claims = _read_token(token)
    token_expires_at = (claims["bucket"] + 2) * ARTIFACT_TOKEN_BUCKET_SECONDS
    team_id = claims.get("team_id")
    if not isinstance(team_id, int) or isinstance(team_id, bool):
        raise Http404
    try:
        build_id = UUID(str(claims.get("build_id")))
        canvas_id = UUID(str(claims.get("canvas_id")))
    except (TypeError, ValueError):
        raise Http404 from None
    build = (
        CanvasBuild.objects.for_team(team_id)
        .filter(id=build_id, canvas_id=canvas_id, canvas__deleted=False, status=CanvasBuild.STATUS_READY)
        .first()
    )
    if build is None or not build.artifact_object_prefix or not isinstance(build.manifest, dict):
        raise Http404
    assets = build.manifest.get("assets")
    asset = (
        next((item for item in assets if isinstance(item, dict) and item.get("path") == artifact_path), None)
        if isinstance(assets, list)
        else None
    )
    if asset is None or not isinstance(asset.get("contentHash"), str):
        raise Http404

    # Artifacts are immutable and content-addressed, so the manifest hash is a
    # perfect validator: a revalidating client skips the object read entirely.
    etag = f'"{asset["contentHash"]}"'
    content_type = asset.get("contentType", "application/octet-stream")
    if not isinstance(content_type, str):
        content_type = "application/octet-stream"
    if request.headers.get("If-None-Match") == etag:
        response: HttpResponse = HttpResponseNotModified()
        response["Content-Type"] = content_type
        return _with_artifact_headers(response, etag, build.manifest, token_expires_at)

    try:
        content = object_storage.read_bytes(f"{build.artifact_object_prefix}/{artifact_path}")
    except object_storage.ObjectStorageError:
        raise Http404 from None
    if (
        content is None
        or len(content) != asset.get("sizeBytes")
        or hashlib.sha256(content).hexdigest() != asset["contentHash"]
    ):
        raise Http404
    response = HttpResponse(content, content_type=content_type)
    response["Content-Disposition"] = "inline"
    return _with_artifact_headers(response, etag, build.manifest, token_expires_at)


def _with_artifact_headers(response: HttpResponse, etag: str, manifest: dict, token_expires_at: int) -> HttpResponse:
    response["ETag"] = etag
    shared_cache_seconds = settings.CANVAS_ARTIFACT_SHARED_CACHE_SECONDS
    if shared_cache_seconds > 0:
        shared_cache_seconds = max(0, min(shared_cache_seconds, token_expires_at - math.ceil(time.time())))
        # CDN mode. Every header below still applies, and in particular the
        # CORS and CSP headers must survive the CDN unchanged, or the sandboxed
        # iframe's module fetches (and with them ph.query/ph.state canvases)
        # break. Configure the CDN to forward these headers as-is.
        response["Cache-Control"] = (
            f"public, max-age=31536000, s-maxage={shared_cache_seconds}, must-revalidate, immutable"
        )
    else:
        response["Cache-Control"] = "private, max-age=31536000, immutable"
    response["Cross-Origin-Resource-Policy"] = "cross-origin"
    # The canvas iframe is sandboxed without allow-same-origin, so its document
    # has an opaque origin and the entry's module scripts are fetched in CORS
    # mode — without this header the bundle is blocked and the canvas renders a
    # blank page. The signed token in the URL is the access credential; a
    # wildcard grants nothing beyond it and forbids credentialed requests by
    # definition.
    response["Access-Control-Allow-Origin"] = "*"
    response["Referrer-Policy"] = "no-referrer"
    response["X-Content-Type-Options"] = "nosniff"
    network_origins = ((manifest.get("capabilities") or {}).get("network") or {}).get("origins") or []
    response["Content-Security-Policy"] = artifact_csp(network_origins)
    response["Permissions-Policy"] = ARTIFACT_PERMISSIONS_POLICY
    return response
