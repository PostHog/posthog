"""Canvas facade API for cross-product access.

This module pulls the build path (and Temporal) onto import. Put reads that run at
``django.setup()`` or on hot request paths in ``facade/search.py`` or ``facade/access.py``.
"""

from django.http import HttpRequest

from products.canvas.backend.artifacts import canvas_artifact as _canvas_artifact
from products.canvas.backend.connectors import (
    call_connector_tool as call_connector_tool,
    canvas_connectors_enabled as canvas_connectors_enabled,
    connector_listings as connector_listings,
    mcp_provider_host as mcp_provider_host,
    native_connector_listings as native_connector_listings,
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
from products.canvas.backend.source_edits import apply_source_edits as apply_source_edits
from products.canvas.backend.state_reads import CanvasStateReader as CanvasStateReader
from products.canvas.backend.teaching import (
    RESERVED_TEMPLATE_IDS as RESERVED_TEMPLATE_IDS,
    TEACHING_CANVAS_NAME as TEACHING_CANVAS_NAME,
    seed_teaching_canvas as seed_teaching_canvas,
)
from products.canvas.backend.welcome import seed_home_canvas as seed_home_canvas


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
