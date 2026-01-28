from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Generic, TypeVar

from pydantic import BaseModel

from posthog.schema import ArtifactContentType

from posthog.models import Team

from ee.hogai.utils.types.base import AssistantMessageUnion
from ee.models.assistant import AgentArtifact

# Type variables for handler generics - bound to BaseModel for model_validate()
T_Stored = TypeVar("T_Stored", bound=BaseModel)  # Stored content type (in DB)
T_Enriched = TypeVar("T_Enriched", bound=BaseModel)  # Enriched content type (for streaming)
# TypeVar for decorator to preserve handler class type
T_Handler = TypeVar("T_Handler", bound="ArtifactHandler")


@dataclass
class EnrichmentContext:
    """Context passed to handlers during enrichment."""

    team: Team
    state_messages: Sequence[AssistantMessageUnion] | None = None


class ArtifactHandler(ABC, Generic[T_Stored, T_Enriched]):
    """
    Base class for artifact type handlers.

    Each artifact type (visualization, notebook, etc.) has a handler that:
    - Declares which sources it supports (STATE, ARTIFACT, INSIGHT)
    - Knows how to fetch from each source
    - Handles enrichment (e.g., resolving refs to full content)
    """

    # Type metadata - subclasses must define these
    content_class: type[T_Stored]
    enriched_class: type[T_Enriched]
    db_type: AgentArtifact.Type
    content_type: ArtifactContentType

    @abstractmethod
    async def alist(
        self,
        team: Team,
        ids: list[str],
        state_messages: Sequence[AssistantMessageUnion] | None = None,
    ) -> list[Any]:
        """
        Fetch content by IDs with source tracking.

        Args:
            team: Team context for DB queries
            ids: Artifact IDs to fetch
            state_messages: Optional state messages for STATE source lookup

        Returns:
            Ordered list matching input IDs (None for missing artifacts).
            Each handler returns its specific result wrapper type.
        """
        ...

    @abstractmethod
    async def aenrich(
        self,
        content: T_Stored,
        context: EnrichmentContext,
    ) -> T_Enriched:
        """
        Transform stored content to enriched content for streaming.

        For types where stored == enriched (e.g., visualizations), this is a no-op.
        For types with refs (e.g., notebooks), this resolves refs to full content.

        Args:
            content: The stored content to enrich
            context: Enrichment context with team and state messages

        Returns:
            Enriched content ready for streaming to frontend
        """
        ...

    def validate(self, data: dict) -> T_Stored:
        """
        Validate and parse raw data into content model.

        Args:
            data: Raw dict data (e.g., from DB JSON field)

        Returns:
            Validated content model instance
        """
        return self.content_class.model_validate(data)

    @abstractmethod
    def get_metadata(self, content: T_Stored) -> dict[str, Any]:
        """
        Extract display metadata from artifact content.

        Returns dict with type-specific fields for display (e.g., name, description, title).
        """
        ...


# Single registry mapping content class -> handler instance
HANDLER_REGISTRY: dict[type, ArtifactHandler] = {}


def register_handler(handler_class: type[T_Handler]) -> type[T_Handler]:
    """
    Class decorator to register a handler.

    Usage:
        @register_handler
        class VisualizationHandler(ArtifactHandler[...]):
            ...
    """
    instance = handler_class()
    HANDLER_REGISTRY[instance.content_class] = instance
    return handler_class


def get_handler_for_content_class(content_class: type) -> ArtifactHandler:
    """Get handler for a content class."""
    handler = HANDLER_REGISTRY.get(content_class)
    if handler is None:
        raise ValueError(f"Unknown content type={content_class.__name__}")
    return handler


def get_handler_for_db_type(db_type: AgentArtifact.Type) -> ArtifactHandler | None:
    """Get handler for a database type (iterates registry - only 2 handlers)."""
    for handler in HANDLER_REGISTRY.values():
        if handler.db_type == db_type:
            return handler
    return None


def get_handler_for_content_type(content_type: ArtifactContentType) -> ArtifactHandler | None:
    """Get handler for a content type enum (iterates registry - only 2 handlers)."""
    for handler in HANDLER_REGISTRY.values():
        if handler.content_type == content_type:
            return handler
    return None
