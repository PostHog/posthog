"""What a rendered canvas does at runtime: error reports, agent requests, actions, connectors, and state."""

import json
from typing import Any
from uuid import UUID

from django.db import connection, transaction
from django.db.models import Q, QuerySet

from rest_framework import status

from products.canvas.backend import error_reports
from products.canvas.backend.actions import CANVAS_ACTIONS, CanvasActionDenied
from products.canvas.backend.capabilities import declared_actions, declared_connectors, declared_state_scopes
from products.canvas.backend.connectors import ConnectorCallResult, call_connector_tool
from products.canvas.backend.contract import contract_limits
from products.canvas.backend.facade.contracts import (
    CanvasAgentRequest,
    CanvasBuildNotFoundError,
    CanvasErrorReport,
    CanvasFixRequest,
    CanvasRequestRejected,
    CanvasStateEntry,
    CanvasStateNotFoundError,
)
from products.canvas.backend.logic.canvases import canvas_row
from products.canvas.backend.logic.records import state_entry_record
from products.canvas.backend.models import Canvas, CanvasBuild, CanvasState
from products.canvas.backend.state_reads import CanvasStateReader

# Write-time bounds on canvas runtime state (ph.state), from the platform
# contract so the desktop bridge mirrors them instead of restating numbers.
# They keep every access a point lookup and cap table growth by canvas count.
CANVAS_STATE_MAX_VALUE_BYTES = contract_limits()["maxStateValueBytes"]
CANVAS_STATE_MAX_KEYS_PER_SCOPE = contract_limits()["maxStateKeysPerScope"]

_SHARED_STATE_WITH_CONNECTORS = "Canvases with connectors cannot use shared state."


def _canvas_build(team_id: int, canvas_id: UUID, build_id: UUID) -> CanvasBuild:
    build = (
        CanvasBuild.objects.for_team(team_id)
        .select_related("source_version")
        .filter(id=build_id, canvas_id=canvas_id)
        .first()
    )
    if build is None:
        raise CanvasBuildNotFoundError
    return build


def report_error(team_id: int, canvas_id: UUID, build_id: UUID, raw_error_type: str) -> CanvasErrorReport:
    """File a runtime error of one build in the authoring task's thread."""
    canvas = canvas_row(team_id, canvas_id)
    build = _canvas_build(team_id, canvas_id, build_id)
    error_type = error_reports.sanitize_error_type(raw_error_type)
    outcome = error_reports.report_runtime_error(canvas, build, error_type)
    return CanvasErrorReport(build_id=build.id, error_type=error_type, outcome=outcome)


def prepare_fix_request(team_id: int, canvas_id: UUID, build_id: UUID, raw_error_type: str | None) -> CanvasFixRequest:
    """The authoring task and the agent prompt for a fix of one build."""
    canvas = canvas_row(team_id, canvas_id)
    build = _canvas_build(team_id, canvas_id, build_id)
    is_build_failure = build.status == CanvasBuild.STATUS_FAILED and not raw_error_type
    error_type = (
        error_reports.BUILD_FAILURE_ERROR_TYPE
        if is_build_failure
        else error_reports.sanitize_error_type(raw_error_type)
    )
    return CanvasFixRequest(
        build_id=build.id,
        task_id=error_reports.authoring_task_id(canvas, build),
        error_type=error_type,
        prompt=error_reports.build_fix_prompt(
            canvas,
            build_id=str(build.id),
            source_version_id=str(build.source_version_id) if build.source_version_id else None,
            error_type=error_type,
            origin="build" if is_build_failure else "runtime",
            error_codes=error_reports.diagnostic_error_codes(build.diagnostics),
        ),
    )


def prepare_agent_request(team_id: int, canvas_id: UUID, viewer_prompt: str) -> CanvasAgentRequest:
    """The authoring task and the agent prompt for a viewer's change request."""
    canvas = (
        Canvas.objects.unscoped().select_related("published_build__source_version").get(team_id=team_id, id=canvas_id)
    )
    return CanvasAgentRequest(
        task_id=error_reports.authoring_task_id(canvas, canvas.published_build),
        prompt=error_reports.build_agent_request_prompt(canvas, viewer_prompt),
    )


def list_actions() -> list[dict[str, Any]]:
    return [
        {
            "verb": entry.verb,
            "summary": entry.summary,
            "destructive": entry.destructive,
            "starts_cloud_run": entry.starts_cloud_run,
            "usage": entry.usage,
        }
        for entry in sorted(CANVAS_ACTIONS.values(), key=lambda entry: entry.verb)
    ]


def action_required_scopes(verb: str) -> list[str] | None:
    """The API scopes a scoped credential needs to invoke `verb`, or None for an unknown verb."""
    entry = CANVAS_ACTIONS.get(verb)
    return ["canvas:write", *entry.required_scopes] if entry is not None else None


def validate_action(capabilities: dict[str, Any] | None, verb: str, payload: dict[str, Any]) -> dict[str, Any]:
    """The verb's validated payload. Raises CanvasRequestRejected, or a DRF ValidationError for the payload."""
    entry = CANVAS_ACTIONS.get(verb)
    if entry is None:
        raise CanvasRequestRejected(
            status.HTTP_400_BAD_REQUEST,
            f'Unknown action verb "{verb}". Registered verbs: {", ".join(sorted(CANVAS_ACTIONS))}.',
        )
    if verb not in declared_actions(capabilities):
        raise CanvasRequestRejected(
            status.HTTP_403_FORBIDDEN,
            f'The canvas does not declare action "{verb}". Add it to capabilities.posthog.actions and publish.',
        )
    verb_payload = entry.payload_serializer(data=payload)
    verb_payload.is_valid(raise_exception=True)
    return verb_payload.validated_data


def action_starts_cloud_run(verb: str) -> bool:
    entry = CANVAS_ACTIONS.get(verb)
    return entry is not None and entry.starts_cloud_run


def execute_action(team_id: int, user_id: int, canvas_id: UUID, verb: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Run a validated verb as the viewer. Raises CanvasRequestRejected, or ValueError for a bad payload."""
    try:
        return CANVAS_ACTIONS[verb].execute(team_id, user_id, canvas_row(team_id, canvas_id), payload)
    except CanvasActionDenied as error:
        body = error.response.data if isinstance(error.response.data, dict) else {"detail": str(error.response.data)}
        raise CanvasRequestRejected(error.response.status_code, str(body.get("detail", "")), body=body) from error


def call_connector(
    team_id: int,
    user_id: int,
    *,
    actor_label: str,
    canvas_id: UUID,
    head_version_id: UUID | None,
    capabilities: dict[str, Any] | None,
    provider: str,
    tool: str,
    arguments: dict[str, Any],
    approval_token: str | None,
) -> ConnectorCallResult:
    """Call one declared connector tool as the viewer. Raises CanvasRequestRejected for an undeclared tool."""
    declared = declared_connectors(capabilities)
    if "shared" in declared_state_scopes(capabilities):
        raise CanvasRequestRejected(status.HTTP_403_FORBIDDEN, _SHARED_STATE_WITH_CONNECTORS)
    if tool not in declared.get(provider, set()):
        raise CanvasRequestRejected(
            status.HTTP_403_FORBIDDEN,
            f'The canvas does not declare connector tool "{tool}" on "{provider}". '
            "Add it to capabilities.connectors and publish.",
        )
    return call_connector_tool(
        team_id,
        user_id,
        provider,
        tool,
        arguments,
        actor_label=actor_label,
        approval_token=approval_token,
        approval_context=f"{canvas_id}:{head_version_id or ''}",
    )


def _lock_state_scope(canvas_id: UUID, scope: str, owner_id: int | None) -> None:
    """Hold a transaction-scoped advisory lock on one canvas state scope of one owner."""
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            [f"canvas_state:{canvas_id}:{scope}:{owner_id if owner_id is not None else 'shared'}"],
        )


def _readable_state(
    team_id: int, user_id: int, canvas_id: UUID, capabilities: dict[str, Any] | None
) -> QuerySet[CanvasState]:
    # Reads honor the same reviewed boundary as writes: a canvas only sees
    # the scopes its head version declares, so narrowing capabilities also
    # stops reads of previously written entries.
    declared = declared_state_scopes(capabilities)
    # Shared state is one value for every viewer, so a canvas that also calls
    # connectors with each viewer's own connection could pass one viewer's data to another.
    if declared_connectors(capabilities):
        declared = declared - {CanvasState.SCOPE_SHARED}
    readable = Q(scope=CanvasState.SCOPE_SHARED, user__isnull=True) | Q(scope=CanvasState.SCOPE_USER, user_id=user_id)
    return CanvasState.objects.for_team(team_id).filter(readable, canvas_id=canvas_id, scope__in=declared)


def read_state(
    team_id: int, user_id: int, canvas_id: UUID, capabilities: dict[str, Any] | None, **query: Any
) -> dict[str, Any]:
    """The shared entries plus the viewer's own entries, filtered and paged by `query`."""
    return CanvasStateReader.entries(_readable_state(team_id, user_id, canvas_id, capabilities), **query)


def read_state_value(
    team_id: int,
    user_id: int,
    canvas_id: UUID,
    capabilities: dict[str, Any] | None,
    *,
    scope: str,
    key: str,
    offset: int,
    limit: int,
) -> dict[str, Any]:
    """One chunk of one readable value. Raises CanvasStateNotFoundError when the viewer cannot read it."""
    entry = _readable_state(team_id, user_id, canvas_id, capabilities).filter(scope=scope, key=key).first()
    if entry is None:
        raise CanvasStateNotFoundError
    return CanvasStateReader.value(entry, offset=offset, limit=limit)


def set_state(
    team_id: int,
    user_id: int,
    canvas_id: UUID,
    capabilities: dict[str, Any] | None,
    *,
    scope: str,
    key: str,
    value: Any,
) -> CanvasStateEntry | None:
    """Write one key, or delete it when `value` is None. Returns None for a delete."""
    # The head version's declared capabilities gate writes: state is part of
    # the canvas's reviewed permission boundary, exactly like insights.
    declared = declared_state_scopes(capabilities)
    if scope == CanvasState.SCOPE_SHARED and declared_connectors(capabilities):
        raise CanvasRequestRejected(status.HTTP_403_FORBIDDEN, _SHARED_STATE_WITH_CONNECTORS)
    if scope not in declared:
        raise CanvasRequestRejected(
            status.HTTP_403_FORBIDDEN,
            f'The canvas does not declare state scope "{scope}". Add it to capabilities.posthog.state and publish.',
        )
    owner_id = user_id if scope == CanvasState.SCOPE_USER else None
    scoped = CanvasState.objects.for_team(team_id).filter(canvas_id=canvas_id, scope=scope)
    scoped = scoped.filter(user_id=owner_id) if owner_id is not None else scoped.filter(user__isnull=True)
    existing = scoped.filter(key=key)
    if value is None:
        existing.delete()
        return None
    if len(json.dumps(value, separators=(",", ":")).encode()) > CANVAS_STATE_MAX_VALUE_BYTES:
        raise CanvasRequestRejected(
            status.HTTP_400_BAD_REQUEST,
            f"State values are capped at {CANVAS_STATE_MAX_VALUE_BYTES // 1024} KB serialized. "
            "Store large data in PostHog (insights, the warehouse) and reference it.",
        )
    with transaction.atomic():
        # The key-count check needs a mutex: without it, concurrent new-key writes
        # both observe space and overshoot the cap. The cap applies per canvas,
        # scope, and owner, so the lock has the same key and writes to other
        # viewers' state do not wait on it.
        _lock_state_scope(canvas_id, scope, owner_id)
        if not existing.exists() and scoped.count() >= CANVAS_STATE_MAX_KEYS_PER_SCOPE:
            raise CanvasRequestRejected(
                status.HTTP_400_BAD_REQUEST,
                f"A canvas may hold at most {CANVAS_STATE_MAX_KEYS_PER_SCOPE} state keys "
                "per scope. Delete keys (set them to null) or consolidate values.",
            )
        owner: dict[str, Any] = {"user_id": owner_id}
        entry, _ = CanvasState.objects.for_team(team_id).update_or_create(
            team_id=team_id, canvas_id=canvas_id, scope=scope, key=key, defaults={"value": value}, **owner
        )
    return state_entry_record(entry)
