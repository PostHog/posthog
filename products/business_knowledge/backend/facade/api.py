from datetime import datetime
from uuid import UUID

from products.business_knowledge.backend import billing
from products.business_knowledge.backend.facade.contracts import KnowledgeUsageByTeam
from products.business_knowledge.backend.models import KnowledgeGapSuggestion, KnowledgeLearningRun


def purge_ticket_derived_rows(*, team_id: int, ticket_id: UUID) -> None:
    """Delete learning rows that name one support ticket.

    Generated knowledge documents stay. The analyzer already refuses document text
    that contains a name, email, identifier, or ticket-specific value.
    """
    KnowledgeGapSuggestion.objects.for_team(team_id).filter(ticket_id=ticket_id).delete()
    KnowledgeLearningRun.objects.for_team(team_id).filter(evidence_key__startswith=f"{ticket_id}:").delete()


def get_usage_by_team(begin: datetime, end: datetime) -> KnowledgeUsageByTeam:
    """Chunks ingested and queries per canonical team in [begin, end), for the usage report."""
    return billing.usage_by_team(begin, end)
