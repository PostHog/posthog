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
    # Stage 2b: populated for URL sources, empty for text sources.
    crawl_mode: str = ""
    crawl_config: dict = field(default_factory=dict)


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
class CreateCrawlSourceInput:
    """
    Input for creating a multi-URL crawl source (Stage 2b).

    `crawl_mode` is one of the `CrawlMode` enum values but typed as `str` to
    keep the contract layer free of Django imports. `crawl_config` is a loose
    dict shaped as::

        {
          "include_globs": ["/docs/*"],
          "exclude_globs": ["/docs/private/*"],
          "max_depth": 2,
          "max_pages": 50,
        }

    The serializer is the authoritative validator — by the time we reach the
    facade, `crawl_config` has been shaped + bounds-checked.
    """

    team_id: int
    created_by_id: int | None
    name: str
    url: str
    crawl_mode: str
    crawl_config: dict


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
