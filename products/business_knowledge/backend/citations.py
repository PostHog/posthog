"""Records which knowledge a support investigation run cited."""

from datetime import datetime
from uuid import UUID

from django.utils import timezone

from posthog.models.scoping.manager import resolve_effective_team_id

from .models import KnowledgeChunk, KnowledgeRunCitation
from .models.knowledge_run_citation import PERSIST_AS_MAX_LENGTH


def _chunk_ids(citations: list[str]) -> list[UUID]:
    """Keep the citations that are chunk ids. A run can also cite a docs URL."""
    chunk_ids: list[UUID] = []
    seen: set[UUID] = set()
    for citation in citations:
        try:
            chunk_id = UUID(str(citation).strip())
        except ValueError:
            continue
        if chunk_id not in seen:
            seen.add(chunk_id)
            chunk_ids.append(chunk_id)
    return chunk_ids


def record_run_citations(
    *,
    team_id: int,
    run_id: str,
    ticket_id: UUID,
    citations: list[str],
    persist_as: str = "",
    confidence: float | None = None,
    cited_at: datetime | None = None,
) -> int:
    """Store one row per knowledge chunk the run cited. Returns how many chunks it cited.

    Recording the same run twice adds nothing, so a retried caller is safe.
    """
    chunk_ids = _chunk_ids(citations)
    if not run_id or not chunk_ids:
        return 0
    canonical_team_id = resolve_effective_team_id(team_id)
    chunks = KnowledgeChunk.objects.for_team(canonical_team_id, canonical=True).filter(id__in=chunk_ids)
    created_at = cited_at or timezone.now()
    rows = [
        KnowledgeRunCitation(
            team_id=canonical_team_id,
            run_id=run_id,
            ticket_id=ticket_id,
            chunk_id=chunk_id,
            document_id=document_id,
            source_id=source_id,
            persist_as=persist_as[:PERSIST_AS_MAX_LENGTH],
            confidence=confidence,
            created_at=created_at,
        )
        for chunk_id, document_id, source_id in chunks.values_list("id", "document_id", "source_id")
    ]
    if not rows:
        return 0
    KnowledgeRunCitation.objects.for_team(canonical_team_id, canonical=True).bulk_create(rows, ignore_conflicts=True)
    return len(rows)
