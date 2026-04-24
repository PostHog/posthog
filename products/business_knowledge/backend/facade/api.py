"""
Facade for business_knowledge.

The ONLY module other products (and our own presentation/ layer) are allowed
to import. Inputs and outputs are frozen dataclasses — no ORM leaks.

Exposes source CRUD used by the DRF viewset and any future admin tooling.
"""

from uuid import UUID

from .. import logic
from ..models import KnowledgeSource
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
