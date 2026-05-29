"""
DRF viewsets for agent_stack — the authoring surface.

Two model viewsets + one catalog viewset:

    AgentApplicationViewSet  list / retrieve / create / update / destroy /
                             set_env
    AgentRevisionViewSet     list / retrieve / create (draft) / update_spec /
                             promote / archive  +  bundle proxy actions
                             (manifest, file, bundle, freeze, clone_from)
    AgentNativeToolsViewSet  list (read-only catalog of native tools)

Bundle reads/writes are proxied to the agent-janitor node service which
owns the actual BundleStore (FS in dev, S3 in prod). The Django layer keeps
its team / scope / draft-only checks and forwards the body. See
janitor_client.py for the wire protocol.
"""

from __future__ import annotations

import os
import json
import logging
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from functools import cached_property
from typing import Any
from urllib.parse import urlencode
from uuid import UUID

from django.db.models import QuerySet
from django.http import StreamingHttpResponse
from django.utils import timezone

import jwt as pyjwt
import requests
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import (
    OpenApiParameter,
    OpenApiResponse,
    PolymorphicProxySerializer,
    extend_schema,
    extend_schema_field,
    inline_serializer,
)
from rest_framework import (
    renderers,
    serializers as drf_serializers,
    status,
    viewsets,
)
from rest_framework.decorators import action
from rest_framework.exceptions import APIException, NotFound, ValidationError
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.settings import api_settings

from posthog.schema import ProductKey

from posthog.api.log_entries import LogEntryRequestSerializer, LogEntrySerializer, fetch_log_entries
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.clickhouse.query_tagging import Feature, tag_queries
from posthog.helpers.encrypted_fields import EncryptedTextField
from posthog.jwt import PosthogJwtAudience
from posthog.models.organization import OrganizationMembership

from .janitor_client import JanitorClient, JanitorClientError, default_client
from .models import AgentApplication, AgentRevision
from .serializers import (
    AgentApplicationSerializer,
    AgentRevisionSerializer,
    CloneFromRequestSerializer,
    DecideApprovalRequestSerializer,
    NewDraftRevisionRequestSerializer,
    PromoteRevisionRequestSerializer,
    SetEnvRequestSerializer,
    WriteBundleRequestSerializer,
    WriteFileRequestSerializer,
)

logger = logging.getLogger(__name__)


def _resolve_application(queryset: QuerySet, lookup_value: str) -> AgentApplication | None:
    """Look up by UUID if the URL value parses as one, otherwise by slug.

    Lets API consumers reference an application either by its stable id or by
    the human-readable slug — both are unique within a team.
    """
    try:
        UUID(str(lookup_value))
        field = "pk"
    except (ValueError, TypeError):
        field = "slug"
    return queryset.filter(**{field: lookup_value}).first()


def _janitor() -> JanitorClient:
    """Indirection so tests can monkey-patch."""
    return default_client()


class JanitorUpstreamError(APIException):
    """DRF-friendly wrapper for non-2xx janitor responses. We forward the
    status code where it makes sense (404 stays 404, 409 stays 409) and
    surface the janitor's body as the API response."""

    status_code = status.HTTP_502_BAD_GATEWAY
    default_detail = "Upstream janitor service error"
    default_code = "janitor_upstream"

    def __init__(self, e: JanitorClientError) -> None:
        # Preserve 4xx mappings; clamp 5xx to a single 502 so we never leak
        # the janitor's internal status (some are nominal like 503 = not
        # configured, but the caller experience is "this isn't available").
        upstream_code = e.status_code
        if 400 <= upstream_code < 500:
            self.status_code = upstream_code
        detail = e.body if e.body is not None else {"detail": e.message}
        super().__init__(detail=detail)


# The `log_source` tag the agent runner stamps on every log_entries row.
# Mirrors `AGENT_SESSION_LOG_SOURCE` in services/agent-shared/src/runtime/
# log-sink.ts — keep both sides in sync.
AGENT_SESSION_LOG_SOURCE = "agent_session"


def _mint_preview_jwt(application: AgentApplication, revision: AgentRevision, user: Any) -> tuple[str, int] | None:
    """Mint a short-lived HS256 JWT scoped to (app, rev) for non-live invokes.

    Returns `(token, ttl_seconds)` or `None` when no shared secret is
    configured (dev / harness path — ingress's gate is then also bypassed).

    Same payload + secret the runtime uses; pulled out of preview_proxy so
    the standalone `preview_token` action and the legacy server-side proxy
    share one implementation. Bound to (app, rev) so a captured token can't
    be replayed against a different draft. See docs/agent-platform/plans/
    draft-preview-auth.md.
    """
    preview_secret = os.environ.get("AGENT_PREVIEW_SECRET", "")
    if not preview_secret:
        return None
    ttl_seconds = 60
    payload: dict[str, Any] = {
        "app": str(application.id),
        "rev": str(revision.id),
        "aud": PosthogJwtAudience.AGENT_PREVIEW.value,
        "exp": datetime.now(tz=UTC) + timedelta(seconds=ttl_seconds),
    }
    if user and getattr(user, "is_authenticated", False):
        payload["sub"] = f"user:{user.id}"
    return pyjwt.encode(payload, preview_secret, algorithm="HS256"), ttl_seconds


class EventStreamRenderer(renderers.BaseRenderer):
    """Lets DRF's content negotiation accept `Accept: text/event-stream`
    requests (browser EventSource sends this) so they reach the view
    instead of 406-ing in the negotiator. The streaming view returns
    `StreamingHttpResponse` directly so this renderer's `render()` is
    never actually invoked — its job is just to claim the media type."""

    media_type = "text/event-stream"
    format = "sse"
    charset = "utf-8"

    def render(self, data: Any, accepted_media_type: str | None = None, renderer_context: Any = None) -> bytes:
        # StreamingHttpResponse path bypasses this, but if a non-streaming
        # response ever lands here (e.g. an error), keep it valid SSE.
        return str(data).encode(self.charset or "utf-8")


# ── Conversation message variants ────────────────────────────────────
# Module-level so `@extend_schema_field` can reference them. Mirrors
# `ConversationMessage` (UserMessage | AssistantMessageRecord |
# ToolResultMessage) in services/agent-shared/src/spec/spec.ts. Each
# variant becomes its own named component in the generated TS; the
# parent `_AgentConversationMessageField` ties them into a discriminated
# union on `role`.

_AGENT_USER_MESSAGE = inline_serializer(
    name="AgentConversationUserMessage",
    fields={
        "role": drf_serializers.ChoiceField(choices=["user"]),
        # Wire is `string | (TextContent|ImageContent)[]`. DRF can't
        # express that as a single field — surface it as JSONField so
        # the generated TS gets `unknown`; consumers narrow on read.
        "content": drf_serializers.JSONField(
            help_text="String shorthand, or array of {type:'text'|'image', ...} parts.",
        ),
        "timestamp": drf_serializers.IntegerField(help_text="Epoch milliseconds."),
    },
)
_AGENT_ASSISTANT_MESSAGE = inline_serializer(
    name="AgentConversationAssistantMessage",
    fields={
        "role": drf_serializers.ChoiceField(choices=["assistant"]),
        "content": drf_serializers.ListField(
            child=drf_serializers.JSONField(),
            help_text="Array of text/thinking/toolCall parts.",
        ),
        "timestamp": drf_serializers.IntegerField(help_text="Epoch milliseconds."),
        "api": drf_serializers.CharField(required=False),
        "provider": drf_serializers.CharField(required=False),
        "model": drf_serializers.CharField(required=False),
        "usage": drf_serializers.DictField(child=drf_serializers.JSONField(), required=False),
        "stopReason": drf_serializers.ChoiceField(
            choices=["stop", "length", "toolUse", "error", "aborted"],
            required=False,
        ),
        "errorMessage": drf_serializers.CharField(required=False),
    },
)
_AGENT_TOOL_RESULT_MESSAGE = inline_serializer(
    name="AgentConversationToolResultMessage",
    fields={
        "role": drf_serializers.ChoiceField(choices=["toolResult"]),
        "toolCallId": drf_serializers.CharField(),
        "toolName": drf_serializers.CharField(),
        "content": drf_serializers.ListField(
            child=drf_serializers.JSONField(),
            help_text="Array of {type:'text'|'image', ...} parts.",
        ),
        "isError": drf_serializers.BooleanField(),
        "timestamp": drf_serializers.IntegerField(help_text="Epoch milliseconds."),
    },
)


@extend_schema_field(
    PolymorphicProxySerializer(
        component_name="AgentConversationMessage",
        resource_type_field_name="role",
        serializers={
            "user": _AGENT_USER_MESSAGE,
            "assistant": _AGENT_ASSISTANT_MESSAGE,
            "toolResult": _AGENT_TOOL_RESULT_MESSAGE,
        },
    )
)
class _AgentConversationMessageField(drf_serializers.JSONField):
    """JSONField whose OpenAPI schema is the discriminated union of the
    three conversation-message variants. Runtime validation is JSONField's
    default (any JSON); the typing only shapes the generated TS so the
    frontend's `conversationToTurns` mapper gets a real narrowing on `role`."""

    pass


# Mirrors `SessionUsageTotal` in services/agent-shared/src/spec/spec.ts.
# When that widens, widen this — MCP + frontend codegen pulls from here.
_AGENT_SESSION_USAGE_TOTAL = inline_serializer(
    name="AgentSessionUsageTotal",
    fields={
        "tokens_in": drf_serializers.IntegerField(),
        "tokens_out": drf_serializers.IntegerField(),
        "cache_read": drf_serializers.IntegerField(),
        "cache_write": drf_serializers.IntegerField(),
        "cost_input": drf_serializers.FloatField(),
        "cost_output": drf_serializers.FloatField(),
        "cost_cache_read": drf_serializers.FloatField(),
        "cost_cache_write": drf_serializers.FloatField(),
        "cost_total": drf_serializers.FloatField(),
    },
)

# Principal kinds the runner stamps onto a session. Mirrors
# `SessionPrincipal` in services/agent-shared/src/spec/spec.ts.
_AGENT_SESSION_PRINCIPAL_KINDS = ["anonymous", "service", "internal", "shared_secret", "slack"]

_AGENT_SESSION_PRINCIPAL = inline_serializer(
    name="AgentSessionPrincipal",
    fields={
        "kind": drf_serializers.ChoiceField(
            choices=_AGENT_SESSION_PRINCIPAL_KINDS,
            help_text="What kind of principal authenticated the session start.",
        ),
        "id": drf_serializers.CharField(
            required=False,
            help_text="Stable identifier for the principal (PAT id, slack user id, etc). Absent for anonymous sessions.",
        ),
        "team_id": drf_serializers.IntegerField(
            required=False,
            help_text="Team the principal belongs to. Absent for anonymous sessions.",
        ),
    },
    allow_null=True,
)

# Runtime `AgentSession.state` enum. Mirrors agent-shared spec.ts.
_AGENT_SESSION_STATE_VALUES = ["queued", "running", "completed", "closed", "cancelled", "failed"]

# Roll-up shape returned by the janitor's `/sessions/stats` and `/fleet/stats`
# endpoints. Used both by the per-application action and the fleet viewset.
_AGENT_AGGREGATE_STATS = inline_serializer(
    name="AgentAggregateStats",
    fields={
        "liveCount": drf_serializers.IntegerField(
            help_text="Sessions currently in a live state (queued / running).",
        ),
        "sessionsInWindowCount": drf_serializers.IntegerField(
            help_text="Sessions created within the `since` window across all states.",
        ),
        "spendInWindowUsd": drf_serializers.FloatField(
            help_text="Sum of `usage_total.cost_total` across sessions in the window.",
        ),
        "lastActivityAt": drf_serializers.DateTimeField(
            allow_null=True,
            help_text="ISO timestamp of the most recent session update — null when there are no sessions.",
        ),
        "failedInWindowCount": drf_serializers.IntegerField(
            help_text="Sessions in `failed` state created within the window.",
        ),
    },
)


@extend_schema(tags=["agent_stack"])
class AgentApplicationViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    """Agent applications — the deployable unit of the platform.

    URLs:
        GET    /api/projects/<team>/agent_applications/             list
        POST   /api/projects/<team>/agent_applications/             create
        GET    /api/projects/<team>/agent_applications/<id|slug>/   retrieve
        PATCH  /api/projects/<team>/agent_applications/<id|slug>/   update
        DELETE /api/projects/<team>/agent_applications/<id|slug>/   archive
        POST   /api/projects/<team>/agent_applications/<id|slug>/set_env/   set env
    """

    scope_object = "agent_application"
    scope_object_write_actions = [
        "create",
        "update",
        "partial_update",
        "destroy",
        "set_env",
        "approvals_decide",
    ]
    scope_object_read_actions = [
        "list",
        "retrieve",
        "sessions_list",
        "sessions_retrieve",
        "session_logs",
        "stats",
        # POST → `preview_proxy`, GET (SSE `listen`) → `preview_proxy_get`.
        # DRF uses the bound function name as `view.action`, so the GET
        # variant is its own entry in the scope-check map.
        "preview_proxy",
        "preview_proxy_get",
        "preview_token",
        "approvals_list",
        "approvals_retrieve",
    ]
    serializer_class = AgentApplicationSerializer
    queryset = AgentApplication.objects.all()

    def safely_get_queryset(self, queryset: QuerySet) -> QuerySet:
        return queryset.filter(archived=False)

    def safely_get_object(self, queryset: QuerySet) -> AgentApplication | None:
        return _resolve_application(queryset, self.kwargs[self.lookup_url_kwarg or self.lookup_field])

    def perform_create(self, serializer: AgentApplicationSerializer) -> None:
        serializer.save(team_id=self.team_id, created_by=self.request.user)

    def perform_destroy(self, instance: AgentApplication) -> None:
        """Soft-delete: archived=True, archived_at=NOW. Preserves audit history."""
        instance.archived = True
        instance.archived_at = timezone.now()
        instance.save(update_fields=["archived", "archived_at", "updated_at"])

    @extend_schema(request=SetEnvRequestSerializer)
    @action(detail=True, methods=["post"], url_path="set_env")
    def set_env(self, request: Request, **kwargs) -> Response:
        """Replace the agent's encrypted env block.

        The body is `{ "env": { "<KEY>": "<value>", ... } }`. The encrypted
        text gets stored on AgentApplication.encrypted_env; the worker
        decrypts it at session start via the same Fernet schedule (see
        agent-shared/src/runtime/encryption.ts).
        """
        application = self.get_object()
        if application is None:
            raise NotFound("Application not found")

        body = SetEnvRequestSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        env_map = body.validated_data["env"]

        # EncryptedTextField encrypts on assignment when saved.
        # We serialize the env dict as JSON before encryption so the worker
        # gets a JSON object back out.
        application.encrypted_env = json.dumps(env_map)
        application.save(update_fields=["encrypted_env", "updated_at"])
        return Response({"ok": True})

    # Ingress trigger paths the preview-proxy is allowed to forward to. Keeping
    # this an allowlist (vs an arbitrary passthrough) gives us a single place
    # to audit what's reachable through the authoring-side trust boundary.
    # `webhook/<path>` and `slack/events` aren't included — those triggers
    # need stable public URLs and don't fit a Django-mediated preview.
    _PREVIEW_PROXY_ALLOWED_PATHS = frozenset({"run", "send", "cancel", "listen"})

    _PREVIEW_PROXY_PARAMETERS = [
        OpenApiParameter(
            "rest",
            OpenApiTypes.STR,
            OpenApiParameter.PATH,
            required=True,
            description="Ingress sub-path under the agent slug. One of: `run`, `send`, `cancel`, `listen`.",
        ),
        OpenApiParameter(
            "revision_id",
            OpenApiTypes.UUID,
            OpenApiParameter.QUERY,
            required=True,
            description="Target draft revision. Must belong to this application and not be live.",
        ),
    ]

    @extend_schema(
        operation_id="agent_applications_preview_proxy",
        parameters=_PREVIEW_PROXY_PARAMETERS,
        request=None,
    )
    @action(
        detail=True,
        methods=["post"],
        url_path=r"preview-proxy/(?P<rest>[^/]+)",
        # Include EventStreamRenderer so browser EventSource (Accept:
        # text/event-stream) gets past DRF content negotiation and into
        # the streaming view. The GET counterpart (`preview_proxy_get`)
        # inherits this via `@preview_proxy.mapping.get`.
        renderer_classes=[*api_settings.DEFAULT_RENDERER_CLASSES, EventStreamRenderer],
    )
    def preview_proxy(self, request: Request, rest: str = "", **kwargs) -> StreamingHttpResponse | Response:
        """Authoring-side proxy for invoking a *draft* (or any non-live) revision.

        Closes the anonymous-draft-invoke gap: the public ingress URL refuses
        non-live invokes that don't carry the `x-agent-preview-secret` header;
        this proxy attaches it after authenticating the Django caller. See
        docs/agent-platform/plans/draft-preview-auth.md.

        URL: `/api/projects/<team>/agent_applications/<app>/preview-proxy/<rest>`
        Auth: standard PAT / session — `agent_application:read` scope.
        """
        application = self.get_object()
        if application is None:
            raise NotFound("Application not found")

        if rest not in self._PREVIEW_PROXY_ALLOWED_PATHS:
            raise ValidationError(
                f"preview-proxy path '{rest}' is not allowed. Allowed: {sorted(self._PREVIEW_PROXY_ALLOWED_PATHS)}."
            )

        revision_id = request.query_params.get("revision_id")
        if not revision_id:
            raise ValidationError("revision_id query parameter is required for preview-proxy")
        revision = AgentRevision.objects.filter(application=application, pk=revision_id).first()
        if not revision:
            raise NotFound("Revision not found in this application")
        if application.live_revision_id == revision.id:
            raise ValidationError(
                "preview-proxy is for non-live revisions only; invoke the live revision via its public ingress URL"
            )

        ingress_base = os.environ.get("AGENT_INGRESS_URL", "http://localhost:3030").rstrip("/")
        # Single URL contract for revision routing: `<slug>-<rev-hex>` in path
        # mode (dev), `<rev-hex>.<slug>.<suffix>` in domain mode (prod). Django
        # proxies via the path form using the full UUID hex (32 chars) so the
        # ingress prefix lookup is unambiguous. See revision-routing.md.
        rev_hex = revision.id.hex
        forwarded_query = {k: v for k, v in request.query_params.items() if k != "revision_id"}
        query_string = f"?{urlencode(forwarded_query)}" if forwarded_query else ""
        upstream_url = f"{ingress_base}/agents/{application.slug}-{rev_hex}/{rest}{query_string}"

        # Header set kept tight — caller's Authorization / Cookie / Host
        # identify the *Django* caller, not the agent's caller. Don't leak.
        skip_headers = {"host", "authorization", "cookie", "content-length"}
        forwarded_headers: dict[str, str] = {k: v for k, v in request.headers.items() if k.lower() not in skip_headers}
        # Same JWT the standalone `preview_token` action returns — pulled
        # out into a helper so the two paths can't drift.
        token_pair = _mint_preview_jwt(application, revision, request.user)
        if token_pair is not None:
            forwarded_headers["x-agent-preview-token"] = token_pair[0]

        # DRF's parser already consumed request.body via request.data — we
        # re-serialize the parsed payload so requests can ship a fresh body.
        # Cheaper than re-reading the raw stream (which the parser exhausted).
        body_bytes: bytes | None = None
        if request.method in ("POST", "PUT", "PATCH"):
            body_bytes = json.dumps(request.data).encode("utf-8") if request.data else b""
            forwarded_headers["content-type"] = "application/json"
        try:
            upstream = requests.request(
                method=request.method,
                url=upstream_url,
                headers=forwarded_headers,
                data=body_bytes,
                stream=True,
                timeout=30.0,
            )
        except requests.RequestException as e:
            logger.exception("preview-proxy upstream call failed")
            raise APIException(detail=f"preview-proxy upstream unreachable: {e}") from e

        def _stream() -> Iterator[bytes]:
            try:
                # iter_content with no decoding keeps SSE chunks intact.
                for chunk in upstream.iter_content(chunk_size=None):
                    if chunk:
                        yield chunk
            finally:
                upstream.close()

        resp = StreamingHttpResponse(
            _stream(),
            status=upstream.status_code,
            content_type=upstream.headers.get("Content-Type", "application/octet-stream"),
        )
        # Forward upstream response headers verbatim minus connection-control
        # ones that Django handles itself.
        skip_resp = {"content-length", "transfer-encoding", "connection", "content-type"}
        for k, v in upstream.headers.items():
            if k.lower() not in skip_resp:
                resp[k] = v
        return resp

    # Same proxy, GET counterpart. Used for SSE (`listen`). Same body, just a
    # different verb so drf-spectacular emits a distinct operation_id.
    # Renderer set inherits from the parent `@action` (includes
    # `EventStreamRenderer` so EventSource requests negotiate cleanly).
    @extend_schema(
        operation_id="agent_applications_preview_proxy_get",
        parameters=_PREVIEW_PROXY_PARAMETERS,
        request=None,
    )
    @preview_proxy.mapping.get
    def preview_proxy_get(self, request: Request, rest: str = "", **kwargs) -> StreamingHttpResponse | Response:
        """GET passthrough for the preview-proxy — used for `/listen` SSE."""
        return self.preview_proxy(request, rest=rest, **kwargs)

    # ── Preview token (direct-to-ingress flow) ───────────────────────
    # Alternative to `preview_proxy`: returns a short-lived JWT the
    # browser can attach to direct ingress calls. Console uses this
    # for chat hops (SSE through the Django proxy is awkward — DRF
    # content negotiation, redirects, body buffering all bite). The
    # proxy action stays for non-browser callers that prefer
    # server-side mediation. Both share `_mint_preview_jwt` so the
    # JWT payload + secret can't drift between paths.

    @extend_schema(
        operation_id="agent_applications_preview_token",
        parameters=[
            OpenApiParameter(
                "revision_id",
                OpenApiTypes.UUID,
                OpenApiParameter.QUERY,
                required=True,
                description="Target draft revision. Must belong to this application and not be live.",
            ),
        ],
        request=None,
        responses=OpenApiResponse(
            response=inline_serializer(
                name="AgentApplicationPreviewTokenResponse",
                fields={
                    "token": drf_serializers.CharField(
                        help_text="HS256 JWT bound to (app, rev) with a short TTL. Attach as the `x-agent-preview-token` header (POST/DELETE) or `preview_token` query param (GET, including EventSource) when calling ingress directly.",
                    ),
                    "expires_in": drf_serializers.IntegerField(
                        help_text="Token TTL in seconds from issue. Clients should refresh before this elapses.",
                    ),
                    "ingress_slug": drf_serializers.CharField(
                        help_text="Slug to use in the ingress URL — `<application_slug>-<revision_uuid_hex>`. Identifies the exact revision in the path-routing prefix.",
                    ),
                },
            )
        ),
    )
    @action(detail=True, methods=["get"], url_path="preview-token")
    def preview_token(self, request: Request, **kwargs) -> Response:
        """Mint a short-lived JWT for talking to a non-live revision
        directly via the public ingress URL. The caller attaches it as
        the `x-agent-preview-token` header (or `?preview_token=` query
        param for `EventSource`). See `_mint_preview_jwt` for the
        payload + claim binding."""
        application = self.get_object()
        if application is None:
            raise NotFound("Application not found")
        revision_id = request.query_params.get("revision_id")
        if not revision_id:
            raise ValidationError("revision_id query parameter is required")
        revision = AgentRevision.objects.filter(application=application, pk=revision_id).first()
        if not revision:
            raise NotFound("Revision not found in this application")
        if application.live_revision_id == revision.id:
            raise ValidationError(
                "preview-token is for non-live revisions only; the live revision is reachable without a token via its public ingress URL"
            )
        token_pair = _mint_preview_jwt(application, revision, request.user)
        if token_pair is None:
            # No AGENT_PREVIEW_SECRET configured — ingress's gate is
            # also bypassed in that mode, so an empty token is fine
            # (and signals the dev/harness configuration to the caller).
            return Response({"token": "", "expires_in": 0, "ingress_slug": f"{application.slug}-{revision.id.hex}"})
        token, expires_in = token_pair
        return Response(
            {
                "token": token,
                "expires_in": expires_in,
                "ingress_slug": f"{application.slug}-{revision.id.hex}",
            }
        )

    @extend_schema(
        operation_id="agent_applications_stats",
        parameters=[
            OpenApiParameter(
                "since",
                OpenApiTypes.DATETIME,
                OpenApiParameter.QUERY,
                required=False,
                description="ISO datetime — counts spend + session totals from this point forward. Defaults to 24h ago.",
            ),
        ],
        request=None,
        responses=OpenApiResponse(response=_AGENT_AGGREGATE_STATS),
        description="Roll-up stats for the agent — drives the agent-detail overview tiles.",
    )
    @action(detail=True, methods=["get"], url_path="stats")
    def stats(self, request: Request, **kwargs) -> Response:
        application = self.get_object()
        if application is None:
            raise NotFound("Application not found")
        try:
            payload = _janitor().aggregate_for_application(
                str(application.id),
                since=request.query_params.get("since") or None,
            )
        except JanitorClientError as e:
            raise JanitorUpstreamError(e) from e
        return Response(payload)

    @extend_schema(
        operation_id="agent_applications_sessions_list",
        parameters=[
            OpenApiParameter("limit", OpenApiTypes.INT, OpenApiParameter.QUERY, required=False),
            OpenApiParameter("offset", OpenApiTypes.INT, OpenApiParameter.QUERY, required=False),
            OpenApiParameter(
                "state",
                OpenApiTypes.STR,
                OpenApiParameter.QUERY,
                required=False,
                description=(
                    "Filter by session state. Comma-separated list accepted "
                    "(e.g. `completed,failed`). Valid values: queued, running, "
                    "completed, closed, cancelled, failed."
                ),
            ),
            OpenApiParameter(
                "revision_id",
                OpenApiTypes.UUID,
                OpenApiParameter.QUERY,
                required=False,
                description="Only return sessions started against this specific revision.",
            ),
            OpenApiParameter(
                "created_after",
                OpenApiTypes.DATETIME,
                OpenApiParameter.QUERY,
                required=False,
                description="ISO datetime — return sessions with created_at >= this.",
            ),
            OpenApiParameter(
                "created_before",
                OpenApiTypes.DATETIME,
                OpenApiParameter.QUERY,
                required=False,
                description="ISO datetime — return sessions with created_at <= this.",
            ),
        ],
        request=None,
        responses=OpenApiResponse(
            response=inline_serializer(
                name="AgentApplicationSessionsListResponse",
                fields={
                    "results": drf_serializers.ListField(
                        child=inline_serializer(
                            name="AgentSessionSummary",
                            fields={
                                "id": drf_serializers.UUIDField(),
                                "application_id": drf_serializers.UUIDField(),
                                "revision_id": drf_serializers.UUIDField(),
                                "state": drf_serializers.ChoiceField(choices=_AGENT_SESSION_STATE_VALUES),
                                "external_key": drf_serializers.CharField(allow_null=True),
                                "principal": _AGENT_SESSION_PRINCIPAL,
                                "turns": drf_serializers.IntegerField(
                                    help_text="Count of messages in the conversation — the full transcript ships on the detail endpoint.",
                                ),
                                "preview": drf_serializers.CharField(
                                    allow_null=True,
                                    help_text="Last assistant text (~120 chars). Null for sessions with no assistant turns yet.",
                                ),
                                "usage_total": _AGENT_SESSION_USAGE_TOTAL,
                                "retry_count": drf_serializers.IntegerField(),
                                "created_at": drf_serializers.DateTimeField(),
                                "updated_at": drf_serializers.DateTimeField(),
                            },
                        ),
                    ),
                    "count": drf_serializers.IntegerField(help_text="Total matching sessions before pagination."),
                },
            )
        ),
    )
    @action(detail=True, methods=["get"], url_path="sessions")
    def sessions_list(self, request: Request, **kwargs) -> Response:
        """List sessions for this application, newest first. Strips the
        conversation transcript from each summary, but includes a `preview`
        (last assistant text, ~120 chars) and `usage_total` (token + cost
        aggregate). Use `agent-applications-sessions-retrieve` for the full
        transcript of a single session."""
        application = self.get_object()
        if application is None:
            raise NotFound("Application not found")
        limit_param = request.query_params.get("limit")
        offset_param = request.query_params.get("offset")
        try:
            limit = int(limit_param) if limit_param is not None else None
            offset = int(offset_param) if offset_param is not None else None
        except ValueError:
            raise ValidationError("limit and offset must be integers")
        try:
            payload = _janitor().list_sessions(
                str(application.id),
                limit=limit,
                offset=offset,
                state=request.query_params.get("state") or None,
                revision_id=request.query_params.get("revision_id") or None,
                created_after=request.query_params.get("created_after") or None,
                created_before=request.query_params.get("created_before") or None,
            )
        except JanitorClientError as e:
            raise JanitorUpstreamError(e) from e
        return Response(payload)

    @extend_schema(
        operation_id="agent_applications_sessions_retrieve",
        parameters=[
            OpenApiParameter(
                "session_id",
                OpenApiTypes.UUID,
                OpenApiParameter.PATH,
                required=True,
                description="UUID of the session to fetch (must belong to this application).",
            ),
            OpenApiParameter(
                "last_n",
                OpenApiTypes.INT,
                OpenApiParameter.QUERY,
                required=False,
                description=(
                    "If set, return only the most recent N messages from the "
                    "conversation. `usage_total` is still computed over the "
                    "full session — only the transcript is trimmed. The "
                    "response includes `conversation_trimmed: true` and "
                    "`conversation_total_turns` so the caller knows how much "
                    "was hidden."
                ),
            ),
        ],
        request=None,
        responses=OpenApiResponse(
            response=inline_serializer(
                name="AgentApplicationSessionsRetrieveResponse",
                fields={
                    "id": drf_serializers.UUIDField(),
                    "application_id": drf_serializers.UUIDField(),
                    "revision_id": drf_serializers.UUIDField(),
                    "team_id": drf_serializers.IntegerField(),
                    "external_key": drf_serializers.CharField(allow_null=True),
                    "state": drf_serializers.ChoiceField(choices=_AGENT_SESSION_STATE_VALUES),
                    "principal": _AGENT_SESSION_PRINCIPAL,
                    "conversation": drf_serializers.ListField(
                        child=_AgentConversationMessageField(),
                        help_text="Full transcript, or the trailing `last_n` messages if `?last_n=` was supplied.",
                    ),
                    "pending_inputs": drf_serializers.ListField(
                        child=_AgentConversationMessageField(),
                        help_text="Messages that arrived while a turn was in flight; drained into `conversation` at the start of the next turn.",
                    ),
                    "retry_count": drf_serializers.IntegerField(
                        help_text="Times the janitor has re-queued this session after a stuck-running detection.",
                    ),
                    "usage_total": _AGENT_SESSION_USAGE_TOTAL,
                    "created_at": drf_serializers.DateTimeField(),
                    "updated_at": drf_serializers.DateTimeField(),
                    "conversation_trimmed": drf_serializers.BooleanField(
                        help_text="True when `?last_n=` was supplied AND the full conversation exceeded it.",
                    ),
                    "conversation_total_turns": drf_serializers.IntegerField(
                        required=False,
                        help_text="Total messages in the untrimmed conversation. Present only when `conversation_trimmed=true`.",
                    ),
                },
            )
        ),
    )
    @action(detail=True, methods=["get"], url_path="sessions/(?P<session_id>[^/.]+)")
    def sessions_retrieve(self, request: Request, session_id: str = "", **kwargs) -> Response:
        """Fetch one session's state — full conversation by default, or just
        the trailing N messages with `?last_n=`. Always returns a
        `usage_total` block aggregated over the entire session, regardless of
        trim. The runner-side queue DB is the source of truth."""
        application = self.get_object()
        if application is None:
            raise NotFound("Application not found")
        last_n_param = request.query_params.get("last_n")
        try:
            last_n = int(last_n_param) if last_n_param is not None else None
        except ValueError:
            raise ValidationError("last_n must be a non-negative integer")
        if last_n is not None and last_n < 0:
            raise ValidationError("last_n must be a non-negative integer")
        try:
            payload = _janitor().get_session(session_id, last_n=last_n)
        except JanitorClientError as e:
            raise JanitorUpstreamError(e) from e
        # Cross-check ownership: the janitor doesn't know about teams. Reject
        # if the session belongs to a different application than the URL says.
        if payload.get("application_id") != str(application.id):
            raise NotFound("Session not found")
        return Response(payload)

    # ── Per-session logs (ClickHouse) ────────────────────────────────
    # The runner writes structured events via `KafkaLogSink` into the
    # `log_entries` CH table, tagged with:
    #   log_source = "agent_session"   (constant; see agent-shared/runtime/log-sink.ts)
    #   log_source_id = <application_id>
    #   instance_id   = <session_id>
    # We use the shared `fetch_log_entries` helper (also used by hog_function,
    # hog_flow, batch_exports) for filter / paginate semantics.

    @extend_schema(
        operation_id="agent_applications_session_logs",
        parameters=[
            OpenApiParameter(
                "session_id",
                OpenApiTypes.UUID,
                OpenApiParameter.PATH,
                required=True,
                description="UUID of the session whose logs to fetch.",
            ),
            LogEntryRequestSerializer,
        ],
        request=None,
        responses=OpenApiResponse(
            response=inline_serializer(
                name="AgentApplicationSessionLogsResponse",
                fields={
                    "results": LogEntrySerializer(many=True),
                },
            )
        ),
    )
    @action(detail=True, methods=["get"], url_path="sessions/(?P<session_id>[^/.]+)/logs")
    def session_logs(self, request: Request, session_id: str = "", **kwargs) -> Response:
        """Read the runner's structured event log for one session from
        ClickHouse. Filters (limit / after / before / level / search)
        match the shared `LogEntryMixin` helper used by hog_function +
        hog_flow."""
        application = self.get_object()
        if application is None:
            raise NotFound("Application not found")
        # Every CH query needs `tag_queries(product, feature)` — without
        # it the query layer raises `UntaggedQueryError`. There's no
        # agent-specific ProductKey yet; LOGS is the closest fit.
        tag_queries(product=ProductKey.LOGS, feature=Feature.QUERY)
        params = LogEntryRequestSerializer(data=request.query_params)
        params.is_valid(raise_exception=True)
        p = params.validated_data
        rows = fetch_log_entries(
            team_id=self.team_id,
            log_source=AGENT_SESSION_LOG_SOURCE,
            log_source_id=str(application.id),
            instance_id=session_id,
            limit=p["limit"],
            after=p.get("after"),
            before=p.get("before"),
            search=p.get("search"),
            level=p["level"].split(",") if p.get("level") else None,
        )
        return Response({"results": LogEntrySerializer(rows, many=True).data})

    # ──────────────────────────── approval-gated tools ────────────────────────
    # See docs/agent-platform/plans/approval-gated-tools.md.
    #
    # AGENT_DB is node-owned (per CLAUDE.md rule #2 in products/agent_stack).
    # Django never queries `agent_tool_approval_request` directly — these
    # actions auth-check on the Django side, then proxy through
    # janitor_client. The janitor owns the wake path (markApproving + write
    # marker into pending_inputs); the runner picks up on its next claim.

    _APPROVAL_RESPONSE_FIELDS = {
        "id": drf_serializers.UUIDField(help_text="Approval request UUID — stable, used in /approvals/<id>/decide."),
        "session_id": drf_serializers.UUIDField(help_text="UUID of the session that proposed the gated call."),
        "application_id": drf_serializers.UUIDField(help_text="UUID of the parent agent application."),
        "team_id": drf_serializers.IntegerField(help_text="Team that owns the agent."),
        "revision_id": drf_serializers.UUIDField(help_text="Revision the gated call was proposed against."),
        "turn": drf_serializers.IntegerField(help_text="Turn number within the session that emitted the call."),
        "tool_call_id": drf_serializers.CharField(
            help_text="pi-ai ToolCall.id from the original assistant message; matched into the synthetic tool_result."
        ),
        "tool_name": drf_serializers.CharField(help_text="Tool id the model invoked (e.g. `@posthog/team-delete`)."),
        "proposed_args": drf_serializers.DictField(
            child=drf_serializers.JSONField(),
            help_text="Arguments the model proposed. Frozen at intercept time.",
        ),
        "decided_args": drf_serializers.DictField(
            child=drf_serializers.JSONField(),
            allow_null=True,
            help_text="Approver-edited arguments. Present iff `approval_policy.allow_edit` was true and the approver supplied edits.",
        ),
        "assistant_message": drf_serializers.DictField(
            child=drf_serializers.JSONField(),
            help_text="Snapshot of the assistant message that emitted the call (text + thinking blocks) — what the approver sees as the model's reasoning.",
        ),
        "approver_scope": drf_serializers.DictField(
            child=drf_serializers.JSONField(),
            help_text="Resolved approver policy (approvers, allow_edit, allow_agent_approver) at request time.",
        ),
        "state": drf_serializers.ChoiceField(
            choices=[
                "queued",
                "approving",
                "dispatched",
                "dispatched_failed",
                "rejected",
                "expired",
            ],
            help_text="Lifecycle state. `queued` = awaiting an approver; `approving` = decision landed and tool dispatch is in flight; `dispatched`/`dispatched_failed` = approved + tool ran; `rejected` = approver said no; `expired` = TTL elapsed.",
        ),
        "decision_by": drf_serializers.CharField(
            allow_null=True,
            help_text="UUID of the user who decided. Null while queued or expired.",
        ),
        "decision_at": drf_serializers.DateTimeField(
            allow_null=True,
            help_text="ISO timestamp of the decision. Null while queued.",
        ),
        "decision_reason": drf_serializers.CharField(
            allow_null=True,
            help_text="Free-form reason supplied by the approver. Optional.",
        ),
        "dispatch_outcome": drf_serializers.DictField(
            child=drf_serializers.JSONField(),
            allow_null=True,
            help_text='`{result: ...}` on a successful approved dispatch, `{error: "..."}` when the tool threw. Null until the runner has finalised.',
        ),
        "created_at": drf_serializers.DateTimeField(help_text="When the model proposed the gated call."),
        "expires_at": drf_serializers.DateTimeField(
            help_text="When the queued request auto-rejects if no decision arrives."
        ),
    }

    def _require_team_admin(self) -> None:
        """Approval decisions are an admin-only surface in v0 (plan §6.1).
        Listing / retrieving approvals does the same check so non-admins
        can't browse what they can't act on.
        """
        membership = OrganizationMembership.objects.filter(
            user=self.request.user, organization_id=self.organization_id
        ).first()
        if membership is None or membership.level < OrganizationMembership.Level.ADMIN:
            raise NotFound("Application not found")

    @extend_schema(
        operation_id="agent_applications_approvals_list",
        parameters=[
            OpenApiParameter(
                "state",
                OpenApiTypes.STR,
                OpenApiParameter.QUERY,
                required=False,
                description=(
                    "Filter by approval state. Comma-separated list accepted. "
                    "Valid values: queued, approving, dispatched, "
                    "dispatched_failed, rejected, expired. Defaults to all states."
                ),
            ),
            OpenApiParameter("limit", OpenApiTypes.INT, OpenApiParameter.QUERY, required=False),
            OpenApiParameter("offset", OpenApiTypes.INT, OpenApiParameter.QUERY, required=False),
        ],
        request=None,
        responses=OpenApiResponse(
            response=inline_serializer(
                name="AgentApplicationApprovalsListResponse",
                fields={
                    "results": drf_serializers.ListField(
                        child=inline_serializer(
                            name="AgentApprovalRequest",
                            fields=_APPROVAL_RESPONSE_FIELDS,
                        ),
                        help_text="Approval requests for this application, newest first.",
                    ),
                },
            )
        ),
    )
    @action(detail=True, methods=["get"], url_path="approvals")
    def approvals_list(self, request: Request, **kwargs) -> Response:
        """List approval-gated tool requests for this application. Team-admin
        only (per plan §6.1). Default returns all states — pass `?state=queued`
        for the inbox view."""
        application = self.get_object()
        if application is None:
            raise NotFound("Application not found")
        self._require_team_admin()
        limit_param = request.query_params.get("limit")
        offset_param = request.query_params.get("offset")
        try:
            limit = int(limit_param) if limit_param is not None else None
            offset = int(offset_param) if offset_param is not None else None
        except ValueError:
            raise ValidationError("limit and offset must be integers")
        try:
            payload = _janitor().list_approvals(
                str(application.id),
                state=request.query_params.get("state") or None,
                limit=limit,
                offset=offset,
            )
        except JanitorClientError as e:
            raise JanitorUpstreamError(e) from e
        return Response(payload)

    @extend_schema(
        operation_id="agent_applications_approvals_retrieve",
        parameters=[
            OpenApiParameter(
                "approval_id",
                OpenApiTypes.UUID,
                OpenApiParameter.PATH,
                required=True,
                description="UUID of the approval request (must belong to this application).",
            ),
        ],
        request=None,
        responses=OpenApiResponse(
            response=inline_serializer(
                name="AgentApprovalRequestDetail",
                fields=_APPROVAL_RESPONSE_FIELDS,
            )
        ),
    )
    @action(detail=True, methods=["get"], url_path="approvals/(?P<approval_id>[^/.]+)")
    def approvals_retrieve(self, request: Request, approval_id: str = "", **kwargs) -> Response:
        """Single approval request — full proposed args, assistant snapshot,
        decision metadata, dispatch outcome. Team-admin only (plan §6.1)."""
        application = self.get_object()
        if application is None:
            raise NotFound("Application not found")
        self._require_team_admin()
        try:
            payload = _janitor().get_approval(approval_id)
        except JanitorClientError as e:
            raise JanitorUpstreamError(e) from e
        # Cross-check ownership: the janitor doesn't know about teams.
        if payload.get("application_id") != str(application.id):
            raise NotFound("Approval not found")
        return Response(payload)

    @extend_schema(
        operation_id="agent_applications_approvals_decide",
        parameters=[
            OpenApiParameter(
                "approval_id",
                OpenApiTypes.UUID,
                OpenApiParameter.PATH,
                required=True,
                description="UUID of the approval request to decide.",
            ),
        ],
        request=DecideApprovalRequestSerializer,
        responses=OpenApiResponse(
            response=inline_serializer(
                name="AgentApprovalsDecideResponse",
                fields={
                    "ok": drf_serializers.BooleanField(help_text="Always `true` on a successful decision."),
                    "state": drf_serializers.CharField(
                        help_text="The approval row's new state — `approving` for approve, `rejected` for reject."
                    ),
                },
            )
        ),
    )
    @action(detail=True, methods=["post"], url_path="approvals/(?P<approval_id>[^/.]+)/decide")
    def approvals_decide(self, request: Request, approval_id: str = "", **kwargs) -> Response:
        """Approve or reject a queued tool-approval request. Team-admin only
        (plan §6.1). The runtime side runs the tool platform-side on approve
        and wakes the session with a synthetic tool_result either way."""
        application = self.get_object()
        if application is None:
            raise NotFound("Application not found")
        self._require_team_admin()
        body = DecideApprovalRequestSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        # Cross-check ownership before forwarding.
        try:
            existing = _janitor().get_approval(approval_id)
        except JanitorClientError as e:
            raise JanitorUpstreamError(e) from e
        if existing.get("application_id") != str(application.id):
            raise NotFound("Approval not found")
        if existing.get("approver_scope", {}).get("allow_agent_approver") is False and not getattr(
            request.user, "is_authenticated", False
        ):
            # PATs / service tokens are rejected unless the spec opts in.
            # Real PAT-vs-user discrimination would go here; for v0 we rely
            # on Django auth + the admin check above as a coarse filter.
            raise NotFound("Approval not found")
        try:
            payload = _janitor().decide_approval(
                approval_id,
                decision=body.validated_data["decision"],
                decided_by=str(request.user.pk) if request.user and request.user.is_authenticated else "",
                edited_args=body.validated_data.get("edited_args"),
                reason=body.validated_data.get("reason"),
            )
        except JanitorClientError as e:
            raise JanitorUpstreamError(e) from e
        return Response(payload)


@extend_schema(tags=["agent_stack"])
class AgentRevisionViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    """Revisions of an agent. Created in `draft`, promoted through
    `ready → live` once the bundle has been uploaded + frozen.

    URLs (nested under an application):

        Model CRUD:
            GET   .../revisions/                       list
            POST  .../revisions/                       create draft
            GET   .../revisions/<id>/                  retrieve
            PATCH .../revisions/<id>/                  update spec (draft only)

        Lifecycle:
            POST  .../revisions/<id>/promote/          ready → live
            POST  .../revisions/<id>/archive/          → archived
            POST  .../revisions/<id>/freeze/           draft → ready (stamps sha256)
            POST  .../revisions/<id>/clone_from/       copy bundle from another rev
            POST  .../revisions/new_draft/             create draft + clone_from atomically

        Bundle authoring (proxied to the janitor):
            GET    .../revisions/<id>/manifest/        list paths + sha256
            GET    .../revisions/<id>/file/?path=…     read one file
            PUT    .../revisions/<id>/file/?path=…     write one file (draft)
            DELETE .../revisions/<id>/file/?path=…     delete one file (draft)
            GET    .../revisions/<id>/bundle/          bulk pull all files
            PUT    .../revisions/<id>/bundle/          bulk push (replace|merge)
    """

    scope_object = "agent_application"  # share the parent's scope
    # AgentRevision is tenant-scoped via its parent application, not directly.
    # The URL kwarg `project_id` from the parent router defaults to filtering
    # `team__project_id` on the queryset, but AgentRevision only has
    # `application__team__project_id`. Rewrite the parent lookup accordingly.
    filter_rewrite_rules = {"project_id": "application__team__project_id"}
    scope_object_write_actions = [
        "create",
        "update",
        "partial_update",
        "promote",
        "archive",
        "freeze",
        "clone_from",
        "new_draft",
        "put_file",
        "delete_file",
        "put_bundle",
    ]
    scope_object_read_actions = [
        "list",
        "retrieve",
        "manifest",
        "get_file",
        "get_bundle",
        "validate",
        "system_prompt",
    ]
    serializer_class = AgentRevisionSerializer
    queryset = AgentRevision.objects.all()

    def get_application(self) -> AgentApplication:
        # drf-extensions nested routing passes the parent URL kwarg as
        # `parent_lookup_application_id` (see `parents_query_lookups` in the
        # nested router registration in posthog/api/__init__.py).
        app = _resolve_application(
            AgentApplication.objects.filter(team_id=self.team_id, archived=False),
            self.kwargs.get("parent_lookup_application_id") or self.kwargs.get("application_id"),
        )
        if app is None:
            raise NotFound("Application not found")
        return app

    def safely_get_queryset(self, queryset: QuerySet) -> QuerySet:
        return queryset.filter(application=self.get_application())

    @cached_property
    def parents_query_dict(self) -> dict[str, Any]:
        # The mixin auto-filters by every parent URL kwarg as a literal value
        # (e.g. `application_id="hello"`). Our parent supports slug-or-UUID
        # via `_resolve_application`, so a slug in the URL otherwise blows up
        # with "'hello' is not a valid UUID". Override the cached lookup dict
        # to substitute the resolved PK before super filters.
        result = super().parents_query_dict
        raw = result.get("application_id")
        if raw is None:
            return result
        try:
            UUID(str(raw))
            return result
        except (ValueError, TypeError):
            return {**result, "application_id": str(self.get_application().id)}

    def perform_create(self, serializer: AgentRevisionSerializer) -> None:
        application = self.get_application()
        # Fresh revisions start in `draft`. Parent revision is optional — if
        # set, this revision can later be diff'd against it for review.
        serializer.save(
            application=application,
            state="draft",
            created_by=self.request.user,
        )

    def update(self, request: Request, *args, **kwargs) -> Response:
        """Spec edits are only allowed while state='draft'. Once promoted to
        ready/live the spec is frozen — change requires a new revision."""
        instance: AgentRevision = self.get_object()
        if instance.state != "draft":
            raise ValidationError(f"Cannot edit spec on a {instance.state} revision; create a new draft instead.")
        return super().update(request, *args, **kwargs)

    @extend_schema(request=PromoteRevisionRequestSerializer)
    @action(detail=True, methods=["post"], url_path="promote")
    def promote(self, request: Request, **kwargs) -> Response:
        """ready → live. Sets the parent application's live_revision."""
        revision: AgentRevision = self.get_object()
        body = PromoteRevisionRequestSerializer(data=request.data)
        body.is_valid(raise_exception=True)

        if revision.state == "live":
            return Response({"ok": True, "state": "live", "no_op": True})
        if revision.state != "ready":
            raise ValidationError(f"Revision is in state '{revision.state}'; only 'ready' can be promoted.")
        if not revision.bundle_sha256:
            raise ValidationError("Revision has no frozen bundle (bundle_sha256 is null).")

        application = revision.application
        # Demote whatever's currently live, if anything different.
        previously_live = application.live_revision
        if previously_live and previously_live.id != revision.id:
            previously_live.state = "archived"
            previously_live.save(update_fields=["state", "updated_at"])

        revision.state = "live"
        revision.save(update_fields=["state", "updated_at"])
        application.live_revision = revision
        application.save(update_fields=["live_revision", "updated_at"])
        return Response({"ok": True, "state": "live"})

    @extend_schema(request=None)
    @action(detail=True, methods=["post"], url_path="archive")
    def archive(self, request: Request, **kwargs) -> Response:
        """Mark a revision archived. If it was the live one, clear the
        application's live_revision pointer (the app effectively has no
        deployable version until another revision is promoted)."""
        revision: AgentRevision = self.get_object()
        if revision.state == "archived":
            return Response({"ok": True, "no_op": True})
        application = revision.application
        revision.state = "archived"
        revision.save(update_fields=["state", "updated_at"])
        if application.live_revision_id == revision.id:
            application.live_revision = None
            application.save(update_fields=["live_revision", "updated_at"])
        return Response({"ok": True, "state": "archived"})

    # ── Bundle proxy actions ───────────────────────────────────────────────

    def _call(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """Wrap a janitor call: map upstream errors into DRF responses."""
        try:
            return fn(*args, **kwargs)
        except JanitorClientError as e:
            raise JanitorUpstreamError(e) from e

    @extend_schema(request=None)
    @action(detail=True, methods=["get"], url_path="manifest")
    def manifest(self, request: Request, **kwargs) -> Response:
        """List every file in this revision's bundle (path, size, sha256)."""
        revision: AgentRevision = self.get_object()
        return Response(self._call(_janitor().manifest, str(revision.id)))

    # DRF routes /file/ and /bundle/ across multiple HTTP verbs via a single
    # @action + .mapping.<verb> chain. Three separate @action decorators with
    # the same url_path don't merge — the last one registered wins and the
    # others 405.
    _FILE_PATH_PARAM = OpenApiParameter(
        "path",
        OpenApiTypes.STR,
        OpenApiParameter.QUERY,
        required=True,
        description="Bundle-relative file path, e.g. `agent.md` or `skills/research.md`.",
    )

    @extend_schema(parameters=[_FILE_PATH_PARAM], request=None)
    @action(detail=True, methods=["get"], url_path="file")
    def get_file(self, request: Request, **kwargs) -> Response:
        """Read one file by `?path=...`. Works on any revision state."""
        revision: AgentRevision = self.get_object()
        path = request.query_params.get("path")
        if not path:
            raise ValidationError("Missing ?path=… query parameter.")
        return Response(self._call(_janitor().get_file, str(revision.id), path))

    @extend_schema(parameters=[_FILE_PATH_PARAM], request=WriteFileRequestSerializer)
    @get_file.mapping.put
    def put_file(self, request: Request, **kwargs) -> Response:
        """Write one file by `?path=...`. Draft-only (janitor enforces)."""
        revision: AgentRevision = self.get_object()
        path = request.query_params.get("path")
        if not path:
            raise ValidationError("Missing ?path=… query parameter.")
        body = WriteFileRequestSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        return Response(self._call(_janitor().put_file, str(revision.id), path, body.validated_data["content"]))

    @extend_schema(parameters=[_FILE_PATH_PARAM], request=None)
    @get_file.mapping.delete
    def delete_file(self, request: Request, **kwargs) -> Response:
        """Delete one file by `?path=...`. Draft-only."""
        revision: AgentRevision = self.get_object()
        path = request.query_params.get("path")
        if not path:
            raise ValidationError("Missing ?path=… query parameter.")
        return Response(self._call(_janitor().delete_file, str(revision.id), path))

    @extend_schema(request=None)
    @action(detail=True, methods=["get"], url_path="bundle")
    def get_bundle(self, request: Request, **kwargs) -> Response:
        """Bulk-pull: returns `{ files: { path: content, ... }, ... }`. Use
        this when the MCP wants the whole bundle to work on locally."""
        revision: AgentRevision = self.get_object()
        return Response(self._call(_janitor().get_bundle, str(revision.id)))

    @extend_schema(request=WriteBundleRequestSerializer)
    @get_bundle.mapping.put
    def put_bundle(self, request: Request, **kwargs) -> Response:
        """Bulk-push the bundle. Body `{ files, mode: replace|merge }`."""
        revision: AgentRevision = self.get_object()
        body = WriteBundleRequestSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        return Response(
            self._call(
                _janitor().put_bundle,
                str(revision.id),
                body.validated_data["files"],
                body.validated_data["mode"],
            )
        )

    @extend_schema(
        request=None,
        responses=OpenApiResponse(
            response=inline_serializer(
                name="AgentRevisionValidateResponse",
                fields={
                    "ok": drf_serializers.BooleanField(),
                    "revision_id": drf_serializers.UUIDField(),
                    "revision_state": drf_serializers.CharField(),
                    "errors": drf_serializers.ListField(
                        child=inline_serializer(
                            name="AgentRevisionValidationError",
                            fields={
                                "code": drf_serializers.CharField(),
                                "message": drf_serializers.CharField(),
                                "pointer": drf_serializers.CharField(),
                            },
                        ),
                    ),
                    "resolved_natives": drf_serializers.ListField(child=drf_serializers.CharField()),
                },
            )
        ),
    )
    @action(detail=True, methods=["post"], url_path="validate")
    def validate(self, request: Request, **kwargs) -> Response:
        """Pre-flight checks before freeze + promote: entrypoint file exists,
        every native tool id is registered, every custom tool has its
        compiled.js + schema.json, every skill path exists, every declared
        secret has a value set in the application's env block. Returns
        `{ ok, errors: [...] }`. Works on any revision state."""
        revision: AgentRevision = self.get_object()
        report = self._call(_janitor().validate, str(revision.id))
        errors = list(report.get("errors", []))

        application = revision.application
        decrypted = application.encrypted_env or ""
        available_keys: set[str] = set()
        if decrypted:
            try:
                env_map = json.loads(decrypted)
                if isinstance(env_map, dict):
                    available_keys = {str(k) for k in env_map}
            except (ValueError, TypeError):
                pass
        for i, secret_name in enumerate(revision.spec.get("secrets") or []):
            if secret_name not in available_keys:
                errors.append(
                    {
                        "code": "missing_secret",
                        "message": f'secret "{secret_name}" is not set in the application env',
                        "pointer": f"spec.secrets[{i}]",
                    }
                )
        report["errors"] = errors
        report["ok"] = len(errors) == 0
        return Response(report)

    @extend_schema(
        operation_id="agent_applications_revisions_system_prompt",
        request=None,
        responses=OpenApiResponse(
            response=inline_serializer(
                name="AgentRevisionSystemPromptResponse",
                fields={
                    "revision_id": drf_serializers.UUIDField(
                        help_text="UUID of the revision the prompt was rendered for.",
                    ),
                    "framework_prompt_version": drf_serializers.IntegerField(
                        help_text=(
                            "Active framework preamble version. Bumps when the "
                            "platform's `# Platform guidance` content changes "
                            "meaningfully (decision rules, sections renamed, "
                            "behavioural defaults flipped). Authors can pin to "
                            "a specific version via `spec.framework_prompt.version_pin`."
                        ),
                    ),
                    "system_prompt": drf_serializers.CharField(
                        help_text=(
                            "Fully-assembled system prompt the runner would pass "
                            "to pi-ai for a session against this revision. "
                            "Concatenates the platform framework preamble, the "
                            "bundle's `agent.md` (or `spec.entrypoint`), and the "
                            "skills index. Inspect before promotion to confirm "
                            "the model will see what you expect — see "
                            "docs/agent-platform/plans/framework-system-prompt.md §4."
                        ),
                    ),
                },
            )
        ),
    )
    @action(detail=True, methods=["get"], url_path="system_prompt")
    def system_prompt(self, request: Request, **kwargs) -> Response:
        """Return the fully-assembled system prompt for this revision.

        Authoring tools call this to preview what the model will actually
        see at session start — the platform framework preamble plus the
        bundle's `agent.md` plus the skills index. Useful for debugging
        author-vs-framework precedence conflicts and verifying
        `spec.framework_prompt.omit` overrides took effect.
        """
        revision: AgentRevision = self.get_object()
        result = self._call(_janitor().get_system_prompt, str(revision.id))
        return Response(result)

    @extend_schema(request=None)
    @action(detail=True, methods=["post"], url_path="freeze")
    def freeze(self, request: Request, **kwargs) -> Response:
        """Freeze the bundle: draft → ready, stamps sha256 on the row.
        The janitor computes the digest and updates the revision row in PG;
        Django re-reads the row before returning so the response reflects
        the persisted state."""
        revision: AgentRevision = self.get_object()
        result = self._call(_janitor().freeze, str(revision.id))
        revision.refresh_from_db()
        return Response(
            {
                **result,
                "revision": AgentRevisionSerializer(revision).data,
            }
        )

    @extend_schema(request=CloneFromRequestSerializer)
    @action(detail=True, methods=["post"], url_path="clone_from")
    def clone_from(self, request: Request, **kwargs) -> Response:
        """Copy every file from `source_revision_id` into this revision."""
        revision: AgentRevision = self.get_object()
        body = CloneFromRequestSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        source_id = str(body.validated_data["source_revision_id"])
        # Guard against cross-app cloning — the source must belong to the same
        # team. The janitor doesn't enforce this since it trusts Django.
        source = AgentRevision.objects.filter(application__team_id=self.team_id, pk=source_id).first()
        if source is None:
            raise NotFound("Source revision not found in this team.")
        return Response(self._call(_janitor().clone_from, str(revision.id), source_id))

    @extend_schema(request=NewDraftRevisionRequestSerializer)
    @action(detail=False, methods=["post"], url_path="new_draft")
    def new_draft(self, request: Request, **kwargs) -> Response:
        """Create a fresh draft revision under `application_id` and seed it
        from `source_revision_id`. Saves the MCP one round-trip vs the
        explicit create + clone_from sequence."""
        body = NewDraftRevisionRequestSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        application_id = str(body.validated_data["application_id"])
        source_id = str(body.validated_data["source_revision_id"])

        application = AgentApplication.objects.filter(team_id=self.team_id, pk=application_id, archived=False).first()
        if application is None:
            raise NotFound("Application not found in this team.")
        source = AgentRevision.objects.filter(application__team_id=self.team_id, pk=source_id).first()
        if source is None:
            raise NotFound("Source revision not found in this team.")

        # bundle_uri convention: the runner-side bundle store resolves this.
        # In dev/CI we use a filesystem prefix derived from the app + new
        # revision id; prod swaps in the team's S3 prefix at deploy time.
        draft = AgentRevision.objects.create(
            application=application,
            parent_revision=source,
            created_by=self.request.user,
            state="draft",
            bundle_uri=source.bundle_uri,  # same bundle root; janitor scopes by revision_id
            spec=source.spec,
        )
        self._call(_janitor().clone_from, str(draft.id), source_id)
        return Response(
            {
                "revision": AgentRevisionSerializer(draft).data,
                "source_revision_id": source_id,
            },
            status=status.HTTP_201_CREATED,
        )


@extend_schema(tags=["agent_stack"])
class AgentNativeToolsViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    """Read-only catalog of every `@posthog/*` native tool the runner knows.

    URLs:
        GET /api/projects/<team>/agent_native_tools/    — list

    Backed by the janitor (which imports `listNativeTools()` from
    `@posthog/agent-tools`). Keeps a single source of truth for what tools
    exist — agents can't put unknown tool ids in their spec, and the MCP /
    wizard show this list to humans + models when picking what to wire up.
    """

    scope_object = "agent_application"
    scope_object_read_actions = ["list"]

    @extend_schema(
        responses=OpenApiResponse(
            response=inline_serializer(
                name="AgentNativeToolsListResponse",
                fields={
                    "tools": drf_serializers.ListField(
                        child=inline_serializer(
                            name="AgentNativeToolEntry",
                            fields={
                                "id": drf_serializers.CharField(),
                                "schema": drf_serializers.DictField(),
                            },
                        ),
                    ),
                },
            )
        ),
        description="Read-only catalog of every @posthog/* native tool the runner knows.",
    )
    def list(self, request: Request, **kwargs) -> Response:
        try:
            return Response(_janitor().native_tools())
        except JanitorClientError as e:
            raise JanitorUpstreamError(e) from e


@extend_schema(tags=["agent_stack"])
class AgentFleetViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    """Team-wide agent fleet rollups.

    URLs:
        GET /api/projects/<team>/agent_fleet/stats/           — aggregate counts + spend across every agent in the team
        GET /api/projects/<team>/agent_fleet/live_sessions/   — live sessions for every agent in the team

    Both endpoints proxy the janitor (which owns the runtime DB). Used by
    the agent-console "fleet" overview to render the cards on the agents
    list without per-agent N+1.
    """

    scope_object = "agent_application"
    scope_object_read_actions = ["stats", "live_sessions"]

    @extend_schema(
        operation_id="agent_fleet_stats",
        parameters=[
            OpenApiParameter(
                "since",
                OpenApiTypes.DATETIME,
                OpenApiParameter.QUERY,
                required=False,
                description="ISO datetime — counts spend + session totals from this point forward. Defaults to 24h ago.",
            ),
        ],
        request=None,
        responses=OpenApiResponse(response=_AGENT_AGGREGATE_STATS),
        description="Roll-up stats across every agent owned by this team.",
    )
    @action(detail=False, methods=["get"], url_path="stats")
    def stats(self, request: Request, **kwargs) -> Response:
        try:
            payload = _janitor().aggregate_for_team(
                int(self.team_id),
                since=request.query_params.get("since") or None,
            )
        except JanitorClientError as e:
            raise JanitorUpstreamError(e) from e
        return Response(payload)

    @extend_schema(
        operation_id="agent_fleet_live_sessions",
        parameters=[
            OpenApiParameter(
                "limit",
                OpenApiTypes.INT,
                OpenApiParameter.QUERY,
                required=False,
                description="Cap on returned sessions (default 100, max 500).",
            ),
        ],
        request=None,
        responses=OpenApiResponse(
            response=inline_serializer(
                name="AgentFleetLiveSessionsResponse",
                fields={
                    "results": drf_serializers.ListField(
                        child=inline_serializer(
                            name="AgentFleetLiveSessionSummary",
                            fields={
                                "id": drf_serializers.UUIDField(),
                                "application_id": drf_serializers.UUIDField(),
                                "revision_id": drf_serializers.UUIDField(),
                                "team_id": drf_serializers.IntegerField(),
                                "state": drf_serializers.ChoiceField(choices=_AGENT_SESSION_STATE_VALUES),
                                "external_key": drf_serializers.CharField(allow_null=True),
                                "principal": _AGENT_SESSION_PRINCIPAL,
                                "turns": drf_serializers.IntegerField(
                                    help_text="Messages in the conversation so far.",
                                ),
                                "preview": drf_serializers.CharField(
                                    allow_null=True,
                                    help_text="Last assistant text (~120 chars). Null when no assistant turns yet.",
                                ),
                                "usage_total": _AGENT_SESSION_USAGE_TOTAL,
                                "created_at": drf_serializers.DateTimeField(),
                                "updated_at": drf_serializers.DateTimeField(),
                            },
                        ),
                    ),
                },
            ),
        ),
        description="Live (non-terminal) sessions across every agent owned by this team, newest activity first.",
    )
    @action(detail=False, methods=["get"], url_path="live_sessions")
    def live_sessions(self, request: Request, **kwargs) -> Response:
        limit_param = request.query_params.get("limit")
        try:
            limit = int(limit_param) if limit_param is not None else None
        except ValueError:
            raise ValidationError("limit must be an integer")
        try:
            payload = _janitor().list_live_for_team(int(self.team_id), limit=limit)
        except JanitorClientError as e:
            raise JanitorUpstreamError(e) from e
        return Response(payload)


# Suppress unused-import warning for the type re-export below.
_ = EncryptedTextField
