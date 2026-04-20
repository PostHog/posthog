"""Shared type definitions for artifact system."""

from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict

from posthog.schema import (
    ArtifactSource,
    ErrorBlock,
    LoadingBlock,
    MarkdownBlock,
    NotebookArtifactContent,
    SessionReplayBlock,
    VisualizationArtifactContent,
    VisualizationBlock,
)

from posthog.models import Insight


class VisualizationRefBlock(BaseModel):
    """Reference to a visualization artifact - stored in DB, enriched to VisualizationBlock when streaming."""

    type: Literal["visualization_ref"] = "visualization_ref"
    artifact_id: str
    title: str | None = None


# Type alias for blocks that can be stored in a notebook artifact
StoredBlock = MarkdownBlock | VisualizationRefBlock | SessionReplayBlock | LoadingBlock

# Type alias for enriched blocks (after resolving refs)
EnrichedBlock = MarkdownBlock | VisualizationBlock | SessionReplayBlock | LoadingBlock | ErrorBlock


class StoredNotebookArtifactContent(BaseModel):
    """Notebook content as stored in the database - contains ref blocks that need enrichment."""

    content_type: Literal["notebook"] = "notebook"
    blocks: list[StoredBlock]
    title: str | None = None


# Content types for storage (includes StoredNotebookArtifactContent with ref blocks)
StoredContent = VisualizationArtifactContent | StoredNotebookArtifactContent

# Content types for streaming to frontend (enriched, no ref blocks)
ArtifactContent = VisualizationArtifactContent | NotebookArtifactContent


ContentT = TypeVar("ContentT", bound=ArtifactContent)

# Generic type vars for result wrappers (using StoredContent as bound to support notebooks)
T = TypeVar("T", bound=StoredContent)
S = TypeVar("S", bound=ArtifactSource)
M = TypeVar("M")


class StateArtifactResult(BaseModel, Generic[T]):
    source: Literal[ArtifactSource.STATE] = ArtifactSource.STATE
    content: T


class DatabaseArtifactResult(BaseModel, Generic[T]):
    source: Literal[ArtifactSource.ARTIFACT] = ArtifactSource.ARTIFACT
    content: T


class ModelArtifactResult(BaseModel, Generic[T, S, M]):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    source: S
    content: T
    model: M


# Result type for visualization artifacts (can come from state, database, or saved insights)
VisualizationWithSourceResult = (
    StateArtifactResult[VisualizationArtifactContent]
    | DatabaseArtifactResult[VisualizationArtifactContent]
    | ModelArtifactResult[VisualizationArtifactContent, Literal[ArtifactSource.INSIGHT], Insight]
)

# Result type for notebook artifacts (can only come from database)
NotebookWithSourceResult = DatabaseArtifactResult[StoredNotebookArtifactContent]

# Generic result type for any artifact
ArtifactWithSourceResult = VisualizationWithSourceResult | NotebookWithSourceResult
