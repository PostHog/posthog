"""Contract types for canvas.

Framework-free frozen dataclasses that define what this product exposes to the rest
of the codebase. No Django imports.

They use ``pydantic.dataclasses.dataclass`` rather than the stdlib variant: same
syntax, but with runtime validation on construction, so a mapper that hands a
contract the wrong shape fails at the facade boundary instead of in a consumer.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic.dataclasses import dataclass


@dataclass(frozen=True)
class CanvasSearchRecord:
    """The fields the tasks search index stores for a canvas."""

    id: UUID
    team_id: int
    name: str
    channel_id: UUID
    kind: str
    template_id: str


@dataclass(frozen=True)
class CanvasSummary:
    """The fields another product shows when it names or links to a canvas."""

    id: UUID
    name: str
    channel_id: UUID
    channel_name: str


@dataclass(frozen=True)
class CanvasOwnerActivity:
    """When a person last changed a canvas they own in a channel."""

    channel_id: UUID
    created_by_id: int
    last_active: datetime


@dataclass(frozen=True)
class CanvasGenerationState:
    current_source_version_id: UUID | None
    artifact_url: str | None
    build_status: str | None
    build_error: str | None
    build_hash: str | None = None


@dataclass(frozen=True)
class NotebookCanvasVersion:
    id: UUID
    build_status: str | None
    artifact_url: str | None
    build_hash: str | None = None


@dataclass(frozen=True)
class CanvasArtifact:
    """The framework-free result returned when reading a built artifact."""

    status_code: int
    body: bytes
    headers: dict[str, str]


@dataclass(frozen=True)
class StagedCanvasSourceUpload:
    """A source project object that canvas has uploaded but not yet committed to a version."""

    key: str
    digest: str
    size: int


@dataclass(frozen=True)
class PreparedNotebookCanvasSource:
    """A validated notebook widget source, staged in object storage.

    Hand it back to ``publish_prepared_notebook_canvas_source`` or
    ``publish_prepared_notebook_canvas_draft`` inside ``notebook_canvas_source_transaction``.
    """

    canvas_id: UUID
    expected_current_version_id: UUID | None
    prompt: str
    name: str
    project: dict[str, Any]
    source_upload: StagedCanvasSourceUpload
    legacy_upload: StagedCanvasSourceUpload | None


class NotebookCanvasError(Exception):
    pass


class NotebookCanvasNotFoundError(NotebookCanvasError):
    pass


class NotebookCanvasVersionConflictError(NotebookCanvasError):
    pass


class NotebookCanvasBuildCapacityError(NotebookCanvasError):
    pass


class NotebookCanvasSourceInvalidError(NotebookCanvasError):
    pass


@dataclass(frozen=True)
class CanvasViewer:
    """Who is calling the canvas API, as the access rules see them."""

    team_id: int
    user_id: int | None
    # True for a task sandbox's OAuth token, even when the task binding fails.
    sandboxed: bool
    # The sandbox's bound task, or None when the binding does not hold.
    sandbox_task_id: UUID | None


@dataclass(frozen=True)
class CanvasUser:
    """The user fields canvas responses show for a creator."""

    id: int
    uuid: UUID
    distinct_id: str | None
    first_name: str
    last_name: str
    email: str
    is_email_verified: bool | None
    hedgehog_config: dict[str, Any] | None
    role_at_organization: str | None


@dataclass(frozen=True)
class CanvasRecord:
    """One canvas, with the head version fields its API responses and access rules read."""

    id: UUID
    team_id: int
    channel_id: UUID
    name: str
    description: str
    kind: str
    template_id: str
    generation_task_id: UUID | None
    pinned_at: datetime | None
    current_source_version_id: UUID | None
    published_build_id: UUID | None
    created_by_id: int | None
    created_by: CanvasUser | None
    created_at: datetime
    updated_at: datetime
    # The head version's placement contract; set only for component canvases.
    component_meta: dict[str, Any] | None
    # The head version's declared capabilities, or None before the first publish.
    head_capabilities: dict[str, Any] | None


@dataclass(frozen=True)
class CanvasPage:
    results: list[CanvasRecord]
    count: int


@dataclass(frozen=True)
class CanvasBuildRecord:
    id: UUID
    canvas_id: UUID
    source_version_id: UUID | None
    status: str
    diagnostics: list[Any]
    manifest: dict[str, Any] | None
    integrity: str | None
    # A signed URL for the entry HTML of a ready build whose artifacts are still retained.
    artifact_url: str | None
    pinned: bool
    created_at: datetime
    finished_at: datetime | None


@dataclass(frozen=True)
class CanvasVersionRecord:
    id: UUID
    parent_version_id: UUID | None
    prompt: str | None
    task_id: UUID | None
    draft: bool
    created_by: CanvasUser | None
    created_at: datetime


@dataclass(frozen=True)
class CanvasDraftRecord:
    version_id: str
    prompt: str | None
    created_by: CanvasUser | None
    created_at: datetime
    build_status: str | None
    build_id: str | None


@dataclass(frozen=True)
class CanvasComponentLifecycle:
    canvas_id: str
    requested_version_id: str | None
    published_build_id: str | None
    current_version_id: str | None
    builds: list[CanvasBuildRecord]


@dataclass(frozen=True)
class CanvasOpenState:
    """Everything a client needs to open a canvas in one round trip."""

    canvas: CanvasRecord
    published_build: CanvasBuildRecord | None
    current_version_id: str | None
    has_active_build: bool
    source: dict[str, Any] | None
    layout: dict[str, Any] | None
    component_lifecycles: list[CanvasComponentLifecycle] | None
    # True when object storage failed, so the payload lacks its source or layout.
    degraded: bool


@dataclass(frozen=True)
class CanvasBuildsState:
    published_build_id: str | None
    current_version_id: str | None
    builds: list[CanvasBuildRecord]


@dataclass(frozen=True)
class CanvasLayoutState:
    layout: dict[str, Any]
    component_lifecycles: list[CanvasComponentLifecycle] | None


@dataclass(frozen=True)
class CanvasPublishResult:
    canvas: CanvasRecord
    version_id: UUID
    version_capabilities: dict[str, Any] | None
    source_size: int | None
    build: CanvasBuildRecord
    first_publish: bool


@dataclass(frozen=True)
class CanvasCapabilityWidening:
    widens: bool
    insights_added: list[str]
    capture_events_added: list[str]
    inline_queries_enabled: bool
    agent_requests_enabled: bool
    network_origins_added: list[str]
    state_scopes_added: list[str]
    actions_added: list[str]
    connectors_added: list[dict[str, Any]]


@dataclass(frozen=True)
class CanvasDraftResult:
    version_id: UUID
    build: CanvasBuildRecord
    capability_widening: CanvasCapabilityWidening


@dataclass(frozen=True)
class CanvasBuildMove:
    """The canvas and build after a promote, revert, or current-version publish."""

    canvas: CanvasRecord
    build: CanvasBuildRecord


@dataclass(frozen=True)
class CanvasLayoutPublishResult:
    canvas: CanvasRecord
    version_id: UUID


@dataclass(frozen=True)
class CanvasFieldChange:
    field: str
    before: Any
    after: Any


@dataclass(frozen=True)
class CanvasUpdateResult:
    canvas: CanvasRecord
    changes: list[CanvasFieldChange]


@dataclass(frozen=True)
class CanvasErrorReport:
    build_id: UUID
    error_type: str
    outcome: str


@dataclass(frozen=True)
class CanvasFixRequest:
    """What a fix dispatch needs. `task_id` is None when the canvas has no authoring task."""

    build_id: UUID
    task_id: UUID | None
    error_type: str
    prompt: str


@dataclass(frozen=True)
class CanvasAgentRequest:
    task_id: UUID | None
    prompt: str


@dataclass(frozen=True)
class CanvasStateEntry:
    scope: str
    key: str
    value: Any
    updated_at: datetime


class CanvasNotFoundError(Exception):
    pass


class CanvasVersionNotFoundError(Exception):
    pass


class CanvasBuildNotFoundError(Exception):
    pass


class CanvasStateNotFoundError(Exception):
    pass


class CanvasBuildCapacityExceeded(Exception):
    """The team already has the maximum number of in-flight builds."""


class CanvasVersionConflict(Exception):
    """A guarded publish was based on a version that is no longer the head."""

    def __init__(self, current_version_id: str | None) -> None:
        super().__init__("The canvas changed since it was read.")
        self.current_version_id = current_version_id


class CanvasRequestRejected(Exception):
    """A canvas rule refused the request. The view returns `detail` with `status_code`."""

    def __init__(self, status_code: int, detail: str, body: dict[str, Any] | None = None) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail
        # The complete response body, when it holds more than `detail`.
        self.body = body if body is not None else {"detail": detail}
