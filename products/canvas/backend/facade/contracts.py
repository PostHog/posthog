"""Contract types for canvas.

Framework-free frozen dataclasses that define what this product exposes to the rest
of the codebase. No Django imports.

They use ``pydantic.dataclasses.dataclass`` rather than the stdlib variant: same
syntax, but with runtime validation on construction, so a mapper that hands a
contract the wrong shape fails at the facade boundary instead of in a consumer.
"""

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
