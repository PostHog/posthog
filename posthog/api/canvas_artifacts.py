from __future__ import annotations

from typing import Any
from urllib.parse import urlparse
from uuid import UUID

from django.conf import settings
from django.core import signing
from django.http import Http404, HttpRequest, HttpResponse
from django.views.decorators.clickjacking import xframe_options_exempt

from posthog.models.file_system.canvas import CanvasBuild
from posthog.storage import object_storage

ARTIFACT_TOKEN_MAX_AGE_SECONDS = 300
ARTIFACT_TOKEN_SALT = "posthog.canvas.artifact.v1"


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
    if not settings.CANVAS_ARTIFACT_SIGNING_KEYS or (
        not settings.CANVAS_ARTIFACT_ORIGIN and not (settings.DEBUG or settings.TEST)
    ):
        return None
    if not (settings.DEBUG or settings.TEST) and len(settings.CANVAS_ARTIFACT_SIGNING_KEYS[0]) < 32:
        return None
    if not (settings.DEBUG or settings.TEST) and _configured_artifact_host() is None:
        return None
    signer = signing.TimestampSigner(key=settings.CANVAS_ARTIFACT_SIGNING_KEYS[0], salt=ARTIFACT_TOKEN_SALT)
    return signer.sign_object(
        {"team_id": build.team_id, "canvas_id": str(build.canvas_id), "build_id": str(build.id)},
        compress=True,
    )


def _read_token(token: str) -> dict[str, Any]:
    for key in settings.CANVAS_ARTIFACT_SIGNING_KEYS:
        if not (settings.DEBUG or settings.TEST) and len(key) < 32:
            continue
        try:
            value = signing.TimestampSigner(key=key, salt=ARTIFACT_TOKEN_SALT).unsign_object(
                token,
                max_age=ARTIFACT_TOKEN_MAX_AGE_SECONDS,
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
        .filter(
            id=build_id,
            canvas_id=canvas_id,
            build_status=CanvasBuild.Status.READY,
        )
        .first()
    )
    if build is None or not build.artifact_object_prefix or not isinstance(build.manifest, dict):
        raise Http404
    files = build.manifest.get("files")
    file_manifest = (
        next(
            (entry for entry in files if isinstance(entry, dict) and entry.get("path") == artifact_path),
            None,
        )
        if isinstance(files, list)
        else None
    )
    if file_manifest is None:
        raise Http404
    content = object_storage.read_bytes(f"{build.artifact_object_prefix}/{artifact_path}")
    if content is None:
        raise Http404
    response = HttpResponse(content, content_type=file_manifest.get("contentType", "application/octet-stream"))
    response["Cache-Control"] = "private, max-age=31536000, immutable"
    response["Content-Disposition"] = "inline"
    response["Cross-Origin-Resource-Policy"] = "cross-origin"
    response["Referrer-Policy"] = "no-referrer"
    response["X-Content-Type-Options"] = "nosniff"
    return response
