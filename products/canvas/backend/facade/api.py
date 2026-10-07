"""Canvas facade API for cross-product access.

This module pulls the build path (and Temporal) onto import. Put reads that run at
``django.setup()`` or on hot request paths in ``facade/search.py`` or ``facade/access.py``.
"""

from django.http import Http404, HttpRequest

from products.canvas.backend.actions import canvas_actions_disabled as canvas_actions_disabled
from products.canvas.backend.artifacts import (
    ARTIFACT_PERMISSIONS_POLICY as ARTIFACT_PERMISSIONS_POLICY,
    _artifact_origin,
    _require_artifact_host,
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
from products.canvas.backend.facade.contracts import CanvasArtifact
from products.canvas.backend.facade.enums import (
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
from products.canvas.backend.source import (
    has_errors as has_errors,
    validate_source_project as validate_source_project,
)
from products.canvas.backend.source_edits import apply_source_edits as apply_source_edits
from products.canvas.backend.teaching import (
    RESERVED_TEMPLATE_IDS as RESERVED_TEMPLATE_IDS,
    seed_teaching_canvas as seed_teaching_canvas,
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


def artifact_delivery_origin() -> str:
    return _artifact_origin()


def require_artifact_host(host: str) -> None:
    _require_artifact_host(host)
