"""Exported enums for canvas."""

from posthog.enums import LabeledStrEnum


class ConnectorCallStatus(LabeledStrEnum):
    OK = "ok"
    NOT_CONNECTED = "not_connected"
    NEEDS_REAUTH = "needs_reauth"
    NEEDS_APPROVAL = "needs_approval"
    BLOCKED = "blocked"
    TOOL_MISSING = "tool_missing"
    WRITE_BLOCKED = "write_blocked"
    UPSTREAM_ERROR = "upstream_error"


class ConnectorKind(LabeledStrEnum):
    NATIVE = "native"
    MCP = "mcp"


class CanvasAccess(LabeledStrEnum):
    """Which canvases a request may reach, by the kind of operation it performs."""

    # Reads: list, retrieve, source, builds, state, and the other read actions.
    READ = "read"
    # Writes to the viewer's own runtime state.
    STATE = "state"
    # Content writes any member who sees the canvas may make: publish, edit, revert, and metadata updates.
    EDIT = "edit"
    # Other writes: error reports, fix and agent requests, actions, and connector calls.
    WRITE = "write"
    # Writes only the creator may make.
    DELETE = "delete"


# The labels repeat the values because the published OpenAPI enums list these exact pairs.
class CanvasKind(LabeledStrEnum):
    FREEFORM = "freeform", "freeform"
    GRID = "grid", "grid"
    COMPONENT = "component", "component"


class CanvasStateScope(LabeledStrEnum):
    USER = "user", "user"
    SHARED = "shared", "shared"


class CanvasPlacementStatus(LabeledStrEnum):
    PENDING = "pending", "pending"
    GENERATING = "generating", "generating"
    LIVE = "live", "live"
    FAILED = "failed", "failed"


CANVAS_KIND_FREEFORM = CanvasKind.FREEFORM.value
CANVAS_KIND_GRID = CanvasKind.GRID.value
CANVAS_KIND_COMPONENT = CanvasKind.COMPONENT.value
CANVAS_KINDS = CanvasKind.values

CANVAS_STATE_SCOPE_USER = CanvasStateScope.USER.value
CANVAS_STATE_SCOPE_SHARED = CanvasStateScope.SHARED.value
CANVAS_STATE_SCOPES = CanvasStateScope.values

CANVAS_BUILD_STATUS_READY = "ready"
CANVAS_BUILD_STATUS_FAILED = "failed"

TEACHING_CANVAS_NAME = "Explore PostHog Desktop"
