"""Contract types for canvas.

Framework-free frozen dataclasses that define what this product exposes to the rest
of the codebase. No Django imports.

They use ``pydantic.dataclasses.dataclass`` rather than the stdlib variant: same
syntax, but with runtime validation on construction, so a mapper that hands a
contract the wrong shape fails at the facade boundary instead of in a consumer.
"""

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
