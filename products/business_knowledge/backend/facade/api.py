"""
Facade for business_knowledge.

The ONLY module other products (and our own presentation/ layer) are allowed
to import. Inputs and outputs are frozen dataclasses — no ORM leaks.

Exposes source CRUD used by the DRF viewset and any future admin tooling.
"""

from uuid import UUID

from .. import logic
from ..models import KnowledgeChunk, KnowledgeSource
from ..models.constants import SourceStatus
from . import contracts


def _to_dto(source: KnowledgeSource) -> contracts.KnowledgeSourceDTO:
    # The counts are attached by list_for_team/get_for_team via annotate().
    # If someone passes a raw instance (e.g. freshly created inside a txn),
    # fall back to 0 instead of triggering a query.
    document_count = getattr(source, "_document_count", 0)
    chunk_count = getattr(source, "_chunk_count", 0)
    return contracts.KnowledgeSourceDTO(
        id=source.id,
        team_id=source.team_id,
        name=source.name,
        source_type=source.source_type,
        status=source.status,
        error_message=source.error_message,
        document_count=document_count,
        chunk_count=chunk_count,
        created_at=source.created_at,
        updated_at=source.updated_at,
        source_url=source.source_url or "",
        last_refresh_at=source.last_refresh_at,
        last_refresh_status=source.last_refresh_status or "",
        last_refresh_error=source.last_refresh_error or "",
        crawl_mode=source.crawl_mode or "",
        crawl_config=dict(source.crawl_config or {}),
        original_filename=source.original_filename or "",
        file_content_type=source.file_content_type or "",
        file_size_bytes=source.file_size_bytes,
    )


def list_for_team(team_id: int) -> list[contracts.KnowledgeSourceDTO]:
    return [_to_dto(s) for s in logic.list_for_team(team_id)]


def get_for_team(source_id: UUID, team_id: int) -> contracts.KnowledgeSourceDTO | None:
    source = logic.get_for_team(source_id, team_id)
    return _to_dto(source) if source is not None else None


def create_text_source(data: contracts.CreateTextSourceInput) -> contracts.KnowledgeSourceDTO:
    source = logic.create_text_source(
        team_id=data.team_id,
        created_by_id=data.created_by_id,
        name=data.name,
        text=data.text,
    )
    return _to_dto(source)


def create_url_source(data: contracts.CreateUrlSourceInput) -> contracts.KnowledgeSourceDTO:
    source = logic.create_url_source(
        team_id=data.team_id,
        created_by_id=data.created_by_id,
        name=data.name,
        url=data.url,
    )
    return _to_dto(source)


def create_file_source(data: contracts.CreateFileSourceInput) -> contracts.KnowledgeSourceDTO:
    source = logic.create_file_source(
        team_id=data.team_id,
        created_by_id=data.created_by_id,
        name=data.name,
        file_data=data.file_data,
        original_filename=data.original_filename,
    )
    return _to_dto(source)


def create_crawl_source(data: contracts.CreateCrawlSourceInput) -> contracts.KnowledgeSourceDTO:
    source = logic.create_crawl_source(
        team_id=data.team_id,
        created_by_id=data.created_by_id,
        name=data.name,
        url=data.url,
        crawl_mode=data.crawl_mode,
        crawl_config=data.crawl_config,
    )
    return _to_dto(source)


def refresh_source(source_id: UUID, team_id: int) -> contracts.KnowledgeSourceDTO | None:
    source = logic.refresh_source(source_id=source_id, team_id=team_id)
    return _to_dto(source) if source is not None else None


def delete_source(source_id: UUID, team_id: int) -> bool:
    return logic.delete_source(source_id, team_id)


def get_source_text(source_id: UUID, team_id: int) -> str | None:
    return logic.get_source_text_for_team(source_id, team_id)


def update_text_source(data: contracts.UpdateTextSourceInput) -> contracts.KnowledgeSourceDTO | None:
    source = logic.update_text_source(
        source_id=data.source_id,
        team_id=data.team_id,
        name=data.name,
        text=data.text,
    )
    return _to_dto(source) if source is not None else None


def update_url_source(data: contracts.UpdateUrlSourceInput) -> contracts.KnowledgeSourceDTO | None:
    source = logic.update_url_source(
        source_id=data.source_id,
        team_id=data.team_id,
        name=data.name,
        url=data.url,
        crawl_mode=data.crawl_mode,
        crawl_config=data.crawl_config,
    )
    return _to_dto(source) if source is not None else None


# ---------------------------------------------------------------------------
# Stage 4 — AI agent read-path
# ---------------------------------------------------------------------------


def has_ready_sources(team_id: int) -> bool:
    """True when the team has at least one READY source (READY implies chunks exist)."""
    return KnowledgeSource.objects.filter(team_id=team_id, status=SourceStatus.READY).exists()


_SEARCH_LIMIT_CAP = 20


def search_knowledge(
    team_id: int,
    query: str,
    *,
    limit: int = 10,
) -> list[contracts.KnowledgeSearchResult]:
    """
    ILIKE search over chunks belonging to READY sources for the given team.

    Returns up to `limit` chunks (capped at _SEARCH_LIMIT_CAP) with their
    source metadata. Uses the GIN trigram index for performance. Results are
    ordered by char_count ascending (shorter, more focused chunks first).
    """
    limit = max(1, min(limit, _SEARCH_LIMIT_CAP))

    if not query.strip():
        return []

    safe_query = query.strip()

    chunks = (
        KnowledgeChunk.objects.filter(
            team_id=team_id,
            source__status=SourceStatus.READY,
            content__icontains=safe_query,
        )
        .select_related("source", "document")
        .only(
            "id",
            "source_id",
            "document_id",
            "heading_path",
            "ordinal",
            "content",
            "source__name",
            "source__source_type",
            "document__title",
        )
        .order_by("char_count")[:limit]
    )

    return [
        contracts.KnowledgeSearchResult(
            chunk_id=c.id,
            source_id=c.source_id,
            source_name=c.source.name,
            source_type=c.source.source_type,
            document_title=c.document.title,
            heading_path=c.heading_path,
            ordinal=c.ordinal,
            content=c.content,
        )
        for c in chunks
    ]
