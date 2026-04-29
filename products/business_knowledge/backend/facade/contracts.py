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
    # Stage 3: file sources. Empty for text/URL sources.
    original_filename: str = ""
    file_content_type: str = ""
    file_size_bytes: int | None = None


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
class UpdateUrlSourceInput:
    """
    Input for updating a URL-type knowledge source. All fields are optional;
    changing `url` or `crawl_mode`/`crawl_config` triggers a re-crawl.
    """

    source_id: UUID
    team_id: int
    name: str | None = None
    url: str | None = None
    crawl_mode: str | None = None
    crawl_config: dict | None = None


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
class CreateFileSourceInput:
    """
    Input for creating a file-type knowledge source. The raw file bytes are
    passed directly — no object storage indirection in Stage 3.
    """

    team_id: int
    created_by_id: int | None
    name: str
    file_data: bytes
    original_filename: str


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
class KnowledgeSearchResult:
    """A single chunk returned by a knowledge search, with source context."""

    chunk_id: UUID
    source_id: UUID
    source_name: str
    source_type: str
    document_title: str
    heading_path: str
    ordinal: int
    content: str
