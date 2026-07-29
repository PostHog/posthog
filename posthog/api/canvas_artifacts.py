import hmac
import hashlib
from typing import Any
from urllib.parse import urlparse
from uuid import UUID

from django.conf import settings
from django.core import signing
from django.http import Http404, HttpRequest, HttpResponse
from django.views.decorators.clickjacking import xframe_options_exempt

from posthog.models.file_system.canvas_build import CanvasBuild
from posthog.storage import object_storage

ARTIFACT_TOKEN_MAX_AGE_SECONDS = 3600
ARTIFACT_TOKEN_SALT = "posthog.canvas.artifact.v1"
ARTIFACT_CSP = (
    "default-src 'none'; base-uri 'none'; object-src 'none'; form-action 'none'; "
    "script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'none'; "
    "img-src 'self' data: blob:; font-src 'self' data:; media-src 'self' data: blob:; worker-src 'self' blob:"
)


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


def create_canvas_artifact_token(build: CanvasBuild) -> str | None:
    keys = settings.CANVAS_ARTIFACT_SIGNING_KEYS
    if not keys or (not settings.CANVAS_ARTIFACT_ORIGIN and not (settings.DEBUG or settings.TEST)):
        return None
    if not (settings.DEBUG or settings.TEST) and (len(keys[0]) < 32 or _configured_artifact_host() is None):
        return None
    return signing.TimestampSigner(key=keys[0], salt=ARTIFACT_TOKEN_SALT).sign_object(
        {"team_id": build.team_id, "canvas_id": str(build.canvas_id), "build_id": str(build.id)}, compress=True
    )


def create_canvas_artifact_url(build: CanvasBuild, artifact_path: str) -> str | None:
    token = create_canvas_artifact_token(build)
    if token is None:
        return None
    origin = settings.CANVAS_ARTIFACT_ORIGIN or settings.SITE_URL
    return f"{origin}/canvas-artifacts/{token}/{artifact_path}"


def _read_token(token: str) -> dict[str, Any]:
    for key in settings.CANVAS_ARTIFACT_SIGNING_KEYS:
        try:
            value = signing.TimestampSigner(key=key, salt=ARTIFACT_TOKEN_SALT).unsign_object(
                token, max_age=ARTIFACT_TOKEN_MAX_AGE_SECONDS
            )
            if isinstance(value, dict):
                return value
        except signing.BadSignature:
            continue
    raise Http404


@xframe_options_exempt
def canvas_artifact(request: HttpRequest, token: str, artifact_path: str) -> HttpResponse:
    if not (settings.DEBUG or settings.TEST):
        configured_host = _configured_artifact_host()
        if configured_host is None or request.get_host().lower() != configured_host:
            raise Http404
    claims = _read_token(token)
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
        .filter(id=build_id, canvas_id=canvas_id, status=CanvasBuild.STATUS_READY)
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
    if asset is None:
        raise Http404
    content = object_storage.read_bytes(f"{build.artifact_object_prefix}/{artifact_path}")
    if content is None:
        raise Http404
    expected_hash = asset.get("contentHash")
    if not isinstance(expected_hash, str) or not hmac.compare_digest(
        hashlib.sha256(content).hexdigest(), expected_hash
    ):
        raise Http404
    response = HttpResponse(content, content_type=asset.get("contentType", "application/octet-stream"))
    response["Cache-Control"] = "private, max-age=31536000, immutable"
    response["Content-Disposition"] = "inline"
    response["Cross-Origin-Resource-Policy"] = "cross-origin"
    response["Referrer-Policy"] = "no-referrer"
    response["X-Content-Type-Options"] = "nosniff"
    response["Content-Security-Policy"] = ARTIFACT_CSP
    response["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(), payment=(), usb=()"
    return response
