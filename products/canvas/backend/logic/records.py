"""Map canvas models to the facade contracts."""

from posthog.models.user import User

from products.canvas.backend.artifacts import create_canvas_artifact_url
from products.canvas.backend.capabilities import CapabilityWidening
from products.canvas.backend.facade.contracts import (
    CanvasBuildRecord,
    CanvasCapabilityWidening,
    CanvasRecord,
    CanvasStateEntry,
    CanvasUser,
    CanvasVersionRecord,
)
from products.canvas.backend.models import Canvas, CanvasBuild, CanvasSourceVersion, CanvasState


def user_record(user: User | None) -> CanvasUser | None:
    if user is None:
        return None
    return CanvasUser(
        id=user.id,
        uuid=user.uuid,
        distinct_id=user.distinct_id,
        first_name=user.first_name,
        last_name=user.last_name,
        email=user.email,
        is_email_verified=user.is_email_verified,
        hedgehog_config=user.hedgehog_config,
        role_at_organization=user.role_at_organization,
    )


def canvas_record(canvas: Canvas) -> CanvasRecord:
    """Reads `created_by` and `current_source_version`; select them with the canvas."""
    head = canvas.current_source_version
    return CanvasRecord(
        id=canvas.id,
        team_id=canvas.team_id,
        channel_id=canvas.channel_id,
        name=canvas.name,
        description=canvas.description,
        kind=canvas.kind,
        template_id=canvas.template_id,
        generation_task_id=canvas.generation_task_id,
        pinned_at=canvas.pinned_at,
        current_source_version_id=canvas.current_source_version_id,
        published_build_id=canvas.published_build_id,
        shared_build_id=canvas.shared_build_id,
        forked_from_canvas_id=canvas.forked_from_canvas_id,
        forked_from_version_id=canvas.forked_from_version_id,
        created_by_id=canvas.created_by_id,
        created_by=user_record(canvas.created_by),
        created_at=canvas.created_at,
        updated_at=canvas.updated_at,
        component_meta=head.component_meta if head is not None and canvas.kind == Canvas.KIND_COMPONENT else None,
        head_capabilities=head.capabilities if head is not None else None,
    )


def artifact_url(build: CanvasBuild) -> str | None:
    # artifact_object_prefix is cleared by retention once a ready build's
    # objects are pruned; the artifact view 404s on it, so don't advertise a
    # URL that can't be served.
    if (
        build.status != CanvasBuild.STATUS_READY
        or not build.artifact_object_prefix
        or not isinstance(build.manifest, dict)
    ):
        return None
    entry = build.manifest.get("entryHtml")
    if not isinstance(entry, str):
        return None
    return create_canvas_artifact_url(build, entry)


def build_record(build: CanvasBuild) -> CanvasBuildRecord:
    return CanvasBuildRecord(
        id=build.id,
        canvas_id=build.canvas_id,
        source_version_id=build.source_version_id,
        status=build.status,
        diagnostics=build.diagnostics or [],
        manifest=build.manifest,
        integrity=build.integrity,
        artifact_url=artifact_url(build),
        pinned=build.pinned,
        created_at=build.created_at,
        finished_at=build.finished_at,
    )


def version_record(version: CanvasSourceVersion) -> CanvasVersionRecord:
    """Reads `created_by`; select it with the version."""
    return CanvasVersionRecord(
        id=version.id,
        parent_version_id=version.parent_version_id,
        prompt=version.prompt,
        task_id=version.task_id,
        draft=version.draft,
        created_by=user_record(version.created_by),
        created_at=version.created_at,
    )


def widening_record(widening: CapabilityWidening) -> CanvasCapabilityWidening:
    return CanvasCapabilityWidening(
        widens=widening.widens,
        insights_added=widening.insights_added,
        capture_events_added=widening.capture_events_added,
        inline_queries_enabled=widening.inline_queries_enabled,
        agent_requests_enabled=widening.agent_requests_enabled,
        network_origins_added=widening.network_origins_added,
        state_scopes_added=widening.state_scopes_added,
        actions_added=widening.actions_added,
        connectors_added=[{"provider": grant.provider, "tools": grant.tools} for grant in widening.connectors_added],
    )


def state_entry_record(entry: CanvasState) -> CanvasStateEntry:
    return CanvasStateEntry(scope=entry.scope, key=entry.key, value=entry.value, updated_at=entry.updated_at)
