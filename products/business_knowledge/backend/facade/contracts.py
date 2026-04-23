"""
Contract types for business_knowledge.

Frozen dataclasses — the only shape other products (and our own presentation
layer) are allowed to see. No Django imports, no ORM instances.
"""

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True)
class KnowledgeSourceDTO:
    id: UUID
    team_id: int
    name: str
    source_type: str
    status: str
    error_message: str
    document_count: int
    chunk_count: int
    created_at: datetime
    updated_at: datetime | None
    # Stage 2a: URL sources. Empty string / None for text sources.
    source_url: str = ""
    last_refresh_at: datetime | None = None
    last_refresh_status: str = ""
    last_refresh_error: str = ""


@dataclass(frozen=True)
class CreateTextSourceInput:
    """
    Input for creating a text-type knowledge source. Team / user come from the
    request context; the serializer never trusts a client-provided team_id.
    """

    team_id: int
    created_by_id: int | None
    name: str
    text: str


@dataclass(frozen=True)
class UpdateTextSourceInput:
    """
    Input for updating a text-type knowledge source. Either field may be None
    to leave it untouched; when `text` is provided the source is re-chunked.
    """

    source_id: UUID
    team_id: int
    name: str | None
    text: str | None


@dataclass(frozen=True)
class CreateUrlSourceInput:
    """
    Input for creating a URL-type knowledge source. Team / user come from the
    request context; the serializer is the only layer that normalizes / validates
    the URL before it gets here (the logic layer still re-validates SSRF at
    fetch time — defense in depth).
    """

    team_id: int
    created_by_id: int | None
    name: str
    url: str


@dataclass(frozen=True)
class KnowledgeChunkPreviewDTO:
    """Slim projection returned on chunk previews (settings UI, debug)."""

    id: UUID
    source_id: UUID
    document_id: UUID
    heading_path: str
    ordinal: int
    content: str
    char_count: int


@dataclass(frozen=True)
class KnowledgePromptSection:
    """
    Rendered prompt fragment the support agent splices into its system prompt
    when a team has ≥1 ready KnowledgeSource. Populated by format_knowledge_prompt.
    """

    has_knowledge: bool
    prompt: str
    source_names: tuple[str, ...] = field(default_factory=tuple)
