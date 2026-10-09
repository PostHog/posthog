"""Canvas facade API for cross-product access.

This module pulls the build path (and Temporal) onto import. Put reads that run at
``django.setup()`` or on hot request paths in ``facade/search.py`` or ``facade/access.py``.
"""

from typing import Any
from uuid import UUID

from django.http import Http404, HttpRequest

from posthog.auth import organization_disallows_public_sharing
from posthog.models.sharing_configuration import SharingConfiguration
from posthog.models.user import User

from products.canvas.backend import build_service
from products.canvas.backend.actions import canvas_actions_disabled as canvas_actions_disabled
from products.canvas.backend.artifacts import (
    canvas_artifact as _canvas_artifact,
    canvas_sandbox_document as _canvas_sandbox_document,
    create_canvas_sandbox_document_url as create_canvas_sandbox_document_url,
)
from products.canvas.backend.connectors import (
    call_connector_tool as call_connector_tool,
    canvas_connectors_enabled as canvas_connectors_enabled,
    connector_listings as connector_listings,
    mcp_provider_host as mcp_provider_host,
    native_connector_listings as native_connector_listings,
)
from products.canvas.backend.contract import (
    GRID_COLUMN_CHOICES as GRID_COLUMN_CHOICES,
    MAX_COMPONENT_HEIGHT as MAX_COMPONENT_HEIGHT,
    MAX_COMPONENT_WIDTH as MAX_COMPONENT_WIDTH,
    canvas_sdk_version as canvas_sdk_version,
    contract_limits as contract_limits,
)
from products.canvas.backend.facade.contracts import (
    CanvasArtifact,
    CanvasBuildCapacityExceeded,
    CanvasForkNotAllowedError,
    CanvasForkRecord,
    CanvasNotFoundError,
    CanvasNotPublishedError,
    CanvasViewer,
)
from products.canvas.backend.facade.enums import (
    CanvasAccess,
    ConnectorCallStatus as ConnectorCallStatus,
    ConnectorKind as ConnectorKind,
)
from products.canvas.backend.layout import (
    CANVAS_LAYOUT_SCHEMA_VERSION as CANVAS_LAYOUT_SCHEMA_VERSION,
    MAX_LAYOUT_PATCH_OPERATIONS as MAX_LAYOUT_PATCH_OPERATIONS,
    PLACEMENT_ID_RE as PLACEMENT_ID_RE,
    PLACEMENT_STATUSES as PLACEMENT_STATUSES,
    apply_layout_ops as apply_layout_ops,
    default_layout as default_layout,
    subtract_preexisting_diagnostics as subtract_preexisting_diagnostics,
    validate_layout as validate_layout,
    validate_layout_references as validate_layout_references,
)
from products.canvas.backend.logic.canvases import (
    count_canvases as count_canvases,
    create_canvas as create_canvas,
    delete_canvas as delete_canvas,
    get_canvas as get_canvas,
    home_canvas as home_canvas,
    list_canvases as list_canvases,
    provision_home_canvas as provision_home_canvas,
    update_canvas as update_canvas,
)
from products.canvas.backend.logic.records import canvas_record
from products.canvas.backend.logic.runtime import (
    action_required_scopes as action_required_scopes,
    action_starts_cloud_run as action_starts_cloud_run,
    call_connector as call_connector,
    execute_action as execute_action,
    list_actions as list_actions,
    prepare_agent_request as prepare_agent_request,
    prepare_fix_request as prepare_fix_request,
    read_state as read_state,
    read_state_value as read_state_value,
    report_error as report_error,
    set_state as set_state,
    validate_action as validate_action,
)
from products.canvas.backend.logic.sources import (
    build_action as build_action,
    canvas_builds as canvas_builds,
    create_draft as create_draft,
    head_layout as head_layout,
    head_source as head_source,
    list_drafts as list_drafts,
    list_versions as list_versions,
    open_canvas as open_canvas,
    promote_draft as promote_draft,
    publish_current_version as publish_current_version,
    publish_layout as publish_layout,
    publish_source as publish_source,
    read_layout as read_layout,
    read_source as read_source,
    revert as revert,
    wait_for_build as wait_for_build,
)
from products.canvas.backend.models import Canvas
from products.canvas.backend.sharing import (
    canvas_app_path as canvas_app_path,
    canvas_is_shareable,
)
from products.canvas.backend.source import (
    has_errors as has_errors,
    validate_source_project as validate_source_project,
)
from products.canvas.backend.source_edits import apply_source_edits as apply_source_edits
from products.canvas.backend.teaching import (
    RESERVED_TEMPLATE_IDS as RESERVED_TEMPLATE_IDS,
    seed_teaching_canvas as seed_teaching_canvas,
)
from products.tasks.backend.facade import api as tasks_facade


def fork_canvas(
    viewer: CanvasViewer,
    *,
    source_canvas_id: UUID | None,
    share_token: str | None,
    user_access_control: Any,
    was_impersonated: bool,
) -> CanvasForkRecord:
    if viewer.user_id is None or viewer.sandboxed:
        raise CanvasNotFoundError

    if source_canvas_id is not None:
        source_record = get_canvas(
            viewer,
            CanvasAccess.READ,
            source_canvas_id,
            user_access_control=user_access_control,
            required_level="viewer",
        )
        source = Canvas.objects.for_team(viewer.team_id).select_related("published_build").get(id=source_record.id)
        build = source.published_build
    elif share_token is not None:
        share = (
            SharingConfiguration.objects.filter(SharingConfiguration.tokens_active_q(), canvas__isnull=False)
            .select_related("canvas", "canvas__shared_build", "team__organization")
            .filter(access_token=share_token)
            .first()
        )
        source = share.canvas if share is not None else None
        if (
            share is None
            or source is None
            or not canvas_is_shareable(kind=source.kind, deleted=source.deleted)
            or organization_disallows_public_sharing(share)
        ):
            raise CanvasNotFoundError
        if not (share.settings or {}).get("allowForking"):
            raise CanvasForkNotAllowedError("The owner of this canvas hasn't allowed copies.")
        if share.password_required:
            raise CanvasForkNotAllowedError("Password-protected canvases can't be copied.")
        build = source.shared_build
    else:
        raise CanvasNotFoundError

    user = User.objects.get(id=viewer.user_id)
    channel_id = tasks_facade.ensure_personal_channel_id(viewer.team_id, user.id)
    try:
        fork = build_service.fork_canvas(
            source,
            build,
            team_id=viewer.team_id,
            channel_id=channel_id,
            created_by=user,
            was_impersonated=was_impersonated,
        )
    except build_service.CanvasNotPublished as error:
        raise CanvasNotPublishedError from error
    except build_service.CanvasBuildCapacityExceeded as error:
        raise CanvasBuildCapacityExceeded from error
    return CanvasForkRecord(
        canvas=canvas_record(fork.canvas),
        source_canvas_id=source.id,
        source_version_id=fork.canvas.forked_from_version_id,
        cross_team=source.team_id != viewer.team_id,
    )


def render_canvas_artifact(*, host: str, token: str, artifact_path: str, if_none_match: str | None) -> CanvasArtifact:
    request = HttpRequest()
    request.META["HTTP_HOST"] = host
    if if_none_match is not None:
        request.META["HTTP_IF_NONE_MATCH"] = if_none_match
    response = _canvas_artifact(request, token, artifact_path)
    return CanvasArtifact(
        status_code=response.status_code,
        body=response.content,
        headers=dict(response.items()),
    )


def render_canvas_sandbox_document(*, host: str, content_hash: str) -> CanvasArtifact | None:
    """The sandbox bootstrap document for `content_hash`, or None when this host or hash serves none."""
    request = HttpRequest()
    request.META["HTTP_HOST"] = host
    try:
        response = _canvas_sandbox_document(request, content_hash)
    except Http404:
        return None
    return CanvasArtifact(
        status_code=response.status_code,
        body=response.content,
        headers=dict(response.items()),
    )
