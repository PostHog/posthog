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
import re
import json
import logging
from collections.abc import AsyncIterator, Callable
from datetime import timedelta
from functools import cached_property
from typing import Any, cast
from urllib.parse import urlencode
from uuid import UUID

from django.conf import settings
from django.db import transaction
from django.db.models import QuerySet
from django.http import StreamingHttpResponse
from django.utils import timezone

import requests
from asgiref.sync import sync_to_async
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
from posthog.api.streaming import streaming_response
from posthog.auth import OAuthAccessTokenAuthentication, SessionAuthentication
from posthog.clickhouse.query_tagging import Feature, tag_queries
from posthog.helpers.encrypted_fields import EncryptedTextField
from posthog.models.organization import OrganizationMembership
from posthog.models.user import User
from posthog.permissions import get_authenticator_scopes
from posthog.security.outbound_proxy import internal_requests

from ..db import WRITER_DB
from ..logic.internal_jwt import AgentInternalAudience, encode_agent_internal_jwt
from ..logic.janitor_client import JanitorClient, JanitorClientError, default_client
from ..logic.kernel_skills import all_kernel_skill_ids, kernel_skills_for
from ..logic.posthog_identity_app import provision_posthog_identity_apps
from ..logic.skill_editing import (
    LLMSkill,
    assert_skills_writable,
    create_store_skill,
    publish_skill_body,
    publish_skill_md_edit,
    store_skill_exists,
    validate_store_write,
)
from ..logic.skill_resolution import assert_skill_refs_readable, resolve_skill_ref, stamp_skill_provenance
from ..logic.spec_schema import missing_required_secrets
from ..models import AgentApplication, AgentIdentityCredential, AgentRevision
from .serializers import (
    MAX_SKILL_REFS,
    AgentApplicationSerializer,
    AgentRevisionSerializer,
    CloneFromRequestSerializer,
    DecideApprovalRequestSerializer,
    DryRunToolRequestSerializer,
    ImportBundleRequestSerializer,
    NewDraftRevisionRequestSerializer,
    PreviewProxyInvokeRequestSerializer,
    PromoteRevisionRequestSerializer,
    RevisionNotDraftErrorSerializer,
    SetEnvKeyRequestSerializer,
    SetEnvRequestSerializer,
    SetSkillRefsRequestSerializer,
    UpdateBundleFileRequestSerializer,
    WriteAgentMdRequestSerializer,
    WriteSpecRequestSerializer,
    WriteToolRequestSerializer,
    WriteTypedBundleRequestSerializer,
    agent_ingress_route_url,
)

logger = logging.getLogger(__name__)


def _resolve_application(queryset: QuerySet, lookup_value: str | None) -> AgentApplication | None:
    """Look up by UUID if the URL value parses as one, otherwise by slug.

    Lets API consumers reference an application either by its stable id or by
    the human-readable slug — both are unique within a team.
    """
    if lookup_value is None:
        return None
    try:
        UUID(str(lookup_value))
        field = "pk"
    except (ValueError, TypeError):
        field = "slug"
    return queryset.filter(**{field: lookup_value}).first()


def _janitor() -> JanitorClient:
    """Indirection so tests can monkey-patch."""
    return default_client()


# Mirrors `RESOURCE_ID_REGEX` in
# services/agent-shared/src/storage/typed-bundle.ts. The janitor enforces this
# regex on every PUT /skills/<id>; pre-checking on the Django side turns a
# noisy janitor 400 into a clean reject before we make any upstream calls,
# and is cheap. Keep these two in sync (per agent-shared CLAUDE.md rule 3).
# Also classifies `skills/<id>/` folders in the freeze sweep, keeping Django's
# sweep set identical to the set the janitor derives as skills.
# Always use `.fullmatch()`: Python's `$` matches before a trailing newline
# (JS's `$` does not), so `.match()` would accept `"abc\n"` and mint a store
# skill + ref alias the janitor later rejects at freeze.
_RESOURCE_ID_REGEX = re.compile(r"[a-z0-9](?:[a-z0-9_-]*[a-z0-9])?")
# Canonical bundle path for one skill's markdown body. Same fullmatch rule.
_SKILL_BODY_PATH_REGEX = re.compile(r"skills/([a-z0-9](?:[a-z0-9_-]*[a-z0-9])?)/SKILL\.md")


def _decode_env_map(raw: str | None) -> dict[str, str]:
    """Decode a decrypted `encrypted_env` JSON blob into a `{KEY: value}` map.

    Tolerates empty / null / corrupt blocks by returning `{}` — the worker
    treats those as "no env set" too. Secrets live on the revision, so callers
    pass `revision.encrypted_env` (decrypted by `EncryptedTextField` on read).
    """
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    if not isinstance(parsed, dict):
        return {}
    return {str(k): str(v) for k, v in parsed.items()}


class JanitorUpstreamError(APIException):
    """DRF-friendly wrapper for non-2xx janitor responses. We forward the
    status code where it makes sense (404 stays 404, 409 stays 409) and
    surface the janitor's body as the API response."""

    status_code: int = status.HTTP_502_BAD_GATEWAY
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
            # Append structured upstream errors so the caller + concierge model
            # see the concrete reason, not just the opaque code. Two shapes:
            # custom-tool compile -> top-level errors=[{kind, message, line}];
            # freeze/validate -> report.errors=[{code, message, pointer}] (e.g.
            # invalid_model from the models gate).
            sub_errors = e.body.get("errors")
            if not sub_errors:
                report = e.body.get("report")
                sub_errors = report.get("errors") if isinstance(report, dict) else None
            if isinstance(sub_errors, list) and sub_errors:
                parts: list[str] = []
                for er in sub_errors:
                    if not isinstance(er, dict) or not isinstance(er.get("message"), str):
                        continue
                    kind = er.get("kind") or er.get("code")
                    line = er.get("line")
                    pointer = er.get("pointer")
                    prefix = f"{kind}: " if isinstance(kind, str) else ""
                    suffix = (
                        f" (line {line})"
                        if isinstance(line, int)
                        else f" [{pointer}]"
                        if isinstance(pointer, str)
                        else ""
                    )
                    parts.append(f"{prefix}{er['message']}{suffix}")
                if parts:
                    joined = "; ".join(parts)
                    msg = f"{msg}: {joined}" if isinstance(msg, str) else joined
            # Zod-validation rejects (typed-bundle PUTs: spec/agent_md/skill_refs/
            # tools) -> issues=[{message, path:[...]}] with `error=invalid_request`.
            # Surface `message [path]` so the caller sees the offending field, not
            # just the opaque code.
            issues = e.body.get("issues")
            if isinstance(issues, list) and issues:
                issue_parts: list[str] = []
                for iss in issues:
                    if not isinstance(iss, dict) or not isinstance(iss.get("message"), str):
                        continue
                    path = iss.get("path")
                    loc = ".".join(str(p) for p in path) if isinstance(path, list) and path else ""
                    issue_parts.append(f"{iss['message']} [{loc}]" if loc else iss["message"])
                if issue_parts:
                    joined = "; ".join(issue_parts)
                    msg = f"{msg}: {joined}" if isinstance(msg, str) else joined
            detail_str: str = msg if isinstance(msg, str) else json.dumps(e.body)
        elif isinstance(e.body, str):
            detail_str = e.body
        else:
            detail_str = e.message
        super().__init__(detail=detail_str)


def _is_sealed_bundle_conflict(e: JanitorClientError) -> bool:
    """True when a janitor edit was refused because the bundle is already sealed.

    The janitor returns 409 `revision_not_draft` from any authoring edit once the
    `.frozen` marker exists. During freeze that means a prior attempt sealed the
    bundle but its HTTP response was lost — the materialization is already done, so
    we skip ahead to the idempotent freeze rather than failing the retry.
    """
    if e.status_code != 409:
        return False
    return isinstance(e.body, dict) and e.body.get("error") == "revision_not_draft"


# The `log_source` tag the agent runner stamps on every log_entries row.
# Mirrors `AGENT_SESSION_LOG_SOURCE` in services/agent-shared/src/runtime/
# log-sink.ts — keep both sides in sync.
AGENT_SESSION_LOG_SOURCE = "agent_session"


def _mint_preview_jwt(
    application: AgentApplication,
    revision: AgentRevision,
    user: Any,
) -> tuple[str, int] | None:
    """Mint a short-lived HS256 JWT scoped to (app, rev) for non-live invokes.

    Returns `(token, ttl_seconds)` or `None` when no shared signing key is
    configured (dev / harness path — ingress's gate is then also bypassed).

    Bound to (app, rev) so a captured token can't be replayed against a
    different draft, and to `aud = agent-ingress.preview` so it can't be
    replayed against any other agent-platform service. The token only admits
    the non-live revision through routing; the revision runs against its own
    `encrypted_env`, so there's no per-session secret payload to carry.
    """
    if not settings.AGENT_INTERNAL_SIGNING_KEY:
        return None
    ttl_seconds = 15 * 60
    payload: dict[str, Any] = {
        "app": str(application.id),
        "rev": str(revision.id),
    }
    if user and getattr(user, "is_authenticated", False):
        payload["sub"] = f"user:{user.id}"
    token = encode_agent_internal_jwt(
        payload,
        timedelta(seconds=ttl_seconds),
        AgentInternalAudience.INGRESS_PREVIEW,
    )
    return token, ttl_seconds


# Per-trigger route catalogue. Mirrors the `path:` arrays in each
# `services/agent-ingress/src/triggers/<type>.ts` `routes` export — keep
# these tables in sync (a sibling test validates the chat one). Source of
# truth is still the ingress; this is here so the preview-token caller
# doesn't have to grep the ingress source to know which path to hit.
_TRIGGER_ROUTES: dict[str, dict[str, str]] = {
    "chat": {
        "run": "/run",
        "send": "/send",
        "cancel": "/cancel",
        "listen": "/listen",
        "client_tool_result": "/client_tool_result",
    },
    "mcp": {
        "rpc": "/mcp",
        "stream": "/mcp/stream",
        "connect_info": "/mcp/connect-info",
    },
    "slack": {
        "events": "/slack/events",
        "interactivity": "/slack/interactivity",
    },
    "webhook": {
        "post": "/webhook",
    },
    # `cron` triggers have no externally-callable ingress endpoint —
    # they fire from the janitor's scheduler. Omit from the catalogue
    # so the preview response doesn't advertise a URL the caller can't
    # actually hit.
}


def _build_preview_endpoints(ingress_slug: str, spec: dict[str, Any]) -> dict[str, dict[str, str]]:
    """Return `{trigger_type: {route_name: absolute_url}}` for every
    trigger the spec declares that has a public ingress route in
    `_TRIGGER_ROUTES`. Empty when no public agent-ingress URL is configured
    for the active routing mode (local dev without `bin/agent-tunnel`)."""
    triggers = spec.get("triggers") or []
    if not isinstance(triggers, list):
        return {}
    out: dict[str, dict[str, str]] = {}
    for trigger in triggers:
        if not isinstance(trigger, dict):
            continue
        ttype = trigger.get("type")
        if not isinstance(ttype, str):
            continue
        routes = _TRIGGER_ROUTES.get(ttype)
        if not routes:
            continue
        # First trigger of a given type wins; spec-side validation
        # should already enforce uniqueness, but be defensive.
        if ttype in out:
            continue
        urls = {name: agent_ingress_route_url(ingress_slug, path) for name, path in routes.items()}
        if any(url is None for url in urls.values()):
            return {}
        out[ttype] = {name: url for name, url in urls.items() if url is not None}
    return out


def _build_preview_auth_info(spec: dict[str, Any]) -> dict[str, Any]:
    """Surface the auth contract the caller has to satisfy when hitting
    the endpoints above. Auth is per-trigger now, so report the accepted
    modes keyed by trigger type. The preview-token gate is separate — the
    caller almost always needs both."""
    trigger_modes: dict[str, list[str]] = {}
    triggers = spec.get("triggers") or []
    if isinstance(triggers, list):
        for trigger in triggers:
            if not isinstance(trigger, dict):
                continue
            ttype = trigger.get("type")
            auth = trigger.get("auth")
            if not isinstance(ttype, str) or not isinstance(auth, dict):
                continue
            modes = auth.get("modes")
            if not isinstance(modes, list):
                continue
            trigger_modes[ttype] = [m["type"] for m in modes if isinstance(m, dict) and isinstance(m.get("type"), str)]
    return {
        "preview_token_header": "x-agent-preview-token",
        "preview_token_query": "preview_token",
        "trigger_modes": trigger_modes,
        "notes": (
            "The preview-token in `token` gates revision routing only (it admits non-live "
            "revisions). The ingress then ALSO enforces the auth modes declared on the trigger "
            "you're hitting — look up the trigger in `trigger_modes`, pick one of its modes, and "
            "attach the matching credential (Authorization: Bearer for posthog, x-posthog-internal "
            "for posthog_internal, the named header for shared_secret). Public-auth triggers accept "
            "anonymous; everything else needs a real credential alongside the preview-token."
        ),
    }


def _build_preview_proxy_info(request: Request, application: AgentApplication) -> dict[str, Any]:
    """Same-origin Django-side proxy. Convenient for browser SSE flows
    where attaching preview-tokens to EventSource is awkward; not a
    full replacement for the direct path because the proxy strips
    caller Authorization (so it can't satisfy a trigger's non-public
    auth modes)."""
    team_id = application.team_id
    proxy_base = (
        f"{request.scheme}://{request.get_host()}"
        f"/api/projects/{team_id}/agent_applications/{application.slug}/preview-proxy"
    )
    return {
        "base": proxy_base,
        "allowed_paths": sorted(AgentApplicationViewSet._PREVIEW_PROXY_ALLOWED_PATHS),
        "notes": (
            "Server-side proxy that mints the preview-token for you and forwards to ingress. "
            "Strips caller Authorization / Cookie before forwarding, so it works for agents "
            "whose hit trigger accepts anonymous (public) auth. Triggers with required auth "
            "(`posthog` / `posthog_internal` / `shared_secret`) need the direct endpoints "
            "above with a real credential attached."
        ),
    }


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
        "pendingApprovalsCount": drf_serializers.IntegerField(
            help_text=(
                "Approval-gated tool requests across the team currently awaiting a decision. "
                "0 on the per-application aggregate (which doesn't roll up approvals)."
            ),
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
        "approvals_decide",
        "users_connection_delete",
        # POST `preview_proxy` forwards `run`/`send`/`cancel` — each starts,
        # feeds, or kills a draft session, driving the agent's configured
        # tools and incurring inference cost. That's a write-class capability,
        # so it lives here even though it targets a non-live revision. The GET
        # `listen` counterpart (read-only SSE tail) stays in read actions.
        "preview_proxy",
        # Minting a preview JWT is a write-class capability regardless of verb:
        # the returned token lets a holder call `run`/`send`/`cancel` against a
        # draft directly, equivalent to `preview_proxy`. BOTH verbs require
        # `agents:write` — the POST (`preview_token_mint`) and the GET sibling
        # (`preview_token`, kept only because EventSource can't set headers)
        # return the identical usable token, so a read token must not be able to
        # mint one via either path and hit ingress on its own. (The
        # `preview_proxy*` actions differ: they use the JWT server-side and
        # never hand it back, so the GET `preview_proxy_get` stays read-scoped.)
        "preview_token_mint",
        "preview_token",
    ]
    scope_object_read_actions = [
        "list",
        "retrieve",
        "models",
        "spec_schema",
        "sessions_list",
        "sessions_retrieve",
        "session_logs",
        "users_list",
        "stats",
        # GET (SSE `listen`) → `preview_proxy_get`. DRF uses the bound function
        # name as `view.action`, so the GET variant is its own scope-map entry;
        # the mutating POST sibling (`preview_proxy`) is a write action above.
        # The proxy uses the preview JWT server-side and never returns it, so
        # this read-scoped GET can't leak a usable credential (unlike
        # `preview_token`, which is write-scoped above).
        "preview_proxy_get",
        "approvals_list",
        "approvals_retrieve",
    ]
    serializer_class = AgentApplicationSerializer
    queryset = AgentApplication.all_teams.all()

    def _should_skip_parents_filter(self) -> bool:
        # agent_platform is a product DB — models carry a plain `team_id` (no
        # `team` FK), so the mixin's `project_id` → `team__project_id` rewrite
        # can't resolve. Scope by `team_id` directly in safely_get_queryset.
        return True

    def safely_get_queryset(self, queryset: QuerySet) -> QuerySet:
        return queryset.filter(team_id=self.team_id, archived=False)

    def safely_get_object(self, queryset: QuerySet) -> AgentApplication | None:
        return _resolve_application(queryset, self.kwargs[self.lookup_url_kwarg or self.lookup_field])

    def perform_create(self, serializer: drf_serializers.BaseSerializer[Any]) -> None:
        serializer.save(team_id=self.team_id, created_by_id=self.request.user.id)

    def perform_destroy(self, instance: AgentApplication) -> None:
        """Soft-delete: archived=True, archived_at=NOW. Preserves audit history.

        Also revoke every linked identity credential for the application: archive
        is terminal (no unarchive), so a retired agent should hold no decryptable
        bearers. Done in the same transaction via the ORM — Django owns this table,
        so no janitor round-trip — and `state='active'` keeps it idempotent.
        """
        now = timezone.now()
        with transaction.atomic(using=WRITER_DB):
            instance.archived = True
            instance.archived_at = now
            instance.save(update_fields=["archived", "archived_at", "updated_at"])
            AgentIdentityCredential.objects.using(WRITER_DB).filter(application_id=instance.id, state="active").update(
                state="revoked", revoked_at=now, updated_at=now
            )

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
        # Document the forwarded body (`run`/`send` carry `message`) so the
        # generated MCP tool exposes it — without this the tool had no way to
        # pass a chat message. SCHEMA-ONLY: the action never validates against
        # this serializer; the raw body is forwarded to ingress verbatim (shape
        # varies by `rest`, extra keys pass through). It exists purely to shape
        # the generated tool / OpenAPI. Response is the ingress SSE stream.
        request=PreviewProxyInvokeRequestSerializer,
        responses={(200, "text/event-stream"): OpenApiTypes.STR},
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
        this proxy attaches it after authenticating the Django caller.

        URL: `/api/projects/<team>/agent_applications/<app>/preview-proxy/<rest>`
        Auth: standard PAT / session — `agents:write` scope (POST run/send/cancel
        is a mutating invoke; the read-only `listen` GET is `agents:read`).
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
        revision = AgentRevision.all_teams.filter(application=application, pk=revision_id).first()
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
        # Defence-in-depth: the slug is interpolated into the upstream URL path,
        # so reject anything that isn't a strict lowercase slug before building
        # it — guards against a slug that reached the DB without the model /
        # serializer validators (e.g. a raw node-side write).
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,61}[a-z0-9]?", application.slug):
            raise ValidationError("Application slug contains unsafe characters")
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
            # The ingress is an in-cluster service — use the internal session so the
            # call bypasses HTTP(S)_PROXY (smokescreen blocks private IPs → 407).
            upstream = internal_requests.request(
                method=request.method or "GET",
                url=upstream_url,
                headers=forwarded_headers,
                data=body_bytes,
                stream=True,
                timeout=30.0,
            )
        except requests.RequestException as e:
            logger.exception("preview-proxy upstream call failed")
            raise APIException(detail=f"preview-proxy upstream unreachable: {e}") from e

        # Async iterator so Django's ASGI handler doesn't warn about consuming
        # a sync generator. `requests` is blocking, so each chunk pull hops to
        # a thread via sync_to_async.
        async def _stream() -> AsyncIterator[bytes]:
            sync_iter = upstream.iter_content(chunk_size=None)
            sentinel = object()

            def _next_chunk() -> object:
                return next(sync_iter, sentinel)

            try:
                while True:
                    chunk = await sync_to_async(_next_chunk, thread_sensitive=False)()
                    if chunk is sentinel:
                        break
                    if chunk:
                        yield cast(bytes, chunk)
            finally:
                await sync_to_async(upstream.close, thread_sensitive=False)()

        resp = streaming_response(
            _stream(),
            content_type=upstream.headers.get("Content-Type", "application/octet-stream"),
            status=upstream.status_code,
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
        # `@action`-decorated method confuses mypy about the bound-method signature.
        return self.preview_proxy(request, rest=rest, **kwargs)  # type: ignore[arg-type]

    # ── Preview token (direct-to-ingress flow) ───────────────────────
    # Alternative to `preview_proxy`: returns a short-lived JWT the
    # browser can attach to direct ingress calls. Console uses this
    # for chat hops (SSE through the Django proxy is awkward — DRF
    # content negotiation, redirects, body buffering all bite). The
    # proxy action stays for non-browser callers that prefer
    # server-side mediation. Both share `_mint_preview_jwt` so the
    # JWT payload + secret can't drift between paths.

    # Reused by GET + POST so drf-spectacular emits one component and the two
    # operations stay shape-locked. POST is the contract-faithful verb (minting
    # is a write); GET stays for `EventSource` callers and back-compat.
    _PREVIEW_TOKEN_RESPONSE = OpenApiResponse(
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
                    help_text="Slug to use in the ingress URL — `<application_slug>-<revision_uuid_hex>`. Identifies the exact revision, placed in the host (domain mode) or path (path mode) routing prefix.",
                ),
                "endpoints": drf_serializers.JSONField(
                    help_text="Per-trigger ingress URLs the caller can hit directly, derived from the revision's `spec.triggers[]`. Shape: `{<trigger_type>: {<route_name>: <absolute_url>}}`. Only includes triggers the spec actually declares. Empty when no public agent-ingress URL is configured for the active routing mode.",
                ),
                "auth": drf_serializers.JSONField(
                    help_text="How to attach credentials to those endpoints: preview-token header/query names, the per-trigger accepted auth modes (`trigger_modes`), and a note about the live vs preview-mode gate split. Lets the caller wire auth without grepping the ingress source.",
                ),
                "preview_proxy": drf_serializers.JSONField(
                    help_text="Server-side alternative — `/api/projects/<team>/agent_applications/<slug>/preview-proxy/<path>` mints the JWT for you. Strips caller Authorization, so it works for public-auth agents; agents with required auth need the direct endpoints above.",
                ),
            },
        ),
    )

    _PREVIEW_TOKEN_PARAMETERS = [
        OpenApiParameter(
            "revision_id",
            OpenApiTypes.UUID,
            OpenApiParameter.QUERY,
            required=True,
            description="Target draft revision. Must belong to this application and not be live.",
        ),
    ]

    # The two verbs live on separate action methods so DRF resolves them to
    # distinct `view.action` names — `preview_token` (GET) and
    # `preview_token_mint` (POST). Both are write-scoped (see the scope lists):
    # the returned JWT is a usable credential for `run`/`send`/`cancel`, so
    # minting it requires `agents:write` no matter the verb. The GET sibling
    # exists only because EventSource can't set headers — it is NOT a
    # read-only-safe alternative. A shared body keeps the response shape
    # lock-stepped across both.

    def _build_preview_token_response(self, request: Request) -> Response:
        application = self.get_object()
        if application is None:
            raise NotFound("Application not found")
        revision_id = request.query_params.get("revision_id")
        if not revision_id:
            raise ValidationError("revision_id query parameter is required")
        revision = AgentRevision.all_teams.filter(application=application, pk=revision_id).first()
        if not revision:
            raise NotFound("Revision not found in this application")
        if application.live_revision_id == revision.id:
            raise ValidationError(
                "preview-token is for non-live revisions only; the live revision is reachable without a token via its public ingress URL"
            )
        spec = revision.spec if isinstance(revision.spec, dict) else {}
        token_pair = _mint_preview_jwt(application, revision, request.user)
        ingress_slug = f"{application.slug}-{revision.id.hex}"
        body: dict[str, Any] = {
            "token": token_pair[0] if token_pair is not None else "",
            "expires_in": token_pair[1] if token_pair is not None else 0,
            "ingress_slug": ingress_slug,
            "endpoints": _build_preview_endpoints(ingress_slug, spec),
            "auth": _build_preview_auth_info(spec),
            "preview_proxy": _build_preview_proxy_info(request, application),
        }
        return Response(body)

    @extend_schema(
        operation_id="agent_applications_preview_token_mint",
        parameters=_PREVIEW_TOKEN_PARAMETERS,
        request=None,
        responses=_PREVIEW_TOKEN_RESPONSE,
    )
    @action(detail=True, methods=["post"], url_path="preview-token")
    def preview_token_mint(self, request: Request, **kwargs) -> Response:
        """Mint a short-lived JWT for talking to a non-live revision
        directly via the public ingress URL. The caller attaches it as
        the `x-agent-preview-token` header (or `?preview_token=` query
        param for `EventSource`). See `_mint_preview_jwt` for the
        payload + claim binding.

        The response also includes `endpoints`, `auth`, and
        `preview_proxy` blocks so the caller can wire a preview
        invocation without grepping the agent-ingress source for which
        path each trigger exposes or which header name carries the
        token. This is the "self-describing" half of preview-mode —
        every piece of info you need to hit ingress is in one response.

        POST is the canonical verb — minting credentials for downstream
        `run`/`send`/`cancel` is a write-class capability. A GET sibling
        exists at the same URL for `EventSource` callers (which can't set
        headers); it is also write-scoped, since it returns the same token.
        """
        return self._build_preview_token_response(request)

    @extend_schema(
        operation_id="agent_applications_preview_token",
        parameters=_PREVIEW_TOKEN_PARAMETERS,
        request=None,
        responses=_PREVIEW_TOKEN_RESPONSE,
    )
    @preview_token_mint.mapping.get
    def preview_token(self, request: Request, **kwargs) -> Response:
        """GET sibling of `preview_token_mint`. Same body and response
        shape — exists because `EventSource` can't set headers, so SSE
        callers fetch the token via GET and then attach `?preview_token=`
        to the ingress URL. Behind the same URL (`url_path="preview-token"`)
        thanks to DRF's `@<action>.mapping.get`; DRF resolves it to a
        distinct `view.action`, but it is in `scope_object_write_actions`
        alongside the POST sibling — both return a usable credential, so
        both require `agents:write`.
        """
        return self._build_preview_token_response(request)

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
        operation_id="agent_applications_models",
        description=(
            "Served-model catalog — each model's id, provider, context window, and "
            "USD-per-million-token pricing — plus the curated auto-level → model map. "
            "Project-agnostic; sourced from the AI gateway catalog. Powers the config "
            "UI model browser and the agent builder's model-choosing skill."
        ),
    )
    @action(detail=False, methods=["get"], url_path="models")
    def models(self, request: Request, **kwargs) -> Response:
        """The model catalog. Proxies the janitor, which owns the gateway-catalog
        client and the level map (single source for runtime + UI + agents)."""
        try:
            payload = _janitor().get_models()
        except JanitorClientError as e:
            raise JanitorUpstreamError(e) from e
        return Response(payload)

    @extend_schema(
        operation_id="agent_applications_spec_schema",
        parameters=[
            OpenApiParameter(
                "section",
                OpenApiTypes.STR,
                OpenApiParameter.QUERY,
                required=False,
                description=(
                    "Return only this top-level slice of the spec schema to save tokens — one of "
                    "`models`, `triggers`, `tools`, `mcps`, `skills`, `identity_providers`, `secrets`, "
                    "`limits`, `reasoning`, `framework_prompt`, `resume`. Omit for the whole spec schema."
                ),
            ),
        ],
        description=(
            "The canonical JSON Schema for an agent `spec` — every field, type, enum, default, and the "
            "discriminated unions for `models` / `triggers[]` / `tools[]`, each with an inline description. "
            "Emitted from the same source the runner validates against (fields with a default are optional "
            "on write), so read it BEFORE composing a spec for create / revisions-spec-update instead of "
            "guessing the shape. Pass `section` to fetch just one part."
        ),
    )
    @action(detail=False, methods=["get"], url_path="spec_schema")
    def spec_schema(self, request: Request, **kwargs) -> Response:
        """The agent-spec JSON Schema, proxied from the janitor, which emits it
        from the canonical zod `AgentSpecSchema` (no Python mirror — the schema
        an author reads can't drift from the one the runner parses). Optional
        `section` slices one top-level property."""
        section = request.query_params.get("section") or None
        try:
            payload = _janitor().get_spec_schema(section=section)
        except JanitorClientError as e:
            # A bad `section` is a client error — the janitor returns 400 with the
            # valid section list. Surface that as a clean 400, not a 502.
            if e.status_code == status.HTTP_400_BAD_REQUEST:
                body = e.body if isinstance(e.body, dict) else {"detail": e.message}
                return Response(body, status=status.HTTP_400_BAD_REQUEST)
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
                                        "Trigger-specific metadata stamped at session creation. Discriminated on "
                                        "`kind`: chat | slack | cron | webhook | mcp. The Zod source of truth is "
                                        "`agent-shared/src/runtime/trigger-metadata.ts`; the node side validates "
                                        "and strips unknown keys at the persistence boundary, so consumers can "
                                        "trust `kind` and per-kind fields. TODO: narrow this DictField to a "
                                        "polymorphic serializer mirroring the union (needs `hogli build:openapi`)."
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
        """List sessions for this application, most recently active first. Strips the
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
                agent_user_id=request.query_params.get("agent_user_id") or None,
                created_after=request.query_params.get("created_after") or None,
                created_before=request.query_params.get("created_before") or None,
                search=request.query_params.get("search") or None,
            )
        except JanitorClientError as e:
            raise JanitorUpstreamError(e) from e
        return Response(payload)

    @extend_schema(
        operation_id="agent_applications_users_list",
        description=(
            "List this agent's end-users (the stable identities behind inbound "
            "principals) and each user's linked external connections. Connection "
            "metadata only — credential material is never returned."
        ),
        responses=OpenApiResponse(
            response=inline_serializer(
                name="AgentUsersList",
                fields={
                    "count": drf_serializers.IntegerField(),
                    "results": drf_serializers.ListField(
                        child=inline_serializer(
                            name="AgentUserWithConnections",
                            fields={
                                "id": drf_serializers.UUIDField(),
                                "principal_kind": drf_serializers.CharField(
                                    help_text="Edge-identity kind: slack | jwt | posthog | service | …",
                                ),
                                "principal_id": drf_serializers.CharField(),
                                "metadata": drf_serializers.JSONField(allow_null=True, required=False),
                                "created_at": drf_serializers.DateTimeField(),
                                "connections": drf_serializers.ListField(
                                    child=inline_serializer(
                                        name="AgentUserConnection",
                                        fields={
                                            "id": drf_serializers.UUIDField(),
                                            "provider": drf_serializers.CharField(),
                                            "scopes": drf_serializers.ListField(child=drf_serializers.CharField()),
                                            "state": drf_serializers.CharField(help_text="active | revoked"),
                                            "subject": drf_serializers.CharField(allow_null=True, required=False),
                                            "access_expires_at": drf_serializers.DateTimeField(
                                                allow_null=True, required=False
                                            ),
                                            "created_at": drf_serializers.DateTimeField(),
                                            "updated_at": drf_serializers.DateTimeField(),
                                            "revoked_at": drf_serializers.DateTimeField(
                                                allow_null=True, required=False
                                            ),
                                        },
                                    )
                                ),
                            },
                        )
                    ),
                },
            )
        ),
    )
    @action(detail=True, methods=["get"], url_path="users")
    def users_list(self, request: Request, **kwargs) -> Response:
        """End-users of this agent, each with their linked connections."""
        application = self.get_object()
        if application is None:
            raise NotFound("Application not found")
        try:
            payload = _janitor().list_users(int(self.team_id), str(application.id))
        except JanitorClientError as e:
            raise JanitorUpstreamError(e) from e
        return Response(payload)

    @extend_schema(
        operation_id="agent_applications_users_connection_delete",
        description=(
            "Revoke one of an end-user's linked connections. The credential is "
            "marked revoked (kept for audit), so the agent can no longer act as "
            "that user on the provider."
        ),
        parameters=[
            OpenApiParameter("agent_user_id", OpenApiTypes.UUID, OpenApiParameter.PATH, required=True),
            OpenApiParameter(
                "provider",
                OpenApiTypes.STR,
                OpenApiParameter.PATH,
                required=True,
                description="Identity provider id (e.g. 'posthog', 'github').",
            ),
        ],
        responses=OpenApiResponse(
            response=inline_serializer(
                name="AgentConnectionDelete",
                fields={
                    "provider": drf_serializers.CharField(),
                    "revoked": drf_serializers.BooleanField(),
                },
            )
        ),
    )
    @action(
        detail=True,
        methods=["delete"],
        url_path=r"users/(?P<agent_user_id>[^/.]+)/connections/(?P<provider>[^/.]+)",
    )
    def users_connection_delete(
        self, request: Request, agent_user_id: str = "", provider: str = "", **kwargs
    ) -> Response:
        """Revoke one linked connection for an end-user."""
        application = self.get_object()
        if application is None:
            raise NotFound("Application not found")
        try:
            payload = _janitor().delete_connection(int(self.team_id), str(application.id), agent_user_id, provider)
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
                            "Trigger-specific metadata stamped at session creation. Discriminated on "
                            "`kind`: chat | slack | cron | webhook | mcp. The Zod source of truth is "
                            "`agent-shared/src/runtime/trigger-metadata.ts`; the node side validates and "
                            "strips unknown keys at the persistence boundary, so consumers can trust "
                            "`kind` and per-kind fields. TODO: narrow this DictField to a polymorphic "
                            "serializer mirroring the union (needs `hogli build:openapi`)."
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
    # AGENT_DB is node-owned (per CLAUDE.md rule #2 in products/agent_platform).
    # Django never queries `agent_tool_approval_request` directly — these
    # actions auth-check on the Django side, then proxy through
    # janitor_client. The janitor owns the wake path (markApproving + write
    # marker into pending_inputs); the runner picks up on its next claim.

    _APPROVAL_RESPONSE_FIELDS: dict[str, drf_serializers.Field] = {
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
            help_text="Resolved approval policy (type: principal|agent, allow_edit) at request time.",
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
            user=cast(User, self.request.user), organization_id=self.organization_id
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
            payload = _janitor().get_approval(approval_id, application_id=str(application.id))
        except JanitorClientError as e:
            raise JanitorUpstreamError(e) from e
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
        """Approve or reject a queued `agent`-type tool-approval request.

        This is the OWNER decision surface — the only PostHog-authoritative one:
        team admins decide here, in the console. `principal`-type approvals are
        decided by the session principal at the ingress decision API, not here.
        The runtime side runs the tool platform-side on approve and wakes the
        session with a synthetic tool_result either way."""
        application = self.get_object()
        if application is None:
            raise NotFound("Application not found")
        self._require_team_admin()
        body = DecideApprovalRequestSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        try:
            existing = _janitor().get_approval(approval_id, application_id=str(application.id))
        except JanitorClientError as e:
            raise JanitorUpstreamError(e) from e
        # Only `agent`-type approvals are decided through the console. A
        # `principal`-type request is the session owner's to clear at the ingress
        # decision API; collapse it to not-found here. (Legacy rows queued before
        # the principal/agent split carry `approvers[]` instead of `type` — map
        # `team_admins` → agent so an in-flight old row stays decidable.)
        scope = existing.get("approver_scope", {})
        approval_type = scope.get("type")
        if approval_type is None:
            approval_type = "agent" if "team_admins" in (scope.get("approvers") or []) else "principal"
        if approval_type != "agent":
            raise NotFound("Approval not found")
        # A human acting interactively only: SessionAuthentication, or a bearer
        # from a first-party PostHog OAuth app (e.g. PostHog Code, where a human
        # approves in-app) — `is_first_party` is staff-set on the app, so a
        # third-party OAuth app or a personal API key can't decide an owner
        # approval.
        authenticator = request.successful_authenticator
        is_session = isinstance(authenticator, SessionAuthentication)
        is_first_party_oauth = isinstance(authenticator, OAuthAccessTokenAuthentication) and bool(
            getattr(getattr(authenticator.access_token, "application", None), "is_first_party", False)
        )
        if not is_session and not is_first_party_oauth:
            raise NotFound("Approval not found")
        try:
            payload = _janitor().decide_approval(
                approval_id,
                decision=body.validated_data["decision"],
                # decision_by is a UUID column — send the user's uuid, not the
                # integer pk (which fails as "invalid input syntax for type uuid").
                decided_by=str(request.user.uuid) if request.user and request.user.is_authenticated else "",
                edited_args=body.validated_data.get("edited_args"),
                reason=body.validated_data.get("reason"),
                application_id=str(application.id),
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
        "put_bundle",
        "put_agent_md",
        "put_spec",
        "set_skill_refs",
        "put_tool",
        "delete_tool",
        # Dry-run reads the persisted compiled.js but actually executes user
        # code in a sandbox — treat it as a write-scoped op so the scope
        # gates arbitrary compute, not just data reads.
        "dry_run_tool",
        "update_bundle_file",
        "import_bundle",
        "cron_fire",
        "set_env",
        # env_keys_key handles GET/PUT/DELETE on /env_keys/<KEY>/ — bundled
        # under :write because PUT/DELETE are the load-bearing ops and we
        # don't want the scope to drift between methods.
        "env_keys_key",
    ]
    scope_object_read_actions = [
        "list",
        "retrieve",
        "manifest",
        "slack_manifest",
        "get_bundle",
        "validate",
        "system_prompt",
        "env_keys_list",
    ]
    serializer_class = AgentRevisionSerializer
    queryset = AgentRevision.all_teams.all()

    def get_application(self) -> AgentApplication:
        # drf-extensions nested routing passes the parent URL kwarg as
        # `parent_lookup_application_id` (see `parents_query_lookups` in the
        # nested router registration in posthog/api/__init__.py).
        app = _resolve_application(
            AgentApplication.all_teams.filter(team_id=self.team_id, archived=False),
            self.kwargs.get("parent_lookup_application_id") or self.kwargs.get("application_id"),
        )
        if app is None:
            raise NotFound("Application not found")
        return app

    def _should_skip_parents_filter(self) -> bool:
        # Product-DB model (plain team_id, no team FK). Scoping is via the
        # application filter below — get_application() resolves it team-scoped.
        return True

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

    def perform_create(self, serializer: drf_serializers.BaseSerializer[Any]) -> None:
        application = self.get_application()
        # Fresh revisions start in `draft`. Parent revision is optional — if
        # set, this revision can later be diff'd against it for review.
        # bundle_uri is optional metadata; fill the `fs://<slug>/` convention
        # when the caller leaves it blank so a no-source create "just works".
        bundle_uri = serializer.validated_data.get("bundle_uri") or f"fs://{application.slug}/"
        serializer.save(
            application=application,
            team_id=application.team_id,
            state="draft",
            created_by_id=self.request.user.id,
            bundle_uri=bundle_uri,
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
        # must be set in this revision's `encrypted_env` before promote,
        # otherwise the ingress would 500 on the first inbound webhook for the
        # trigger. Per-key gate, not per-trigger — multiple triggers can share
        # a key. Secrets are per-revision, so the gate reads the revision being
        # promoted (not the application).
        env_map = _decode_env_map(revision.encrypted_env)
        missing = missing_required_secrets(revision.spec or {}, env_map)
        if missing:
            details = ", ".join(f"{m['key']} (for {m['trigger']} trigger)" for m in missing)
            raise ValidationError(
                f"Cannot promote: agent is missing required encrypted_env entries: {details}. "
                f"Set the value(s) via the env editor then retry."
            )

        # Managed PostHog identity providers: ensure each declared `{kind:posthog}`
        # provider has a (normal, user-consented) OAuthApplication and inject its
        # client_id into the spec. Idempotent; runs before the state flip so the
        # frozen-and-live spec carries the client_id the runner links against.
        spec_mutated = provision_posthog_identity_apps(
            # Promote requires auth, so this is always a real User (not Anonymous);
            # cast to satisfy the `User | None` signature, as elsewhere in this file.
            application=revision.application,
            revision=revision,
            acting_user=cast(User, request.user),
        )

        # All three writes — demote previous live, set this live, point the
        # application — must succeed or fail together. select_for_update on
        # the application row serializes concurrent promotes so two callers
        # can't both archive the same predecessor or land both revisions in
        # state="live" with the application pointing at only one.
        with transaction.atomic(using=WRITER_DB):
            application = (
                AgentApplication.all_teams.using(WRITER_DB).select_for_update().get(pk=revision.application_id)
            )
            previously_live = application.live_revision
            if previously_live and previously_live.id != revision.id:
                previously_live.state = "archived"
                previously_live.save(update_fields=["state", "updated_at"])
            revision.state = "live"
            revision.save(update_fields=["state", "spec", "updated_at"] if spec_mutated else ["state", "updated_at"])
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
        # Same atomic+lock shape as promote — without it, a concurrent
        # promote could read the pre-archive `live_revision` and overwrite
        # our clear, leaving the application pointed at an archived row.
        with transaction.atomic(using=WRITER_DB):
            application = (
                AgentApplication.all_teams.using(WRITER_DB).select_for_update().get(pk=revision.application_id)
            )
            revision.state = "archived"
            revision.save(update_fields=["state", "updated_at"])
            if application.live_revision_id == revision.id:
                application.live_revision = None
                application.save(update_fields=["live_revision", "updated_at"])
        return Response({"ok": True, "state": "archived"})

    # ── Per-revision env / secrets ──────────────────────────────────────────
    # Secrets live on the revision (each revision runs against its own
    # `encrypted_env`). Set-replace via `set_env` is fine for bulk sync; the
    # per-key routes below let the UI inspect + mutate one secret at a time
    # without ever exposing decrypted values across the wire. Editing is
    # allowed in ANY state (not just draft) — rotating a leaked/expired key on
    # a live revision must not require cutting a new one. Spec edits stay
    # draft-only; secrets are operational, not structural.

    @extend_schema(request=SetEnvRequestSerializer)
    @action(detail=True, methods=["post"], url_path="set_env")
    def set_env(self, request: Request, **kwargs) -> Response:
        """Replace this revision's encrypted env block.

        The body is `{ "env": { "<KEY>": "<value>", ... } }`. The encrypted
        text is stored on `AgentRevision.encrypted_env`; the worker decrypts it
        at session start via the same Fernet schedule (see
        agent-shared/src/runtime/encryption.ts).
        """
        revision: AgentRevision = self.get_object()
        body = SetEnvRequestSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        # EncryptedTextField encrypts on assignment when saved. Serialize the
        # env dict as JSON before encryption so the worker gets a JSON object
        # back out.
        revision.encrypted_env = json.dumps(body.validated_data["env"])
        revision.save(update_fields=["encrypted_env", "updated_at"])
        return Response({"ok": True})

    _ENV_KEY_NAME = OpenApiParameter(
        "key",
        OpenApiTypes.STR,
        OpenApiParameter.PATH,
        required=True,
        description="The env variable name. Conventionally UPPER_SNAKE_CASE; the API does not enforce a shape.",
    )

    @extend_schema(
        operation_id="agent_revisions_env_keys_list",
        request=None,
        responses=OpenApiResponse(
            response=inline_serializer(
                name="AgentRevisionEnvKeysResponse",
                fields={
                    "keys": drf_serializers.ListField(
                        child=drf_serializers.CharField(),
                        help_text="Names of env variables currently set on the revision. Values are never returned.",
                    ),
                },
            ),
        ),
    )
    @action(detail=True, methods=["get"], url_path="env_keys")
    def env_keys_list(self, request: Request, **kwargs) -> Response:
        """List the names of secrets currently set on this revision.

        Returns names only — values stay server-side under
        `EncryptedTextField`. Use this to drive the "set / unset" badge next to
        a declared secret in the editor UI.
        """
        revision: AgentRevision = self.get_object()
        env_map = _decode_env_map(revision.encrypted_env)
        # Sort for stable UI ordering; the encrypted JSON has no meaningful
        # order of its own.
        return Response({"keys": sorted(env_map.keys())})

    # One inline status serializer reused by all three method schemas so
    # drf-spectacular emits a single named component instead of three
    # near-identical ones.
    _ENV_KEY_STATUS_RESPONSE = OpenApiResponse(
        response=inline_serializer(
            name="AgentRevisionEnvKeyStatus",
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
        operation_id="agent_revisions_env_keys_get",
        parameters=[_ENV_KEY_NAME],
        request=None,
        responses=_ENV_KEY_STATUS_RESPONSE,
    )
    @extend_schema(
        methods=["PUT"],
        operation_id="agent_revisions_env_keys_set",
        parameters=[_ENV_KEY_NAME],
        request=SetEnvKeyRequestSerializer,
        responses=_ENV_KEY_STATUS_RESPONSE,
    )
    @extend_schema(
        methods=["DELETE"],
        operation_id="agent_revisions_env_keys_clear",
        parameters=[_ENV_KEY_NAME],
        request=None,
        responses=_ENV_KEY_STATUS_RESPONSE,
    )
    @action(detail=True, methods=["get", "put", "delete"], url_path="env_keys/(?P<key>[^/.]+)")
    def env_keys_key(self, request: Request, key: str, **kwargs) -> Response:
        """GET / PUT / DELETE one secret by name on this revision.

        - `GET`    → `{ key, is_set }` (never returns the value).
        - `PUT`    → upserts `{ value }` into the env block.
        - `DELETE` → removes the key. No-op when it wasn't set.

        Per-method scope: GET is treated as a write action so the single action
        name maps to one consistent scope; reading whether a secret is set is
        restricted to writers in any case.
        """
        revision: AgentRevision = self.get_object()
        env_map = _decode_env_map(revision.encrypted_env)

        if request.method == "GET":
            return Response({"key": key, "is_set": key in env_map})

        if request.method == "DELETE":
            env_map.pop(key, None)
            revision.encrypted_env = json.dumps(env_map)
            revision.save(update_fields=["encrypted_env", "updated_at"])
            return Response({"key": key, "is_set": False})

        # PUT
        body = SetEnvKeyRequestSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        env_map[key] = body.validated_data["value"]
        revision.encrypted_env = json.dumps(env_map)
        revision.save(update_fields=["encrypted_env", "updated_at"])
        return Response({"key": key, "is_set": True})

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

    @extend_schema(
        operation_id="agent_applications_revisions_slack_manifest",
        request=None,
        responses=OpenApiResponse(
            response=inline_serializer(
                name="AgentRevisionSlackManifestResponse",
                fields={
                    "revision_id": drf_serializers.UUIDField(),
                    "manifest": drf_serializers.JSONField(
                        help_text=(
                            "Slack app manifest (JSON) ready to paste into "
                            "https://api.slack.com/apps?new_app=1 → 'From an app manifest'. Scopes and "
                            "event subscriptions are derived from the agent's slack trigger config + tools."
                        )
                    ),
                    "notes": drf_serializers.ListField(
                        child=drf_serializers.CharField(),
                        help_text="Reminders the manifest can't enforce (e.g. invite the bot to its channels).",
                    ),
                    "events_url": drf_serializers.CharField(
                        allow_null=True, help_text="The Event Subscriptions Request URL baked into the manifest."
                    ),
                    "interactivity_url": drf_serializers.CharField(
                        allow_null=True, help_text="The Interactivity Request URL (used by approval-gated tools)."
                    ),
                },
            )
        ),
    )
    @action(detail=True, methods=["get"], url_path="slack_manifest")
    def slack_manifest(self, request: Request, **kwargs) -> Response:
        """Build a Slack app manifest for this revision's slack trigger.

        Deterministic: the OAuth scopes and bot event subscriptions are derived
        from the slack trigger config (`mention_only` / `auto_resume_threads` /
        `ack_reaction`) and the agent's Slack tools, so the manifest already
        subscribes to exactly the events the config needs. 400 if the revision
        has no slack trigger.
        """
        revision: AgentRevision = self.get_object()
        slug = revision.application.slug
        events_url = agent_ingress_route_url(slug, "/slack/events")
        interactivity_url = agent_ingress_route_url(slug, "/slack/interactivity")
        result = self._call(
            _janitor().slack_manifest,
            str(revision.id),
            events_url=events_url,
            interactivity_url=interactivity_url,
        )
        return Response({**result, "events_url": events_url, "interactivity_url": interactivity_url})

    # DRF routes the typed bundle verbs across @action + .mapping.<verb>
    # chains. Separate @action decorators with the same url_path don't merge —
    # the last one registered wins and the others 405 — so GET+PUT under /bundle/
    # share a single @action with a mapping chain below.
    # NOTE: skill folders are deliberately NOT author-writable through Django.
    # There is no `skills/<id>` author action (only agent_md/spec/skill_refs/tools);
    # `skills/` is populated only at freeze (resolved store `skill_refs` + injected
    # platform kernel skills). The janitor's `PUT/DELETE /revisions/:id/skills/:id`
    # is internal-only, reachable solely via `janitor_client.put_skill`/`delete_skill`
    # during freeze. Do NOT proxy it through to authors — that re-opens the
    # store-only boundary kernel skills + skill_refs are built to enforce.

    # ── typed bundle authoring API ──────────────────────────────────────
    # Django
    # is a thin proxy: every byte of the payload flows through to the
    # janitor unchanged. The legacy file-grain endpoints (file/, bundle/
    # with mode) were removed.

    @extend_schema(request=None)
    @action(detail=True, methods=["get"], url_path="bundle")
    def get_bundle(self, request: Request, **kwargs) -> Response:
        """Read the full typed bundle: `{ agent_md, skills, tools, spec }`."""
        revision: AgentRevision = self.get_object()
        return Response(self._call(_janitor().get_bundle, str(revision.id)))

    @extend_schema(request=WriteTypedBundleRequestSerializer)
    @get_bundle.mapping.put
    def put_bundle(self, request: Request, **kwargs) -> Response:
        """Full-replace the typed bundle. Anything not in the payload is
        deleted. Tool sources are AST-checked + esbuild-compiled by the
        janitor before any S3 writes."""
        revision: AgentRevision = self.get_object()
        body = WriteTypedBundleRequestSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        return Response(self._call(_janitor().put_bundle, str(revision.id), body.validated_data))

    @extend_schema(request=WriteAgentMdRequestSerializer)
    @action(detail=True, methods=["put"], url_path="agent_md")
    def put_agent_md(self, request: Request, **kwargs) -> Response:
        revision: AgentRevision = self.get_object()
        body = WriteAgentMdRequestSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        return Response(self._call(_janitor().put_agent_md, str(revision.id), body.validated_data["content"]))

    @extend_schema(request=WriteSpecRequestSerializer)
    @action(detail=True, methods=["put"], url_path="spec")
    def put_spec(self, request: Request, **kwargs) -> Response:
        revision: AgentRevision = self.get_object()
        body = WriteSpecRequestSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        return Response(self._call(_janitor().put_spec, str(revision.id), body.validated_data["spec"]))

    @extend_schema(request=SetSkillRefsRequestSerializer, responses={200: AgentRevisionSerializer})
    @action(detail=True, methods=["put"], url_path="skill_refs")
    def set_skill_refs(self, request: Request, **kwargs) -> Response:
        """Full-replace the draft's store-skill references. They are resolved
        and materialized into the bundle at freeze, not here — this only records
        which skills (and pinned versions) the freeze should pull in."""
        revision: AgentRevision = self.get_object()
        if revision.state != "draft":
            raise ValidationError(
                f"Cannot set skill references on a {revision.state} revision; only 'draft' is mutable."
            )
        body = SetSkillRefsRequestSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        refs = body.validated_data["skill_refs"]
        aliases = [r["alias"] for r in refs]
        if len(set(aliases)) != len(aliases):
            raise ValidationError("Each skill reference must have a unique 'alias' within the revision.")
        # Same skill-read authorization the freeze enforces — surfaced early here
        # so an author setting refs gets the 403 at write time, not at freeze.
        assert_skill_refs_readable(
            self.team,
            [dict(r) for r in refs],
            scopes=get_authenticator_scopes(getattr(request, "successful_authenticator", None)),
            user_access_control=self.user_access_control,
        )
        # Lock the row and re-check state before writing: a concurrent freeze
        # could have sealed the bundle and flipped this revision to `ready`
        # between our first read and this write — writing `skill_refs` onto a
        # frozen revision would leave the column describing skills the sealed
        # bundle doesn't contain.
        with transaction.atomic(using=WRITER_DB):
            locked = AgentRevision.all_teams.using(WRITER_DB).select_for_update().get(pk=revision.pk)
            if locked.state != "draft":
                raise ValidationError(
                    f"Cannot set skill references on a {locked.state} revision; only 'draft' is mutable."
                )
            locked.skill_refs = [dict(r) for r in refs]
            locked.save(update_fields=["skill_refs"])
        revision.refresh_from_db()
        return Response(AgentRevisionSerializer(revision).data)

    @extend_schema(request=WriteToolRequestSerializer)
    @action(detail=True, methods=["put"], url_path=r"tools/(?P<tool_id>[a-z0-9][a-z0-9_-]*)")
    def put_tool(self, request: Request, tool_id: str, **kwargs) -> Response:
        revision: AgentRevision = self.get_object()
        body = WriteToolRequestSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        return Response(self._call(_janitor().put_tool, str(revision.id), tool_id, body.validated_data))

    @extend_schema(request=None)
    @put_tool.mapping.delete
    def delete_tool(self, request: Request, tool_id: str, **kwargs) -> Response:
        revision: AgentRevision = self.get_object()
        return Response(self._call(_janitor().delete_tool, str(revision.id), tool_id))

    # ── editable .md surface: per-file PUT + bulk import ────────────────
    # Author surface for the configuration-pane editor and the bulk-paste
    # migration dialog. `agent.md` writes proxy to the draft bundle via the
    # janitor. Skill writes are store-backed: freeze materializes
    # `skill_refs` from the skill store and sweeps everything else out of
    # `skills/`, so a draft-bundle write could never stick — instead an
    # edit publishes a new version of the referenced store skill and
    # re-pins the draft's ref to it (see logic/skill_editing.py). Both
    # endpoints are draft-only — once a revision is frozen
    # (ready/live/archived) the stamped bundle sha is the source of truth
    # and neither the bundle nor the refs may move underneath it.

    _BUNDLE_EDIT_409_RESPONSE = OpenApiResponse(
        response=RevisionNotDraftErrorSerializer,
        description="The revision is frozen (ready/live/archived); clone a new draft and edit that instead.",
    )

    def _require_draft_or_409(self, revision: AgentRevision) -> Response | None:
        if revision.state == "draft":
            return None
        return Response(
            {
                "error": "revision_not_draft",
                "state": revision.state,
                "detail": (
                    f"Cannot edit the bundle on a '{revision.state}' revision. Clone a new draft and edit it instead."
                ),
            },
            status=status.HTTP_409_CONFLICT,
        )

    def _locked_repin_skill_refs(
        self,
        revision: AgentRevision,
        published_by_alias: dict[str, LLMSkill],
        appended_refs: list[dict[str, Any]] | None = None,
    ) -> Response | None:
        """Re-pin edited refs (and append new ones) under a row lock, re-checking
        draft state — a concurrent freeze could have sealed the revision since
        the unlocked gate, and writing refs onto a frozen row would desync the
        column from the sealed bundle (mirrors `set_skill_refs`). Returns the
        409 response when frozen, None on success. Store versions already
        published stay valid either way — they're append-only and merely go
        unreferenced.
        """
        with transaction.atomic(using=WRITER_DB):
            locked = AgentRevision.all_teams.using(WRITER_DB).select_for_update().get(pk=revision.pk)
            if locked.state != "draft":
                return self._require_draft_or_409(locked)
            refs = [dict(r) for r in (locked.skill_refs or [])]
            for ref in refs:
                alias = ref.get("alias")
                if not isinstance(alias, str):
                    continue
                published = published_by_alias.get(alias)
                if published is not None:
                    ref["version"] = published.version
                    ref["source_version_id"] = str(published.id)
            refs.extend(appended_refs or [])
            locked.skill_refs = refs
            locked.save(update_fields=["skill_refs"])
        return None

    def _publish_referenced_skill_edit(
        self, request: Request, revision: AgentRevision, alias: str, content: str
    ) -> Response | None:
        """Publish edited SKILL.md content as a new store version and re-pin the
        draft's ref to it. Returns the 409 response if the revision froze
        concurrently, None on success."""
        if alias in all_kernel_skill_ids():
            raise ValidationError(
                f"Skill '{alias}' is a platform kernel skill — its content is code-locked and cannot be edited."
            )
        ref = next((r for r in (revision.skill_refs or []) if r.get("alias") == alias), None)
        name = ref.get("from_template") if ref else None
        if not isinstance(name, str) or not name:
            raise ValidationError(
                f"Skill '{alias}' is not referenced by this revision. Add it via the skill_refs "
                "endpoint or bundle/import/ first."
            )
        assert_skills_writable(
            [name],
            scopes=get_authenticator_scopes(getattr(request, "successful_authenticator", None)),
            user_access_control=self.user_access_control,
        )
        published = publish_skill_md_edit(self.team, user=cast(User, request.user), skill_name=name, content=content)
        return self._locked_repin_skill_refs(revision, {alias: published})

    @extend_schema(
        request=UpdateBundleFileRequestSerializer,
        responses={200: AgentRevisionSerializer, 409: _BUNDLE_EDIT_409_RESPONSE},
    )
    @action(detail=True, methods=["put"], url_path="bundle/file")
    def update_bundle_file(self, request: Request, **kwargs) -> Response:
        """Update one `.md` file on a draft revision.

        `agent.md` writes go to the draft bundle. `skills/<id>/SKILL.md`
        writes are store-backed — skills are materialized from the skill
        store at freeze, so the edit publishes a new version of the
        referenced store skill and re-pins the draft's `skill_refs` entry
        to it. `<id>` must be a ref alias on this revision; add new skills
        via `bundle/import/` or `skill_refs`. Tool source / schema editing
        is out of scope here — use the per-tool endpoints. Returns the
        updated revision so the caller can refresh in one round-trip.
        """
        revision: AgentRevision = self.get_object()
        # Gate on draft state before validating the payload so a non-draft
        # revision always returns 409, never a 400 that hides the real reason
        # the request can't proceed.
        if (resp := self._require_draft_or_409(revision)) is not None:
            return resp

        body = UpdateBundleFileRequestSerializer(data=request.data)
        body.is_valid(raise_exception=True)

        path = body.validated_data["path"]
        content = body.validated_data["content"]

        if path == "agent.md":
            self._call(_janitor().put_agent_md, str(revision.id), content)
        elif (match := _SKILL_BODY_PATH_REGEX.fullmatch(path)) is not None:
            if (resp := self._publish_referenced_skill_edit(request, revision, match.group(1), content)) is not None:
                return resp
        else:
            raise ValidationError(
                f"Path '{path}' is not editable through this endpoint. "
                "Only 'agent.md' and 'skills/<id>/SKILL.md' are supported."
            )

        revision.refresh_from_db()
        return Response(AgentRevisionSerializer(revision, context=self.get_serializer_context()).data)

    @extend_schema(
        request=ImportBundleRequestSerializer,
        responses={200: AgentRevisionSerializer, 409: _BUNDLE_EDIT_409_RESPONSE},
    )
    @action(detail=True, methods=["post"], url_path="bundle/import")
    def import_bundle(self, request: Request, **kwargs) -> Response:
        """Bulk-merge a set of `.md` files into a draft revision.

        Sets `agent_md` on the draft bundle if present. `skills[]` are
        store-backed and merge by `id`: an id already referenced by the
        draft publishes a new version of its store skill; an unreferenced
        id attaches the store skill of that name (publishing the payload's
        body to it), or creates it when no such skill exists — and each
        ref is (re-)pinned to the published version. Skills not mentioned
        are left alone, so the import is safe to retry. Draft-only;
        non-draft revisions return 409 untouched.
        """
        revision: AgentRevision = self.get_object()
        # Gate on draft state before validating the payload so a non-draft
        # revision always returns 409, never a 400 that hides the real reason
        # the request can't proceed.
        if (resp := self._require_draft_or_409(revision)) is not None:
            return resp

        body = ImportBundleRequestSerializer(data=request.data)
        body.is_valid(raise_exception=True)

        agent_md = body.validated_data.get("agent_md")
        skills = body.validated_data.get("skills") or []

        # Validate everything up-front so a single bad entry rejects the whole
        # request before anything is published — callers expect "all-or-nothing"
        # semantics for the bulk paste. (Store publishes are append-only, so a
        # mid-flight failure can't corrupt existing versions, but half an
        # import is still a state the UI can't easily explain.)
        seen_ids: set[str] = set()
        for skill in skills:
            skill_id = skill["id"]
            if not _RESOURCE_ID_REGEX.fullmatch(skill_id):
                raise ValidationError(
                    f"Skill id '{skill_id}' is invalid. Use lowercase letters, "
                    "digits, hyphens, or underscores; must start and end with [a-z0-9]."
                )
            if skill_id in seen_ids:
                raise ValidationError(f"Skill id '{skill_id}' appears more than once in the import payload.")
            seen_ids.add(skill_id)
        kernel_collisions = sorted(seen_ids & all_kernel_skill_ids())
        if kernel_collisions:
            raise ValidationError(
                f"Skill id(s) {kernel_collisions} collide with platform kernel skills — pick different ids."
            )

        # Plan each entry against the refs and the store: an id already
        # referenced by the draft targets its ref's store skill; anything else
        # targets (or creates) the store skill of the same name and appends a
        # ref. New store skills must carry a description — there's no current
        # version to fall back to.
        refs_by_alias = {r.get("alias"): r for r in (revision.skill_refs or [])}
        plan: list[tuple[dict[str, Any], str, bool]] = []  # (payload entry, store name, exists in store)
        for skill in skills:
            skill_id = skill["id"]
            ref = refs_by_alias.get(skill_id)
            name = ref.get("from_template") if ref is not None else skill_id
            if not isinstance(name, str) or not name:
                raise ValidationError(f"Skill reference '{skill_id}' on this revision is malformed.")
            exists = ref is not None or store_skill_exists(self.team, name)
            if not exists and not skill.get("description"):
                raise ValidationError(f"Skill '{skill_id}' is new — `description` is required when adding a skill.")
            # Store-side caps (body size, description length, name format for
            # creates) checked up-front too, so a bad entry mid-payload can't
            # leave earlier entries already published.
            validate_store_write(skill["body"], skill.get("description"), new_skill_name=None if exists else name)
            plan.append((skill, name, exists))

        appended_count = sum(1 for entry, _, _ in plan if entry["id"] not in refs_by_alias)
        if len(revision.skill_refs or []) + appended_count > MAX_SKILL_REFS:
            raise ValidationError(f"A revision may reference at most {MAX_SKILL_REFS} store skills.")

        if plan:
            assert_skills_writable(
                [name for _, name, _ in plan],
                scopes=get_authenticator_scopes(getattr(request, "successful_authenticator", None)),
                user_access_control=self.user_access_control,
            )

        published_by_alias: dict[str, LLMSkill] = {}
        appended_refs: list[dict[str, Any]] = []
        user = cast(User, request.user)
        for skill, name, exists in plan:
            skill_id = skill["id"]
            if exists:
                published = publish_skill_body(
                    self.team, user=user, skill_name=name, body=skill["body"], description=skill.get("description")
                )
            else:
                published = create_store_skill(
                    self.team, user=user, name=name, description=skill["description"], body=skill["body"]
                )
            published_by_alias[skill_id] = published
            if skill_id not in refs_by_alias:
                appended_refs.append(
                    {
                        "from_template": name,
                        "alias": skill_id,
                        "version": published.version,
                        "source_version_id": str(published.id),
                    }
                )

        if (
            published_by_alias
            and (resp := self._locked_repin_skill_refs(revision, published_by_alias, appended_refs)) is not None
        ):
            return resp

        if agent_md is not None:
            self._call(_janitor().put_agent_md, str(revision.id), agent_md)

        revision.refresh_from_db()
        return Response(AgentRevisionSerializer(revision, context=self.get_serializer_context()).data)

    @extend_schema(
        request=DryRunToolRequestSerializer,
        responses=OpenApiResponse(
            response=inline_serializer(
                name="AgentRevisionDryRunToolResponse",
                fields={
                    "ok": drf_serializers.BooleanField(
                        help_text="True when the tool's `actions.default` returned without throwing. False when the tool threw or the sandbox rejected the invocation (the structured `error` describes which)."
                    ),
                    "tool_id": drf_serializers.CharField(help_text="Echo of the tool id from the URL."),
                    "result": drf_serializers.JSONField(
                        required=False,
                        help_text="Present on success — the value the tool's `actions.default` returned.",
                    ),
                    "error": inline_serializer(
                        name="AgentRevisionDryRunToolError",
                        fields={
                            "code": drf_serializers.CharField(
                                help_text=(
                                    "Stable error code. `sandbox_acquire_failed` — the platform could not start a "
                                    "sandbox (infrastructure issue, not tool code). `sandbox_invoke_failed` — the "
                                    "sandbox started but the invoke threw uncaught (problem in the tool body, or a "
                                    "runtime error). Dispatcher-side codes come through on `ok:false` invoke results: "
                                    "`timeout`, `secret_not_provisioned`, `action_not_found`, `tool_not_found`."
                                )
                            ),
                            "message": drf_serializers.CharField(help_text="One-line human-readable detail."),
                        },
                        required=False,
                    ),
                    "duration_ms": drf_serializers.IntegerField(
                        help_text=(
                            "Wall-clock duration in milliseconds, measured from sandbox acquire to after release. "
                            "Captured consistently across success, tool-throw, and acquire-failure paths so authors "
                            "can compare timings between calls. Always present."
                        )
                    ),
                },
            )
        ),
    )
    @action(detail=True, methods=["post"], url_path=r"tools/(?P<tool_id>[a-z0-9][a-z0-9_-]*)/dry_run")
    def dry_run_tool(self, request: Request, tool_id: str, **kwargs) -> Response:
        """Execute one persisted custom tool in a single-shot sandbox.

        Authoring loop's "test this tool" button. The tool's source must
        already be PUT (compiled.js is what runs); this just invokes it
        with the caller-supplied args and a stubbed ctx. No real secrets
        leave Django — `mock_secrets` is a `{name → placeholder}` map.
        """
        revision: AgentRevision = self.get_object()
        body = DryRunToolRequestSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        return Response(self._call(_janitor().dry_run_tool, str(revision.id), tool_id, body.validated_data))

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
        """Pre-flight checks before freeze + promote: agent.md exists,
        every native tool id is registered, every custom tool has its
        compiled.js + schema.json, every skill path exists, every declared
        secret has a value set in this revision's env block. Returns
        `{ ok, errors: [...] }`. Works on any revision state."""
        revision: AgentRevision = self.get_object()
        report = self._call(_janitor().validate, str(revision.id))
        errors = list(report.get("errors", []))

        # Secrets are per-revision now, so check this revision's own env block.
        available_keys = set(_decode_env_map(revision.encrypted_env).keys())
        for i, secret_entry in enumerate(revision.spec.get("secrets") or []):
            # spec.secrets[] entries are either bare strings (back-compat,
            # resolvable but no host binding) or {name, allowed_hosts}.
            # Both forms carry a name that must exist in encrypted_env.
            if isinstance(secret_entry, str):
                secret_name = secret_entry
            elif isinstance(secret_entry, dict):
                secret_name = secret_entry.get("name") or ""
            else:
                secret_name = ""
            if not secret_name:
                continue
            if secret_name not in available_keys:
                errors.append(
                    {
                        "code": "missing_secret",
                        "message": f'secret "{secret_name}" is not set in this revision\'s env',
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
        to the same session id rather than firing N times.
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
                            "bundle's `agent.md`, and the "
                            "skills index. Inspect before promotion to confirm "
                            "the model will see what you expect."
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

        Django is a thin proxy here: resolve template refs into the
        bundle, ask the janitor to seal it (the janitor returns the sha
        + the spec it derived from the typed resources), then stamp the
        row. No `transaction.atomic()` — the janitor's freeze is idempotent
        (on retry it re-reads the existing `.frozen` marker + re-derives
        spec), so a partial failure here is recoverable by re-calling
        freeze, not by transactional rollback. Holding an atomic block
        across the janitor HTTP call previously deadlocked the
        agent_revision row against the janitor's spec write — that's
        moved off the janitor side as part of the same fix.
        """
        revision: AgentRevision = self.get_object()
        # Only a draft can be frozen. Without this guard a freeze against an
        # archived/live revision would overwrite its state to "ready" — leaving
        # `application.live_revision` pointing at a now-"ready" row, which the
        # promote path doesn't expect. Mirrors the `update()` non-draft guard.
        if revision.state != "draft":
            raise ValidationError(f"Cannot freeze a {revision.state} revision; only 'draft' can be frozen.")
        skill_refs = revision.skill_refs or []
        # Re-bound the ref count here too: the serializer cap only guards
        # `set_skill_refs`, but refs reach the column via fork / raw write, and each
        # ref is one store fetch + one janitor round-trip, all sequential.
        if len(skill_refs) > MAX_SKILL_REFS:
            raise ValidationError(f"A revision may reference at most {MAX_SKILL_REFS} store skills.")
        # Authorize skill reads before materializing any store content into the
        # bundle — refs can reach the column via fork or raw write, so the
        # `set_skill_refs` check alone isn't enough. (Confused-deputy guard:
        # `agents:write` must not become a backdoor read of private skills.)
        assert_skill_refs_readable(
            self.team,
            skill_refs,
            scopes=get_authenticator_scopes(getattr(request, "successful_authenticator", None)),
            user_access_control=self.user_access_control,
        )
        janitor_client = _janitor()
        # Resolve every draft skill reference against the llma-skill store at its
        # pinned version, then materialize each into the bundle (SKILL.md +
        # companions) BEFORE sealing — so a frozen revision carries the exact
        # skill bytes and never re-resolves a possibly-changed skill at runtime.
        # Resolution is pure (no side effects) and runs to completion first, so a
        # missing/un-exportable/duplicate-alias ref fails the freeze before any
        # bundle write, never leaving the draft half-materialized. Alias
        # uniqueness is re-checked here because refs can reach the column via fork
        # or raw write, bypassing the `skill_refs` endpoint's validation.
        # (Custom-tool template pinning stays disabled pending a registry rethink
        # — see the commented-out template routes in routes.py.)
        resolved_skills = [resolve_skill_ref(self.team, ref) for ref in skill_refs]
        aliases = {r.alias for r in resolved_skills}
        if len(aliases) != len(resolved_skills):
            raise ValidationError("Each skill reference must have a unique 'alias' within the revision.")
        provenance_by_alias: dict[str, dict] = {
            r.alias: {"from_template": r.from_template, "version": r.version, "source_version_id": r.source_version_id}
            for r in resolved_skills
        }
        # Platform kernel skills — code-locked operator behaviour injected from
        # backend code, never authored through the API. The store (`skill_refs`)
        # is the only author path into `skills/`, so an author can't supply or
        # forge these; the freeze materializes them alongside the resolved store
        # skills below and merges both into the derived `spec.skills[]`. Empty for
        # any agent the platform hasn't designated (see logic/kernel_skills.py).
        # Per-slug targeting is safe to key on the slug only because human-readable
        # slugs are gated behind a first-party allowlist
        # (AGENT_PLATFORM_EXPLICIT_SLUG_TEAM_IDS); a normal team gets an opaque
        # server-minted slug it can't use to claim e.g. `agent-builder`.
        kernel_skills = kernel_skills_for(revision.application.slug)
        kernel_ids = {k.id for k in kernel_skills}
        collisions = sorted(kernel_ids & aliases)
        if collisions:
            raise ValidationError(
                f"Skill reference alias(es) {collisions} collide with a platform kernel skill id — "
                "rename the alias in `skill_refs`."
            )
        # Migration guard for pre-store agents: a revision forked from one authored
        # before the store became canonical carries inline skill entries in its
        # spec with no store provenance. Discriminate on `source_version_id`, NOT
        # `from_template`: `from_template` is author-writable on a draft spec (via
        # partial_update), so trusting it lets an author spoof provenance and make
        # the sweep silently drop the inline content this guard protects.
        # `source_version_id` is only ever server-stamped at freeze and is rejected
        # by the write spec schema (`additionalProperties: false`), so it can't be
        # forged. Detect from the spec (stable record) not the bundle, so a folder
        # left by a failed prior freeze — absent from the spec — is swept on retry
        # rather than misclassified as legacy. An unreferenced inline skill is
        # refused: silently dropping it would lose real content.
        #
        # Exempt ANY shipped kernel id (`all_kernel_ids`), not just this agent's
        # applicable set (`kernel_ids`): an inline entry whose id is a platform
        # kernel skill is platform-owned content the author can't author or remove
        # (there is no `skills` write path). It reaches a fork two ways the guard
        # must not brick — a kernel de-designated for this slug, or a cross-team
        # `clone_from` that lands an opaque slug no kernel targets. In both the id
        # is still a shipped kernel, so it's safe to let through: the sweep below
        # drops it from the bundle when it's no longer applicable, re-injecting only
        # what `kernel_ids` still designates. Only a genuinely deleted kernel folder
        # falls through to the legacy path, which is the honest outcome.
        all_kernel_ids = all_kernel_skill_ids()
        legacy_orphans = sorted(
            sid
            for s in ((revision.spec or {}).get("skills") or [])
            if (sid := s.get("id"))
            and not s.get("source_version_id")
            and sid not in aliases
            and sid not in all_kernel_ids
        )
        if legacy_orphans:
            raise ValidationError(
                f"Revision carries inline skill(s) {legacy_orphans} not backed by a store reference. "
                "These predate the skill store — recreate them in the store and set `skill_refs` before freezing."
            )
        # Materialize the resolved refs into the bundle, then seal. Skills are
        # store-only — nothing else writes `skills/` — so the frozen bundle must
        # hold exactly the current refs: sweep any folder not in `aliases`, then
        # (re-)write each resolved skill. This whole block is skipped if a prior
        # freeze already sealed the bundle (its HTTP response was lost): the
        # janitor refuses edits to a sealed bundle, and its `freeze` is idempotent
        # — it re-derives the sha + spec from what's already sealed.
        bundle_already_sealed = False
        try:
            manifest = janitor_client.manifest(str(revision.id))
            # Only `skills/<alias>/<file>` paths whose alias matches the janitor's
            # skill-id regex count — keeps Django's sweep set identical to the set
            # the janitor derives as skills, so a stray `skills/README.md` can't be
            # misread as an alias.
            bundle_aliases = {
                parts[1]
                for f in manifest.get("files", [])
                if len(parts := f["path"].split("/")) >= 3
                and parts[0] == "skills"
                and _RESOURCE_ID_REGEX.fullmatch(parts[1])
            }
            # Write the resolved skills BEFORE sweeping leftovers: a failure
            # mid-flight then leaves the bundle with extra folders, never missing a
            # current ref, and a retry is a clean full replace. Sweeping first would
            # leave a window where the draft has neither the old nor the new skill.
            for resolved in resolved_skills:
                janitor_client.put_skill(str(revision.id), resolved.alias, resolved.put_skill_payload())
            # Inject the platform kernel skills the same way — re-written from
            # backend code every freeze, so the frozen bundle always carries the
            # current bytes (never a stale DB copy) and stays in lockstep.
            for kskill in kernel_skills:
                janitor_client.put_skill(str(revision.id), kskill.id, kskill.put_skill_payload())
            # Sweep store-orphan folders, but keep the kernel folders just written:
            # `kernel_ids` are legitimate, not leftovers from a removed ref.
            for stale in bundle_aliases - aliases - kernel_ids:
                try:
                    janitor_client.delete_skill(str(revision.id), stale)
                except JanitorClientError as e:
                    # A folder with no `SKILL.md` (e.g. companion-only cruft) 404s on
                    # delete — it isn't a skill the janitor will remove, so treat it
                    # as already-swept rather than re-failing the freeze every retry.
                    if e.status_code != 404:
                        raise
        except JanitorClientError as e:
            # A 409 from an edit means the bundle is already sealed — fall through
            # to the idempotent freeze below. Any other error is a real failure.
            if not _is_sealed_bundle_conflict(e):
                raise JanitorUpstreamError(e) from e
            bundle_already_sealed = True
        result = self._call(janitor_client.freeze, str(revision.id))
        # Pin resolved versions back into `skill_refs` so an unpinned ref becomes a
        # concrete pin after its first freeze. A fork copies `skill_refs` verbatim,
        # so without this an unpinned ref would re-resolve "latest" on the fork's
        # freeze — drifting away from the bytes the parent shipped. `source_version_id`
        # makes the pin immortal (resolve_skill_ref prefers it over `version`).
        pinned_refs = [
            {**ref, "version": r.version, "source_version_id": r.source_version_id}
            for ref, r in zip(skill_refs, resolved_skills)
        ]
        fields: dict[str, Any] = {
            "state": "ready",
            "bundle_sha256": result["bundle_sha256"],
            "skill_refs": pinned_refs,
        }
        derived_spec = result.get("derived_spec")
        if derived_spec is not None:
            stamp_skill_provenance(derived_spec, provenance_by_alias)
            # Post-seal invariant: every kernel skill we injected must be present in
            # the sealed spec. A 2xx `put_skill` whose body didn't materialize (S3
            # eventual consistency, a future janitor derivation change) would
            # otherwise flip a `ready` agent live while silently missing a kernel
            # skill — e.g. `safety-and-boundaries`. Fail before the draft→ready flip
            # so the revision stays a draft and the freeze is retriable.
            #
            # Only enforce it when we actually (re)wrote the bundle this freeze. On
            # the sealed-bundle fall-through the bytes are immutable and `put_skill`
            # can no longer touch them — the freeze that sealed them already ran this
            # check. Re-running it here would permanently wedge the draft whenever
            # the kernel set drifted (grew/renamed) after that seal, or whenever a
            # concurrent freeze won the seal first — turning a lost-response retry
            # into a dead end. The conditional draft→ready UPDATE below is what keeps
            # concurrent freezes consistent in that case.
            if not bundle_already_sealed:
                materialized_ids = {s.get("id") for s in derived_spec.get("skills") or []}
                missing_kernel = sorted(kernel_ids - materialized_ids)
                if missing_kernel:
                    raise APIException(
                        detail=f"Freeze sealed without kernel skill(s) {missing_kernel}; materialization failed — "
                        "revision left in draft. Retry the freeze."
                    )
            fields["spec"] = derived_spec
        # Conditional draft→ready flip: only the first freeze of a draft wins, so
        # two concurrent freezes can't both stamp the row, and a `set_skill_refs`
        # that raced in can't leave `skill_refs` describing skills the sealed
        # bundle doesn't contain (this write reasserts the materialized set).
        updated = AgentRevision.all_teams.filter(pk=revision.pk, state="draft").update(**fields)
        # Read back from the writer: a replica read under lag could still show
        # `draft` right after our UPDATE and trip the conflict check below.
        revision.refresh_from_db(using=WRITER_DB)
        if not updated and revision.state not in ("ready", "live"):
            raise ValidationError(f"Revision is in state '{revision.state}'; only a 'draft' can be frozen.")
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
        source = AgentRevision.all_teams.filter(application__team_id=self.team_id, pk=source_id).first()
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

        application = AgentApplication.all_teams.filter(team_id=self.team_id, pk=application_id, archived=False).first()
        if application is None:
            raise NotFound("Application not found in this team.")
        source = AgentRevision.all_teams.filter(application__team_id=self.team_id, pk=source_id).first()
        if source is None:
            raise NotFound("Source revision not found in this team.")

        # bundle_uri convention: the runner-side bundle store resolves this.
        # In dev/CI we use a filesystem prefix derived from the app + new
        # revision id; prod swaps in the team's S3 prefix at deploy time.
        draft = AgentRevision.all_teams.create(
            application=application,
            team_id=application.team_id,
            parent_revision=source,
            created_by_id=self.request.user.id,
            state="draft",
            bundle_uri=source.bundle_uri,  # same bundle root; janitor scopes by revision_id
            spec=source.spec,
            # Carry store-skill references forward so a forked draft keeps (and can
            # re-resolve / re-pin) the same skills — they're the only skill source.
            skill_refs=source.skill_refs,
            # Secrets are per-revision: carry the parent's encrypted env forward
            # so the author isn't forced to re-enter every secret on each new
            # draft. The ciphertext copies verbatim (same EncryptedFields key
            # schedule); editing one revision's env never touches another's.
            encrypted_env=source.encrypted_env,
        )
        # The janitor clone is the side effect that gives the row meaning —
        # without it, the draft is an empty pointer. If it fails, drop the
        # row so retries don't accumulate orphans. We can't wrap in
        # transaction.atomic() because the HTTP call is the failure mode
        # we're guarding against; the row is committed first, then cleaned
        # up explicitly on error.
        try:
            self._call(_janitor().clone_from, str(draft.id), source_id)
        except Exception:
            draft.delete()
            raise
        return Response(
            {
                "revision": AgentRevisionSerializer(draft).data,
                "source_revision_id": source_id,
            },
            status=status.HTTP_201_CREATED,
        )


_MEMORY_HEADER_FIELDS: dict[str, drf_serializers.Field] = {
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
            AgentApplication.all_teams.filter(team_id=self.team_id, archived=False),
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
        GET /api/projects/<team>/agent_fleet/approvals/       — approval-gated tool requests across every agent in the team

    All three endpoints proxy the janitor (which owns the runtime DB). Used
    by the "fleet" overview to render the cards on the agents
    list without per-agent N+1.
    """

    scope_object = "agents"
    scope_object_read_actions = ["stats", "live_sessions", "approvals"]

    def _require_team_admin(self) -> None:
        """Mirror AgentApplicationViewSet — approvals are an admin-only surface."""
        membership = OrganizationMembership.objects.filter(
            user=cast(User, self.request.user), organization_id=self.organization_id
        ).first()
        if membership is None or membership.level < OrganizationMembership.Level.ADMIN:
            raise NotFound("Not found")

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
                                        "Trigger-specific metadata stamped at session creation. Discriminated on "
                                        "`kind`: chat | slack | cron | webhook | mcp. The Zod source of truth is "
                                        "`agent-shared/src/runtime/trigger-metadata.ts`; the node side validates "
                                        "and strips unknown keys at the persistence boundary, so consumers can "
                                        "trust `kind` and per-kind fields. TODO: narrow this DictField to a "
                                        "polymorphic serializer mirroring the union (needs `hogli build:openapi`)."
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

    @extend_schema(
        operation_id="agent_fleet_approvals_list",
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
            OpenApiParameter(
                "agent_id",
                OpenApiTypes.UUID,
                OpenApiParameter.QUERY,
                required=False,
                description="Optional agent UUID — narrows the listing to one application.",
            ),
            OpenApiParameter("limit", OpenApiTypes.INT, OpenApiParameter.QUERY, required=False),
            OpenApiParameter("offset", OpenApiTypes.INT, OpenApiParameter.QUERY, required=False),
        ],
        request=None,
        responses=OpenApiResponse(
            response=inline_serializer(
                name="AgentFleetApprovalsListResponse",
                fields={
                    "results": drf_serializers.ListField(
                        child=inline_serializer(
                            name="AgentFleetApprovalRequest",
                            fields=AgentApplicationViewSet._APPROVAL_RESPONSE_FIELDS,
                        ),
                        help_text="Approval requests across every agent in the team, newest first.",
                    ),
                },
            )
        ),
        description="Approval-gated tool requests across every agent in this team. Team-admin only.",
    )
    @action(detail=False, methods=["get"], url_path="approvals")
    def approvals(self, request: Request, **kwargs) -> Response:
        self._require_team_admin()
        limit_param = request.query_params.get("limit")
        offset_param = request.query_params.get("offset")
        try:
            limit = int(limit_param) if limit_param is not None else None
            offset = int(offset_param) if offset_param is not None else None
        except ValueError:
            raise ValidationError("limit and offset must be integers")
        try:
            payload = _janitor().list_approvals_for_team(
                int(self.team_id),
                application_id=request.query_params.get("agent_id") or None,
                state=request.query_params.get("state") or None,
                limit=limit,
                offset=offset,
            )
        except JanitorClientError as e:
            raise JanitorUpstreamError(e) from e
        return Response(payload)


# Suppress unused-import warning for the type re-export below.
_ = EncryptedTextField
