"""Forward arbitrary API requests to another PostHog project through a `posthog` connection.

A `posthog` integration (see `posthog.models.integration`) holds a user-consented, refreshable OAuth
grant against another PostHog project, in another region or your own. This viewset lets the connecting
user replay any request against that project's API — the server injects the stored token, so the
caller (a browser, an agent sandbox, an MCP tool) never holds it.

What the connection can do is bounded three ways: the scopes the user granted at consent, the target
cell's OAuthApplication.allowed_scopes, and the target's normal per-request permission checks. This
side only resolves the token and forwards; it does not re-implement or gate individual endpoints.
"""

import re
import json
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from time import monotonic
from typing import Any

from django.core.cache import cache

import requests
import structlog
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied, Throttled, ValidationError
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import BaseThrottle

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.auth import OAuthAccessTokenAuthentication, PersonalAPIKeyAuthentication, SessionAuthentication
from posthog.models.integration import POSTHOG_CONNECT_KIND, Integration, OauthIntegration, posthog_connect_base_url
from posthog.permissions import get_authenticator_scopes
from posthog.rate_limit import PostHogConnectionForwardThrottle

logger = structlog.get_logger(__name__)

CONNECTION_FORWARD_TIMEOUT_SECONDS = 30
# Each forward holds an API worker open while it round-trips to the target, so bound how many can be
# in flight per connection at once — the per-minute throttle only limits how fast they *start*, not
# how many run concurrently. Best-effort via the shared cache: the slot key carries a TTL so a worker
# that dies before releasing self-heals, and any cache error fails open so a limiter outage can't
# break a legitimate forward.
CONNECTION_MAX_INFLIGHT_PER_CONNECTION = 10
# Read at most this much of the target's response into memory. The proxy holds the whole body to
# re-serialize it, so cap it to keep an oversized upstream response from exhausting a worker.
CONNECTION_MAX_RESPONSE_BYTES = 5 * 1024 * 1024
# Header stamped on every forwarded request so the target (and this endpoint) can tell a request came
# through a connection — used here to refuse a forwarded request being forwarded again.
CONNECTION_MARKER_HEADER = "X-PostHog-Connection"
_METHODS_WITH_BODY = ("POST", "PUT", "PATCH", "DELETE")
_ALLOWED_METHODS = ("GET", *_METHODS_WITH_BODY)
# A relative API path on the target, e.g. `api/projects/2/insights/`. The host comes from the fixed
# per-region base URL (never from here), so the netloc can't be changed; this just keeps the path a
# well-formed relative path and blocks obvious traversal.
_SAFE_PATH = re.compile(r"^[A-Za-z0-9._~!$&'()*+,;=:@%/-]+$")
# How long the target's own identity (project id, org, region) is reused before being read again. It
# changes only when the user reconnects against a different project, so a stale window this short is
# invisible, while the cache removes a cross-region round trip from the front of every session.
CONNECTION_TARGET_CACHE_SECONDS = 300


@dataclass(frozen=True, kw_only=True)
class ForwardResult:
    """One forwarded request's outcome. `gateway_error` marks a failure raised on this side — target
    unreachable, too slow, response too large — as opposed to a status the target itself returned, so
    a caller can mirror it as the outer HTTP status instead of reporting a 200 that carries a 502."""

    status: int
    data: Any
    gateway_error: bool = False


def _connection_access_token(integration: Integration) -> str:
    oauth = OauthIntegration(integration)
    if oauth.access_token_expired():
        oauth.refresh_access_token()
        integration.refresh_from_db()
    token = integration.sensitive_config.get("access_token")
    if not token:
        raise ValidationError("This PostHog connection has no usable access token — reconnect it.")
    return token


def _enforce_caller_covers_connection_scopes(request: Request, integration: Integration) -> None:
    """A connection acts with the creator's stored grant, which may be broader than the API key making
    this call. Require that key to itself carry the scopes the connection was granted, so a narrowly
    scoped (or leaked) key can't wield the connection to exceed its own authority. Session auth and
    full-access (`*`) keys already carry the user's full authority, so they pass."""
    caller_scopes = get_authenticator_scopes(getattr(request, "successful_authenticator", None))
    if caller_scopes is None or "*" in caller_scopes:
        return
    granted = set(integration.config.get("granted_scopes") or [])
    if not granted:
        # We don't know what this connection can do — `granted_scopes` is only ever populated from the
        # target's token-response `scope`, which is OPTIONAL per RFC 6749 §5.1. If the target omitted
        # it, fail closed: a scoped (or leaked) key must not wield a grant whose reach we can't bound.
        raise PermissionDenied(
            "This PostHog connection's granted scopes are unknown, so it can only be used with a "
            "full-access API key or a session. Reconnect it to record its scopes."
        )
    missing = granted - set(caller_scopes)
    if missing:
        raise PermissionDenied(
            "Your API key must carry the scopes this connection was granted to use it. "
            f"Missing: {', '.join(sorted(missing))}."
        )


def _validate_target_path(path: str) -> str:
    raw = path or ""
    stripped = raw.lstrip("/")
    # Reject a leading `//` (protocol-relative-looking) even though the fixed base URL already fixes
    # the host — it's never a legitimate API path, so refuse it rather than silently normalizing.
    if not stripped or raw.startswith("//") or "://" in stripped or ".." in stripped or not _SAFE_PATH.match(stripped):
        raise ValidationError("path must be a relative target API path, e.g. `api/projects/2/insights/`.")
    return stripped


@contextmanager
def _inflight_slot(integration_id: int) -> Iterator[bool]:
    """Bound concurrent forwards per connection, yielding whether a slot was acquired. Fails open on
    any cache error so the limiter can never take the feature down; the slot key's TTL reclaims a
    slot whose holder died before release."""
    key = f"posthog_connection_inflight:{integration_id}"
    # Keep the lease alive for the whole forward: the read is bounded by a wall-clock deadline of
    # CONNECTION_FORWARD_TIMEOUT_SECONDS, plus up to one more socket-timeout window for the final
    # blocking read, so a slot could legitimately be held for ~2x the timeout. TTL past that (rather
    # than expiring mid-forward) is what makes the concurrency cap actually hold.
    try:
        cache.add(key, 0, timeout=2 * CONNECTION_FORWARD_TIMEOUT_SECONDS + 5)
        current = cache.incr(key)
    except Exception:
        yield True
        return
    try:
        yield current <= CONNECTION_MAX_INFLIGHT_PER_CONNECTION
    finally:
        try:
            cache.decr(key)
        except Exception:
            pass


def _forward_through_connection(
    integration: Integration,
    method: str,
    path: str,
    *,
    query: dict[str, Any] | None = None,
    data: Any = None,
) -> ForwardResult:
    """Replay one request against the connected project, injecting the connection's token."""
    token = _connection_access_token(integration)
    base = posthog_connect_base_url(integration.config.get("region"))

    raw = bytearray()
    timed_out = False
    try:
        with _inflight_slot(integration.id) as acquired:
            if not acquired:
                raise Throttled(detail="Too many concurrent requests through this PostHog connection.")
            res = requests.request(
                method,
                f"{base}/{path}",
                params=query or None,
                json=data if method in _METHODS_WITH_BODY else None,
                headers={"Authorization": f"Bearer {token}", CONNECTION_MARKER_HEADER: "1"},
                timeout=CONNECTION_FORWARD_TIMEOUT_SECONDS,
                # A compromised/misconfigured target must not be able to 30x us into resending the
                # bearer token to another origin.
                allow_redirects=False,
                # Stream so an oversized body is capped below rather than fully buffered by requests.
                stream=True,
            )
            with res:
                # Bound the *total* time we hold a worker, not just each socket read. A target that
                # trickles a long-lived stream (SSE keepalives, say) would otherwise keep this read
                # alive past the in-flight lease below and defeat the concurrency cap. Stop at the
                # size cap or the wall-clock deadline, whichever comes first.
                deadline = monotonic() + CONNECTION_FORWARD_TIMEOUT_SECONDS
                for chunk in res.iter_content(chunk_size=65536):
                    raw += chunk
                    if len(raw) > CONNECTION_MAX_RESPONSE_BYTES:
                        break
                    if monotonic() > deadline:
                        timed_out = True
                        break
    except requests.RequestException as err:
        logger.warning(
            "posthog_connection_forward_unreachable",
            integration_id=integration.id,
            region=integration.config.get("region"),
            error=str(err),
        )
        return ForwardResult(
            status=status.HTTP_502_BAD_GATEWAY,
            data={"error": "The target project could not be reached."},
            gateway_error=True,
        )

    if timed_out:
        return ForwardResult(
            status=status.HTTP_504_GATEWAY_TIMEOUT,
            data={"error": "The target project took too long to respond."},
            gateway_error=True,
        )

    if len(raw) > CONNECTION_MAX_RESPONSE_BYTES:
        return ForwardResult(
            status=status.HTTP_502_BAD_GATEWAY,
            data={"error": "The target project's response was too large."},
            gateway_error=True,
        )

    try:
        body = json.loads(raw) if raw else None
    except ValueError:
        body = None
    # Pass the target's status and body straight through. The target owns the residency policy for
    # what its responses contain, so no scrub happens on this side.
    return ForwardResult(status=res.status_code, data=body)


class PostHogConnectionForwardSerializer(serializers.Serializer):
    method = serializers.ChoiceField(
        choices=list(_ALLOWED_METHODS), help_text="HTTP method to use against the target project's API."
    )
    path = serializers.CharField(
        help_text="Relative target API path with no host or scheme, e.g. `api/projects/2/insights/`."
    )
    query = serializers.DictField(
        required=False, child=serializers.CharField(), help_text="Query parameters to send to the target."
    )
    # `data` shadows Serializer.data (a property); the field is part of the API contract, so keep the
    # name and silence the resulting attribute-type mismatch.
    data = serializers.JSONField(required=False, help_text="JSON request body for write methods.")  # type: ignore[assignment]


class PostHogConnectionForwardResponseSerializer(serializers.Serializer):
    status = serializers.IntegerField(help_text="HTTP status the target project returned.")
    data = serializers.JSONField(help_text="The target project's response body, passed through.")  # type: ignore[assignment]


class PostHogConnectionTargetSerializer(serializers.Serializer):
    project_id = serializers.IntegerField(
        help_text="Project id to use in target API paths. It is the connected project's id, not this one's."
    )
    project_name = serializers.CharField(help_text="Name of the connected project.")
    organization_id = serializers.CharField(help_text="Id of the organization the connected project belongs to.")
    organization_name = serializers.CharField(help_text="Name of the organization the connected project belongs to.")
    region = serializers.CharField(help_text="Cloud region the connected project lives in, e.g. `US` or `EU`.")
    base_url = serializers.CharField(help_text="Base URL requests through this connection are sent to.")


class PostHogConnectionTargetErrorSerializer(serializers.Serializer):
    error = serializers.CharField(help_text="Why the connected project's context could not be read.")


# A `posthog` connection is an integration kind, so route its codegen (frontend types, MCP tools)
# to the integrations product rather than the core bucket this module's path would otherwise imply.
@extend_schema(extensions={"x-product": "integrations"})
class PostHogConnectionViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    """Replay requests against another PostHog project via a `posthog` connection you created."""

    authentication_classes = [SessionAuthentication, PersonalAPIKeyAuthentication, OAuthAccessTokenAuthentication]
    scope_object = "integration"
    serializer_class = PostHogConnectionForwardSerializer

    def get_throttles(self) -> list[BaseThrottle]:
        if self.action in ("forward", "target"):
            return [PostHogConnectionForwardThrottle(), *super().get_throttles()]
        return super().get_throttles()

    def _authorized_connection(self, request: Request, pk: str | None) -> Integration:
        # Refuse to forward a request that itself arrived through a connection, so a same-region (or
        # cross-region) connection can't be chained into itself and tie up workers one hop at a time.
        if request.headers.get(CONNECTION_MARKER_HEADER):
            raise ValidationError("A request forwarded through a PostHog connection cannot be forwarded again.")
        integration = self._get_connection(pk)
        _enforce_caller_covers_connection_scopes(request, integration)
        return integration

    def _get_connection(self, pk: str | None) -> Integration:
        if pk is None:
            raise NotFound("No PostHog connection with that id in this project.")
        try:
            integration = Integration.objects.get(team_id=self.team_id, id=pk, kind=POSTHOG_CONNECT_KIND)
        except (Integration.DoesNotExist, ValueError, ValidationError):
            raise NotFound("No PostHog connection with that id in this project.")
        # A connection acts as the user who consented to it. Restrict use to that user so a broad,
        # any-scope grant can't become a team-wide confused deputy in the target project.
        if integration.created_by_id != getattr(self.request.user, "id", None):
            raise PermissionDenied("You can only use a PostHog connection you created.")
        return integration

    @extend_schema(
        request=PostHogConnectionForwardSerializer,
        responses={200: OpenApiResponse(response=PostHogConnectionForwardResponseSerializer)},
        summary="Forward a request through a PostHog connection",
        description="Replay an API request against the connected PostHog project. The server injects the connection's token; the response is passed through.",
    )
    @action(detail=True, methods=["post"], url_path="forward", required_scopes=["integration:write"])
    def forward(self, request: Request, pk: str | None = None, **kwargs: Any) -> Response:
        integration = self._authorized_connection(request, pk)

        serializer = PostHogConnectionForwardSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payload = serializer.validated_data

        result = _forward_through_connection(
            integration,
            payload["method"],
            _validate_target_path(payload["path"]),
            query=payload.get("query"),
            data=payload.get("data"),
        )
        body = {"status": result.status, "data": result.data}
        # A failure on this side is mirrored as the outer status too, so a caller that only reads the
        # HTTP status still sees it. A status the target itself returned rides inside a 200.
        return Response(body, status=result.status if result.gateway_error else status.HTTP_200_OK)

    @extend_schema(
        responses={
            200: OpenApiResponse(response=PostHogConnectionTargetSerializer),
            502: OpenApiResponse(response=PostHogConnectionTargetErrorSerializer),
        },
        summary="Read the connected project's identity",
        description="Resolve which project, organization and region a PostHog connection points at, so callers can build target API paths without reading `api/users/@me/` through the connection first.",
    )
    @action(detail=True, methods=["get"], url_path="target", required_scopes=["integration:read"])
    def target(self, request: Request, pk: str | None = None, **kwargs: Any) -> Response:
        integration = self._authorized_connection(request, pk)

        cache_key = f"posthog_connection_target:{integration.id}"
        try:
            cached = cache.get(cache_key)
        except Exception:
            cached = None
        if cached:
            return Response(cached)

        result = _forward_through_connection(integration, "GET", "api/users/@me/")
        me = result.data if isinstance(result.data, dict) else {}
        team = me.get("team") or {}
        organization = me.get("organization") or {}
        if result.status != status.HTTP_200_OK or not team.get("id"):
            return Response(
                {"error": "The connected project's identity could not be read. Reconnect the connection."},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        payload = {
            "project_id": team["id"],
            "project_name": team.get("name") or "",
            "organization_id": str(organization.get("id") or ""),
            "organization_name": organization.get("name") or "",
            "region": (integration.config.get("region") or "").upper(),
            "base_url": posthog_connect_base_url(integration.config.get("region")),
        }
        try:
            cache.set(cache_key, payload, timeout=CONNECTION_TARGET_CACHE_SECONDS)
        except Exception:
            pass
        return Response(payload)
