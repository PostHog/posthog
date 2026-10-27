from uuid import UUID

from products.business_knowledge.backend import logic
from products.business_knowledge.backend.facade.contracts import KnowledgeHit
from products.business_knowledge.backend.models import KnowledgeGapSuggestion, KnowledgeLearningRun


def purge_ticket_derived_rows(*, team_id: int, ticket_id: UUID) -> None:
    """Delete learning rows that name one support ticket.

    Generated knowledge documents stay. The analyzer already refuses document text
    that contains a name, email, identifier, or ticket-specific value.
    """
    KnowledgeGapSuggestion.objects.for_team(team_id).filter(ticket_id=ticket_id).delete()
    KnowledgeLearningRun.objects.for_team(team_id).filter(evidence_key__startswith=f"{ticket_id}:").delete()


def search_knowledge(*, team_id: int, query: str, limit: int = 5) -> list[KnowledgeHit]:
    """Keyword search over the team's knowledge, best match first."""
    return [
        KnowledgeHit(
            document_title=result.document_title,
            heading_path=result.heading_path,
            url=result.url,
            content=result.content,
        )
        for result in logic.search_knowledge(team_id, query, limit=limit)
    ]
