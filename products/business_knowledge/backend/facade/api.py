from datetime import datetime
from uuid import UUID

from products.business_knowledge.backend import (
    billing,
    citations as run_citations,
)
from products.business_knowledge.backend.facade.contracts import KnowledgeHit, KnowledgeUsageByTeam
from products.business_knowledge.backend.models import (
    KnowledgeGapSuggestion,
    KnowledgeLearningRun,
    KnowledgeRunCitation,
)


def purge_ticket_derived_rows(*, team_id: int, ticket_id: UUID) -> None:
    """Delete learning rows that name one support ticket.

    Generated knowledge documents stay. The analyzer already refuses document text
    that contains a name, email, identifier, or ticket-specific value.
    """
    KnowledgeGapSuggestion.objects.for_team(team_id).filter(ticket_id=ticket_id).delete()
    KnowledgeLearningRun.objects.for_team(team_id).filter(evidence_key__startswith=f"{ticket_id}:").delete()
    KnowledgeRunCitation.objects.for_team(team_id).filter(ticket_id=ticket_id).delete()


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
    """Record the knowledge chunks one support investigation run cited. Returns how many it cited.

    Citations that are not knowledge chunk ids, such as docs URLs, are skipped.
    """
    return run_citations.record_run_citations(
        team_id=team_id,
        run_id=run_id,
        ticket_id=ticket_id,
        citations=citations,
        persist_as=persist_as,
        confidence=confidence,
        cited_at=cited_at,
    )


def get_usage_by_team(begin: datetime, end: datetime) -> KnowledgeUsageByTeam:
    """Chunks ingested and queries per canonical team in [begin, end), for the usage report."""
    return billing.usage_by_team(begin, end)


def search_knowledge(*, team_id: int, query: str, limit: int = 5) -> list[KnowledgeHit]:
    """Keyword search over the team's knowledge, best match first."""
    from products.business_knowledge.backend import logic  # noqa: PLC0415 — keeps LLM clients off django.setup()

    return [
        KnowledgeHit(
            document_title=result.document_title,
            heading_path=result.heading_path,
            url=result.url,
            content=result.content,
        )
        for result in logic.search_knowledge(team_id, query, limit=limit)
    ]
