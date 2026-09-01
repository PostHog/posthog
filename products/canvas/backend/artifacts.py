"""The canvas artifact origin: serves built canvas files to sandboxed iframes.

Artifacts are untrusted user content, so they are served from a dedicated
origin (``CANVAS_ARTIFACT_ORIGIN``) that fails closed: in production the view
refuses to answer on any other Host, keeping user code off the application
origin. Access is capability-based: a signed token minted for the
authenticated user is the only credential, so the artifact origin itself
holds no cookies or sessions. Every request re-authorizes against the live
build row and the minting user's current team access, so deleting the canvas
or its build, or revoking that user's access, cuts off outstanding URLs.

Integrity is verified when artifacts are written and again when they are read
from object storage. The manifest hash is also used as the response ETag.
"""

import time
import hashlib
from typing import Any
from urllib.parse import urlparse
from uuid import UUID

from django.conf import settings
from django.core import signing
from django.http import Http404, HttpRequest, HttpResponse, HttpResponseNotModified
from django.views.decorators.clickjacking import xframe_options_exempt

from posthog.models import OrganizationMembership, Team, User
from posthog.storage import object_storage

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.canvas.backend.contract import artifact_csp
from products.canvas.backend.models import CanvasBuild

ARTIFACT_TOKEN_SALT = "posthog.canvas.artifact.v1"
# Minted tokens carry no expiry claim, because the URL for a build must stay
# byte-stable: the assets are served with `max-age=31536000, immutable`, and the
# browser HTTP cache is keyed by URL, so any time component in the token forces
# a full re-download of the artifact (up to the 12 MB size cap) every time it
# rolls over. Because they never expire, stable tokens are bound to the user
# they were minted for, and every request re-checks the build row and that
# user's team access, so a leaked URL outlives neither the build nor its
# holder's access. A token carrying a `bucket` claim is still honored for its
# original window (its own bucket and the next one, i.e. between one and two
# hours) without a user binding, so URLs held by open clients keep working.
ARTIFACT_TOKEN_BUCKET_SECONDS = 3600


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


def create_canvas_artifact_token(build: CanvasBuild, user: User) -> str | None:
    keys = settings.CANVAS_ARTIFACT_SIGNING_KEYS
    if not keys or (not settings.CANVAS_ARTIFACT_ORIGIN and not (settings.DEBUG or settings.TEST)):
        return None
    if not (settings.DEBUG or settings.TEST) and (len(keys[0]) < 32 or _configured_artifact_host() is None):
        return None
    return signing.Signer(key=keys[0], salt=ARTIFACT_TOKEN_SALT).sign_object(
        {
            "team_id": build.team_id,
            "canvas_id": str(build.canvas_id),
            "build_id": str(build.id),
            "user_id": user.id,
        },
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


def create_canvas_artifact_url(build: CanvasBuild, artifact_path: str, user: User) -> str | None:
    token = create_canvas_artifact_token(build, user)
    if token is None:
        return None
    return f"{_artifact_origin()}/canvas-artifacts/{token}/{artifact_path}"


def _minting_user_retains_access(user_id: int, team: Team) -> bool:
    """Whether the user a stable token was minted for can still access the team.

    Stable tokens never expire, so this per-request check is what revokes a
    leaked URL: deactivating the user or removing them from the organization
    cuts off every artifact URL minted for them.
    """
    user = User.objects.filter(id=user_id, is_active=True).first()
    if user is None:
        return False
    if not OrganizationMembership.objects.filter(organization_id=team.organization_id, user_id=user_id).exists():
        return False
    # Project RBAC can revoke project access without touching org membership.
    # check_access_level_for_object default-allows admins/creators/no-AC-feature
    # orgs, so this only fails closed on an explicit revocation.
    return UserAccessControl(user=user, team=team).check_access_level_for_object(team, required_level="member")


def _read_token(token: str) -> dict[str, Any]:
    for key in settings.CANVAS_ARTIFACT_SIGNING_KEYS:
        try:
            value = signing.Signer(key=key, salt=ARTIFACT_TOKEN_SALT).unsign_object(token)
        except signing.BadSignature:
            continue
        if not isinstance(value, dict):
            continue
        if "bucket" not in value:
            return value
        current_bucket = int(time.time() // ARTIFACT_TOKEN_BUCKET_SECONDS)
        if value["bucket"] in (current_bucket, current_bucket - 1):
            return value
    raise Http404


@xframe_options_exempt
def canvas_artifact(request: HttpRequest, token: str, artifact_path: str) -> HttpResponse:
    configured_host = _configured_artifact_host()
    if settings.CANVAS_ARTIFACT_ORIGIN and (configured_host is None or request.get_host().lower() != configured_host):
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
        .filter(id=build_id, canvas_id=canvas_id, canvas__deleted=False, status=CanvasBuild.STATUS_READY)
        .select_related("team")
        .first()
    )
    if build is None or not build.artifact_object_prefix or not isinstance(build.manifest, dict):
        raise Http404
    # A stable (bucket-less) token is a credential with no expiry, so it must
    # name the user it was minted for and that user must still have access.
    # Bucketed tokens are exempt: they carry no user binding, and their own
    # window already bounds them to at most two hours.
    if "bucket" not in claims:
        user_id = claims.get("user_id")
        if not isinstance(user_id, int) or isinstance(user_id, bool):
            raise Http404
        if not _minting_user_retains_access(user_id, build.team):
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
        return _with_artifact_headers(response, etag, build.manifest)

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
    return _with_artifact_headers(response, etag, build.manifest)


def _with_artifact_headers(response: HttpResponse, etag: str, manifest: dict) -> HttpResponse:
    response["ETag"] = etag
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
    response["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(), payment=(), usb=()"
    return response
