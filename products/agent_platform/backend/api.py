"""
DRF viewsets for agent_platform — the authoring surface.

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

from django.db import transaction
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
from .registry_freeze import FreezeError, freeze_templates_into_bundle
from .serializers import (
    AgentApplicationSerializer,
    AgentRevisionSerializer,
    CloneFromRequestSerializer,
    DecideApprovalRequestSerializer,
    NewDraftRevisionRequestSerializer,
    PromoteRevisionRequestSerializer,
    SetEnvKeyRequestSerializer,
    SetEnvRequestSerializer,
    WriteBundleRequestSerializer,
    WriteFileRequestSerializer,
)
from .spec_schema import missing_required_secrets

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
        # Flatten the body to a string. exceptions_hog's `_get_detail` walks
        # `dict` details via `exception_key` and falls through to `value[0]`
        # otherwise — passing a dict here raises `KeyError: 0` at render time.
        # Prefer common janitor error fields; otherwise JSON-dump so callers
        # still see the upstream payload.
        if isinstance(e.body, dict):
            msg = e.body.get("error") or e.body.get("detail") or e.body.get("message")
            detail_str: str = msg if isinstance(msg, str) else json.dumps(e.body)
        elif isinstance(e.body, str):
            detail_str = e.body
        else:
            detail_str = e.message
        super().__init__(detail=detail_str)


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


@extend_schema(tags=["agent_platform"])
class AgentApplicationViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    """Agent applications — the deployable unit of the platform.

    URLs:
        GET    /api/projects/<team>/agent_applications/             list
        POST   /api/projects/<team>/agent_applications/             create
        GET    /api/projects/<team>/agent_applications/<id|slug>/   retrieve
        PATCH  /api/projects/<team>/agent_applications/<id|slug>/   update
        DELETE /api/projects/<team>/agent_applications/<id|slug>/   archive
        POST   /api/projects/<team>/agent_applications/<id|slug>/set_env/        bulk replace env
        GET    /api/projects/<team>/agent_applications/<id|slug>/env_keys/        list set keys
        GET    /api/projects/<team>/agent_applications/<id|slug>/env_keys/<KEY>/  is one key set?
        PUT    /api/projects/<team>/agent_applications/<id|slug>/env_keys/<KEY>/  set one key
        DELETE /api/projects/<team>/agent_applications/<id|slug>/env_keys/<KEY>/  clear one key
    """

    scope_object = "agents"
    scope_object_write_actions = [
        "create",
        "update",
        "partial_update",
        "destroy",
        "set_env",
        # env_keys_key handles GET/PUT/DELETE on /env_keys/<KEY>/ — bundled
        # under :write because PUT/DELETE are the load-bearing ops and we
        # don't want the scope to drift between methods.
        "env_keys_key",
        "approvals_decide",
    ]
    scope_object_read_actions = [
        "list",
        "retrieve",
        "sessions_list",
        "sessions_retrieve",
        "session_logs",
        "stats",
        "env_keys_list",
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

    # ── Per-key env management ───────────────────────────────────────
    # Set-replace via `set_env` is fine for bulk sync (CI pushes the
    # whole env file) but useless for a "set one secret" UI: the caller
    # can't read existing values out, so they'd wipe the rest on every
    # save. The four routes below let the UI (and the concierge agent's
    # client tool) inspect + mutate one key at a time without ever
    # exposing decrypted values across the wire.

    @staticmethod
    def _load_env_map(application: AgentApplication) -> dict[str, str]:
        """Decode the encrypted env JSON into a `{KEY: value}` map.

        Tolerates empty / null / corrupt blocks by returning `{}` — the
        worker treats those as "no env set" too.
        """
        raw = application.encrypted_env or ""
        if not raw:
            return {}
        try:
            parsed = json.loads(raw)
        except (TypeError, ValueError):
            return {}
        if not isinstance(parsed, dict):
            return {}
        return {str(k): str(v) for k, v in parsed.items()}

    _ENV_KEY_NAME = OpenApiParameter(
        "key",
        OpenApiTypes.STR,
        OpenApiParameter.PATH,
        required=True,
        description="The env variable name. Conventionally UPPER_SNAKE_CASE; the API does not enforce a shape.",
    )

    @extend_schema(
        operation_id="agent_applications_env_keys_list",
        request=None,
        responses=OpenApiResponse(
            response=inline_serializer(
                name="AgentApplicationEnvKeysResponse",
                fields={
                    "keys": drf_serializers.ListField(
                        child=drf_serializers.CharField(),
                        help_text="Names of env variables currently set on the application. Values are never returned.",
                    ),
                },
            ),
        ),
    )
    @action(detail=True, methods=["get"], url_path="env_keys")
    def env_keys_list(self, request: Request, **kwargs) -> Response:
        """List the names of secrets currently set on the application.

        Returns names only — values stay server-side under
        `EncryptedTextField`. Use this to drive the "set / unset" badge
        next to a declared secret in the editor UI.
        """
        application = self.get_object()
        if application is None:
            raise NotFound("Application not found")
        env_map = self._load_env_map(application)
        # Sort for stable UI ordering; the encrypted JSON has no
        # meaningful order of its own.
        return Response({"keys": sorted(env_map.keys())})

    # One inline status serializer reused by all three method schemas so
    # drf-spectacular emits a single named component instead of three
    # near-identical ones.
    _ENV_KEY_STATUS_RESPONSE = OpenApiResponse(
        response=inline_serializer(
            name="AgentApplicationEnvKeyStatus",
            fields={
                "key": drf_serializers.CharField(),
                "is_set": drf_serializers.BooleanField(
                    help_text="True if the key is present in the env block. The value itself is never returned.",
                ),
            },
        ),
    )

    @extend_schema(
        methods=["GET"],
        operation_id="agent_applications_env_keys_get",
        parameters=[_ENV_KEY_NAME],
        request=None,
        responses=_ENV_KEY_STATUS_RESPONSE,
    )
    @extend_schema(
        methods=["PUT"],
        operation_id="agent_applications_env_keys_set",
        parameters=[_ENV_KEY_NAME],
        request=SetEnvKeyRequestSerializer,
        responses=_ENV_KEY_STATUS_RESPONSE,
    )
    @extend_schema(
        methods=["DELETE"],
        operation_id="agent_applications_env_keys_clear",
        parameters=[_ENV_KEY_NAME],
        request=None,
        responses=_ENV_KEY_STATUS_RESPONSE,
    )
    @action(detail=True, methods=["get", "put", "delete"], url_path="env_keys/(?P<key>[^/.]+)")
    def env_keys_key(self, request: Request, key: str, **kwargs) -> Response:
        """GET / PUT / DELETE one secret by name.

        - `GET`    → `{ key, is_set }` (never returns the value).
        - `PUT`    → upserts `{ value }` into the env block.
        - `DELETE` → removes the key. No-op when it wasn't set.

        Per-method scope: GET is treated as a write action so the
        single action name maps to one consistent scope; reading whether
        a secret is set is restricted to writers in any case.
        """
        application = self.get_object()
        if application is None:
            raise NotFound("Application not found")
        env_map = self._load_env_map(application)

        if request.method == "GET":
            return Response({"key": key, "is_set": key in env_map})

        if request.method == "DELETE":
            env_map.pop(key, None)
            application.encrypted_env = json.dumps(env_map)
            application.save(update_fields=["encrypted_env", "updated_at"])
            return Response({"key": key, "is_set": False})

        # PUT
        body = SetEnvKeyRequestSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        env_map[key] = body.validated_data["value"]
        application.encrypted_env = json.dumps(env_map)
        application.save(update_fields=["encrypted_env", "updated_at"])
        return Response({"key": key, "is_set": True})

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
        Auth: standard PAT / session — `agents:read` scope.
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
                                "trigger_metadata": drf_serializers.DictField(
                                    allow_null=True,
                                    required=False,
                                    help_text=(
                                        "Trigger-specific metadata stamped at session creation. Shape varies "
                                        "by trigger kind; cron firings carry "
                                        "`{ kind: 'cron', cron_name, schedule, fired_at, manual? }`. "
                                        "Render this on session-detail so the operator can tell at a glance "
                                        "that a session was fired by which cron / when."
                                    ),
                                ),
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
                    "trigger_metadata": drf_serializers.DictField(
                        allow_null=True,
                        required=False,
                        help_text=(
                            "Trigger-specific metadata stamped at session creation. Shape varies "
                            "by trigger kind; cron firings carry "
                            "`{ kind: 'cron', cron_name, schedule, fired_at, manual? }`. "
                            "Render this on session-detail so the operator can tell at a glance "
                            "that a session was fired by which cron / when."
                        ),
                    ),
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
    # AGENT_DB is node-owned (per CLAUDE.md rule #2 in products/agent_platform).
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


@extend_schema(tags=["agent_platform"])
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

    scope_object = "agents"  # share the parent's scope
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
        "cron_fire",
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

        # Trigger types declare the secrets they need via
        # `TRIGGER_REQUIRED_SECRETS` (see spec_schema.py). Each required key
        # must be set in `application.encrypted_env` before promote, otherwise
        # the ingress would 500 on the first inbound webhook for the trigger.
        # Per-key gate, not per-trigger — multiple triggers can share a key.
        env_map = AgentApplicationViewSet._load_env_map(application)
        missing = missing_required_secrets(revision.spec or {}, env_map)
        if missing:
            details = ", ".join(f"{m['key']} (for {m['trigger']} trigger)" for m in missing)
            raise ValidationError(
                f"Cannot promote: agent is missing required encrypted_env entries: {details}. "
                f"Set the value(s) via the env editor then retry."
            )

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
        request=inline_serializer(
            name="AgentRevisionCronFireRequest",
            fields={
                "cron_name": drf_serializers.CharField(
                    help_text="`name` of the cron trigger in `spec.triggers[]` to fire.",
                ),
                "request_id": drf_serializers.CharField(
                    required=False,
                    allow_null=True,
                    help_text=(
                        "Stable client-supplied id so repeated clicks of the same UI 'Fire now' "
                        "button resolve to the same session id rather than firing twice. The "
                        "janitor keys dedupe off `cron-manual:<rev>:<name>:<request_id>`. Omit "
                        "to fire unconditionally — every call generates a fresh UUID."
                    ),
                ),
            },
        ),
        responses=OpenApiResponse(
            response=inline_serializer(
                name="AgentRevisionCronFireResponse",
                fields={
                    "ok": drf_serializers.BooleanField(),
                    "session_id": drf_serializers.UUIDField(
                        help_text="ID of the session the cron firing created (or returned, on dedupe).",
                    ),
                    "fired_at": drf_serializers.CharField(
                        help_text="ISO-8601 timestamp the firing was attributed to.",
                    ),
                    "idempotency_key": drf_serializers.CharField(
                        help_text=(
                            "Composed dedupe key — `cron-manual:<rev>:<name>:<request_id>`. "
                            "Returned so the UI can correlate."
                        ),
                    ),
                    "request_id": drf_serializers.CharField(
                        help_text="The request id the firing used (echoed back, or freshly minted).",
                    ),
                },
            ),
            description="Cron job was fired (or deduped to an existing session).",
        ),
    )
    @action(detail=True, methods=["post"], url_path="cron/fire")
    def cron_fire(self, request: Request, **kwargs) -> Response:
        """Fire one cron job out-of-band — the same execution path the
        scheduler walks, but on demand. Authoring UX: the user iterates on
        a cron prompt by clicking 'Fire now' rather than waiting for the
        next scheduled firing. Without this, 'did my prompt do the right
        thing?' is unanswerable until the cron actually fires.

        Idempotent via `request_id`: repeat clicks with the same id resolve
        to the same session id rather than firing N times. See
        `docs/agent-platform/plans/cron-trigger-scheduler.md` §9.
        """
        revision: AgentRevision = self.get_object()
        cron_name = request.data.get("cron_name")
        if not isinstance(cron_name, str) or not cron_name:
            raise ValidationError({"cron_name": "required"})
        request_id_raw = request.data.get("request_id")
        request_id = request_id_raw if isinstance(request_id_raw, str) and request_id_raw else None
        return Response(self._call(_janitor().cron_fire, str(revision.id), cron_name=cron_name, request_id=request_id))

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

        Single atomic block now that the janitor's freeze endpoint is
        side-effect-free w.r.t. `agent_revision`: (1) resolve
        `spec.skills[].from_template` / `spec.tools[].from_template` refs
        into the bundle (copies content, stamps versions, inserts join
        rows); (2) call the janitor to compute the bundle sha (writes the
        S3 `.frozen` marker, returns the sha); (3) stamp `state='ready'`
        + `bundle_sha256` on the revision row from Django. Django is the
        sole writer to `agent_revision.state`, so there's no cross-process
        row contention on the same row to deadlock against. Any failure
        leaves the revision in `draft`; the next freeze re-runs all three
        phases idempotently.
        """
        revision: AgentRevision = self.get_object()
        janitor_client = _janitor()
        try:
            with transaction.atomic():
                freeze_templates_into_bundle(revision, janitor_client, team_id=self.team_id)
                result = self._call(janitor_client.freeze, str(revision.id))
                revision.state = "ready"
                revision.bundle_sha256 = result["bundle_sha256"]
                revision.save(update_fields=["state", "bundle_sha256"])
        except FreezeError as e:
            err = ValidationError(e.message)
            err.extra = {"kind": e.kind, "index": e.index}  # type: ignore[attr-defined]
            raise err from e
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


_MEMORY_HEADER_FIELDS = {
    "path": drf_serializers.CharField(help_text="Relative path within the agent's memory, e.g. 'incidents/db.md'."),
    "description": drf_serializers.CharField(help_text="One-line summary from the file's frontmatter."),
    "tags": drf_serializers.ListField(
        child=drf_serializers.CharField(),
        help_text="Frontmatter tags (lowercase a-z 0-9 _ - only).",
    ),
    "created_at": drf_serializers.CharField(
        allow_null=True,
        help_text="ISO-8601 timestamp stamped on create. Null for files written before this field was introduced.",
    ),
    "updated_at": drf_serializers.CharField(
        allow_null=True,
        help_text="ISO-8601 timestamp stamped on every write.",
    ),
}

_MEMORY_LIST_RESPONSE = inline_serializer(
    name="AgentMemoryListResponse",
    fields={
        "count": drf_serializers.IntegerField(help_text="Number of entries returned."),
        "entries": drf_serializers.ListField(
            child=inline_serializer(name="AgentMemoryHeader", fields=_MEMORY_HEADER_FIELDS),
            help_text="Headers (frontmatter only) — no file bodies. Use the read endpoint for the body.",
        ),
    },
)

_MEMORY_FILE_RESPONSE = inline_serializer(
    name="AgentMemoryFile",
    fields={
        **_MEMORY_HEADER_FIELDS,
        "content": drf_serializers.CharField(help_text="Full markdown body."),
    },
)

_AGENT_TABLES_LIST_RESPONSE = inline_serializer(
    name="AgentTablesListResponse",
    fields={
        "count": drf_serializers.IntegerField(help_text="Number of tables."),
        "tables": drf_serializers.ListField(
            child=inline_serializer(
                name="AgentTableHeader",
                fields={
                    "name": drf_serializers.CharField(help_text="Table name."),
                    "size": drf_serializers.IntegerField(help_text="Object size in bytes."),
                },
            ),
            help_text="Tabular-reference tables for this agent (the @posthog/table-* JSONL tables).",
        ),
    },
)

_AGENT_TABLE_ROWS_RESPONSE = inline_serializer(
    name="AgentTableRowsResponse",
    fields={
        "name": drf_serializers.CharField(),
        "total": drf_serializers.IntegerField(help_text="Total rows in the table."),
        "returned": drf_serializers.IntegerField(help_text="Rows in this response (capped by limit)."),
        "limit": drf_serializers.IntegerField(),
        "rows": drf_serializers.ListField(
            child=drf_serializers.DictField(),
            help_text="The rows (arbitrary JSON objects).",
        ),
    },
)

_MEMORY_TREE_RESPONSE = inline_serializer(
    name="AgentMemoryTreeResponse",
    fields={
        # Tree shape is recursive; declared loosely so OpenAPI doesn't need a
        # self-reference. The frontend types use a hand-typed shape.
        "root": drf_serializers.DictField(
            help_text="Folder tree rooted at the agent's memory prefix. Each node is "
            "{name, type: 'folder'|'file', path?, description?, tags?, children?}.",
        ),
    },
)

_MEMORY_SEARCH_RESULT = inline_serializer(
    name="AgentMemorySearchResult",
    fields={
        "path": drf_serializers.CharField(),
        "description": drf_serializers.CharField(),
        "tags": drf_serializers.ListField(child=drf_serializers.CharField()),
        "score": drf_serializers.FloatField(help_text="BM25 relevance score."),
        "snippet": drf_serializers.CharField(
            allow_null=True,
            help_text="Body snippet around the earliest match. Null when only the header matched.",
        ),
    },
)

_MEMORY_SEARCH_RESPONSE = inline_serializer(
    name="AgentMemorySearchResponse",
    fields={
        "cue": drf_serializers.CharField(help_text="The original search cue, echoed back."),
        "count": drf_serializers.IntegerField(),
        "results": drf_serializers.ListField(child=_MEMORY_SEARCH_RESULT),
    },
)


class AgentMemoryWriteRequest(drf_serializers.Serializer):
    """Body shape for AgentMemoryViewSet.write_file (create)."""

    path = drf_serializers.CharField(
        help_text="Where to store the file. Lowercase a-z 0-9 _ - / only, must end in .md."
    )
    description = drf_serializers.CharField(
        max_length=280,
        help_text="One-line summary, max 280 chars. Surfaces in list/search results.",
    )
    content = drf_serializers.CharField(help_text="Full markdown body.")
    tags = drf_serializers.ListField(
        child=drf_serializers.CharField(),
        required=False,
        help_text="Optional flat tags for search ranking. Lowercase a-z 0-9 _ - only.",
    )


class AgentMemoryUpdateRequest(drf_serializers.Serializer):
    """Body shape for AgentMemoryViewSet.update_file. Omitted fields preserve the existing value."""

    description = drf_serializers.CharField(max_length=280, required=False)
    content = drf_serializers.CharField(required=False)
    tags = drf_serializers.ListField(child=drf_serializers.CharField(), required=False)


@extend_schema(tags=["agent_platform"])
class AgentMemoryViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    """S3-backed memory files for a single agent (application).

    URLs (nested under an application):

        GET    .../memory/files/                          list headers under the agent's prefix (?prefix=…)
        GET    .../memory/tree/                           pre-aggregated folder tree
        GET    .../memory/files/by_path/?path=…           read one file in full
        POST   .../memory/files/                          create — body {path, description, content, tags?}
        PATCH  .../memory/files/by_path/?path=…           update fields on an existing file
        DELETE .../memory/files/by_path/?path=…           hard delete
        GET    .../memory/search/?q=…                     BM25 search across files

    Every endpoint proxies the janitor, which owns the S3MemoryStore. The
    runner writes the same bucket directly via `@posthog/memory-*` tools —
    one bucket, two callers, one source-of-truth code path.

    Activity logging: create/update/delete log under scope='AgentApplication'
    so memory edits surface in the agent's audit trail.
    """

    scope_object = "agents"  # share the parent's scope
    scope_object_read_actions = ["list_files", "tree", "get_file", "search", "tables", "table_rows"]
    scope_object_write_actions = ["create_file", "update_file", "delete_file"]
    # The parent URL kwarg is `application_id`; we override resolution to
    # accept slug-or-UUID via _resolve_application.
    filter_rewrite_rules: dict[str, str] = {}

    def _get_application(self) -> AgentApplication:
        app = _resolve_application(
            AgentApplication.objects.filter(team_id=self.team_id, archived=False),
            self.kwargs.get("parent_lookup_application_id") or self.kwargs.get("application_id"),
        )
        if app is None:
            raise NotFound("Application not found")
        # This is a plain ViewSet, so it bypasses the mixin's get_object() and
        # the object-level RBAC it runs. Enforce per-application access control
        # explicitly (mirrors TeamAndOrgViewSetMixin.get_object) — otherwise a
        # user with team access but no access to THIS application could read its
        # memory files / tables by guessing the slug or UUID.
        self.check_object_permissions(self.request, app)
        return app

    def _log_memory_change(
        self, application: AgentApplication, activity: str, path: str, extra: dict[str, Any]
    ) -> None:
        # Local import — activity_log isn't on the hot path and avoids a top-level
        # circular import with posthog.models in some test paths.
        from posthog.models.activity_logging.activity_log import Detail, log_activity  # noqa: PLC0415

        log_activity(
            organization_id=application.team.organization_id,
            team_id=application.team_id,
            user=self.request.user,
            was_impersonated=getattr(self.request, "user_is_impersonated", False),
            item_id=application.id,
            scope="AgentApplication",
            activity=activity,
            detail=Detail(
                name=application.slug,
                short_id=None,
                changes=None,
                trigger=None,
                type=None,
                context={"memory_path": path, **extra},
            ),
        )

    # ── list / tree ────────────────────────────────────────────────────────

    @extend_schema(
        operation_id="agent_memory_list_files",
        parameters=[
            OpenApiParameter(
                "prefix",
                OpenApiTypes.STR,
                OpenApiParameter.QUERY,
                required=False,
                description="Optional path prefix to scope the list, e.g. 'incidents/'.",
            ),
        ],
        request=None,
        responses=OpenApiResponse(response=_MEMORY_LIST_RESPONSE),
        description="List memory file headers under the agent's prefix. Headers only — no bodies.",
    )
    @action(detail=False, methods=["get"], url_path="files")
    def list_files(self, request: Request, **kwargs) -> Response:
        application = self._get_application()
        try:
            payload = _janitor().list_memory_files(
                int(self.team_id),
                str(application.id),
                prefix=request.query_params.get("prefix") or None,
            )
        except JanitorClientError as e:
            raise JanitorUpstreamError(e) from e
        return Response(payload)

    @extend_schema(
        operation_id="agent_memory_list_tables",
        request=None,
        responses=OpenApiResponse(response=_AGENT_TABLES_LIST_RESPONSE),
        description="List the agent's tabular-reference tables (the @posthog/table-* JSONL tables): name + byte size.",
    )
    @action(detail=False, methods=["get"], url_path="tables")
    def tables(self, request: Request, **kwargs) -> Response:
        application = self._get_application()
        try:
            payload = _janitor().list_tables(int(self.team_id), str(application.id))
        except JanitorClientError as e:
            raise JanitorUpstreamError(e) from e
        return Response(payload)

    @extend_schema(
        operation_id="agent_memory_read_table",
        parameters=[
            OpenApiParameter(
                "limit",
                OpenApiTypes.INT,
                OpenApiParameter.QUERY,
                required=False,
                description="Max rows to return (default 500, max 5000).",
            ),
        ],
        request=None,
        responses=OpenApiResponse(response=_AGENT_TABLE_ROWS_RESPONSE),
        description="Read rows from one tabular-reference table (capped via ?limit).",
    )
    @action(detail=False, methods=["get"], url_path="tables/(?P<name>[^/]+)")
    def table_rows(self, request: Request, name: str | None = None, **kwargs) -> Response:
        application = self._get_application()
        limit_raw = request.query_params.get("limit")
        limit: int | None = None
        if limit_raw:
            try:
                limit = int(limit_raw)
            except ValueError:
                raise ValidationError("limit must be an integer")
        try:
            payload = _janitor().read_table(int(self.team_id), str(application.id), str(name), limit=limit)
        except JanitorClientError as e:
            raise JanitorUpstreamError(e) from e
        return Response(payload)

    @extend_schema(
        operation_id="agent_memory_tree",
        request=None,
        responses=OpenApiResponse(response=_MEMORY_TREE_RESPONSE),
        description="Pre-aggregated folder tree of memory files. Saves the frontend re-derivation work.",
    )
    @action(detail=False, methods=["get"], url_path="tree")
    def tree(self, request: Request, **kwargs) -> Response:
        application = self._get_application()
        try:
            payload = _janitor().get_memory_tree(int(self.team_id), str(application.id))
        except JanitorClientError as e:
            raise JanitorUpstreamError(e) from e
        return Response(payload)

    # ── read / write / delete one file ─────────────────────────────────────

    @extend_schema(
        operation_id="agent_memory_get_file",
        parameters=[
            OpenApiParameter(
                "path",
                OpenApiTypes.STR,
                OpenApiParameter.QUERY,
                required=True,
                description="Memory path returned by the list endpoint, e.g. 'incidents/db.md'.",
            ),
        ],
        request=None,
        responses=OpenApiResponse(response=_MEMORY_FILE_RESPONSE),
        description="Read one memory file in full (frontmatter + markdown body).",
    )
    @action(detail=False, methods=["get"], url_path="files/by_path")
    def get_file(self, request: Request, **kwargs) -> Response:
        path = request.query_params.get("path")
        if not path:
            raise ValidationError("missing required query param: path")
        application = self._get_application()
        try:
            payload = _janitor().read_memory_file(int(self.team_id), str(application.id), path)
        except JanitorClientError as e:
            raise JanitorUpstreamError(e) from e
        return Response(payload)

    @extend_schema(
        operation_id="agent_memory_create_file",
        request=AgentMemoryWriteRequest,
        responses=OpenApiResponse(response=_MEMORY_FILE_RESPONSE),
        description="Create a memory file. Fails if the path already exists — use the update endpoint to overwrite.",
    )
    # Chained off `list_files` via `@list_files.mapping.post` rather than its
    # own `@action(url_path="files")` — DRF only registers one action per
    # url_path, so two separate decorators leave the loser unrouted
    # (the symptom is `405 Method Not Allowed: Allow: <whatever-loser>`).
    @list_files.mapping.post
    def create_file(self, request: Request, **kwargs) -> Response:
        serializer = AgentMemoryWriteRequest(data=request.data)
        serializer.is_valid(raise_exception=True)
        body = serializer.validated_data
        application = self._get_application()
        try:
            payload = _janitor().write_memory_file(
                int(self.team_id),
                str(application.id),
                path=body["path"],
                description=body["description"],
                content=body["content"],
                tags=body.get("tags"),
            )
        except JanitorClientError as e:
            raise JanitorUpstreamError(e) from e
        self._log_memory_change(
            application,
            activity="memory_file_created",
            path=body["path"],
            extra={"description": body["description"], "tags": body.get("tags") or []},
        )
        return Response(payload, status=status.HTTP_201_CREATED)

    @extend_schema(
        operation_id="agent_memory_update_file",
        parameters=[
            OpenApiParameter(
                "path",
                OpenApiTypes.STR,
                OpenApiParameter.QUERY,
                required=True,
                description="Memory path to update.",
            ),
        ],
        request=AgentMemoryUpdateRequest,
        responses=OpenApiResponse(response=_MEMORY_FILE_RESPONSE),
        description="Update a memory file. Any field omitted is preserved from the existing file.",
    )
    # Chained off `get_file` — see comment on `create_file` above.
    @get_file.mapping.patch
    def update_file(self, request: Request, **kwargs) -> Response:
        path = request.query_params.get("path")
        if not path:
            raise ValidationError("missing required query param: path")
        serializer = AgentMemoryUpdateRequest(data=request.data)
        serializer.is_valid(raise_exception=True)
        body = serializer.validated_data
        application = self._get_application()
        try:
            payload = _janitor().update_memory_file(
                int(self.team_id),
                str(application.id),
                path,
                description=body.get("description"),
                content=body.get("content"),
                tags=body.get("tags"),
            )
        except JanitorClientError as e:
            raise JanitorUpstreamError(e) from e
        self._log_memory_change(
            application,
            activity="memory_file_updated",
            path=path,
            extra=dict(body.items()),
        )
        return Response(payload)

    @extend_schema(
        operation_id="agent_memory_delete_file",
        parameters=[
            OpenApiParameter(
                "path",
                OpenApiTypes.STR,
                OpenApiParameter.QUERY,
                required=True,
                description="Memory path to delete.",
            ),
        ],
        request=None,
        responses=OpenApiResponse(
            response=inline_serializer(
                name="AgentMemoryDeleteResponse",
                fields={
                    "path": drf_serializers.CharField(),
                    "deleted": drf_serializers.BooleanField(),
                },
            ),
        ),
        description="Hard-delete a memory file. Activity log captures the action against the agent.",
    )
    # Chained off `get_file` — see comment on `create_file` above.
    @get_file.mapping.delete
    def delete_file(self, request: Request, **kwargs) -> Response:
        path = request.query_params.get("path")
        if not path:
            raise ValidationError("missing required query param: path")
        application = self._get_application()
        try:
            payload = _janitor().delete_memory_file(int(self.team_id), str(application.id), path)
        except JanitorClientError as e:
            raise JanitorUpstreamError(e) from e
        self._log_memory_change(application, activity="memory_file_deleted", path=path, extra={})
        return Response(payload)

    # ── search ─────────────────────────────────────────────────────────────

    @extend_schema(
        operation_id="agent_memory_search",
        parameters=[
            OpenApiParameter(
                "q",
                OpenApiTypes.STR,
                OpenApiParameter.QUERY,
                required=True,
                description="Search cue — plain natural language is fine.",
            ),
            OpenApiParameter(
                "prefix",
                OpenApiTypes.STR,
                OpenApiParameter.QUERY,
                required=False,
                description="Optional path prefix to scope the search.",
            ),
            OpenApiParameter(
                "limit",
                OpenApiTypes.INT,
                OpenApiParameter.QUERY,
                required=False,
                description="Max results (default 10, max 100).",
            ),
        ],
        request=None,
        responses=OpenApiResponse(response=_MEMORY_SEARCH_RESPONSE),
        description="BM25 search across the agent's memory files. Ranks by description+tags+path+body with field weighting.",
    )
    @action(detail=False, methods=["get"], url_path="search")
    def search(self, request: Request, **kwargs) -> Response:
        q = request.query_params.get("q")
        if not q:
            raise ValidationError("missing required query param: q")
        prefix = request.query_params.get("prefix") or None
        limit_param = request.query_params.get("limit")
        try:
            limit = int(limit_param) if limit_param is not None else None
        except ValueError:
            raise ValidationError("limit must be an integer")
        application = self._get_application()
        try:
            payload = _janitor().search_memory(
                int(self.team_id),
                str(application.id),
                q=q,
                prefix=prefix,
                limit=limit,
            )
        except JanitorClientError as e:
            raise JanitorUpstreamError(e) from e
        return Response(payload)


@extend_schema(tags=["agent_platform"])
class AgentNativeToolsViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    """Read-only catalog of every `@posthog/*` native tool the runner knows.

    URLs:
        GET /api/projects/<team>/agent_native_tools/    — list

    Backed by the janitor (which imports `listNativeTools()` from
    `@posthog/agent-tools`). Keeps a single source of truth for what tools
    exist — agents can't put unknown tool ids in their spec, and the MCP /
    wizard show this list to humans + models when picking what to wire up.
    """

    scope_object = "agents"
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


@extend_schema(tags=["agent_platform"])
class AgentFleetViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    """Team-wide agent fleet rollups.

    URLs:
        GET /api/projects/<team>/agent_fleet/stats/           — aggregate counts + spend across every agent in the team
        GET /api/projects/<team>/agent_fleet/live_sessions/   — live sessions for every agent in the team

    Both endpoints proxy the janitor (which owns the runtime DB). Used by
    the agent-console "fleet" overview to render the cards on the agents
    list without per-agent N+1.
    """

    scope_object = "agents"
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
                                "trigger_metadata": drf_serializers.DictField(
                                    allow_null=True,
                                    required=False,
                                    help_text=(
                                        "Trigger-specific metadata stamped at session creation. Shape varies "
                                        "by trigger kind; cron firings carry "
                                        "`{ kind: 'cron', cron_name, schedule, fired_at, manual? }`. "
                                        "Render this on session-detail so the operator can tell at a glance "
                                        "that a session was fired by which cron / when."
                                    ),
                                ),
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
