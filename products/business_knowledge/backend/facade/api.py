from datetime import datetime
from uuid import UUID

from products.business_knowledge.backend.models import KnowledgeGapSuggestion, KnowledgeLearningRun


def purge_ticket_derived_rows(*, team_id: int, ticket_id: UUID) -> None:
    """Delete learning rows that name one support ticket.

    Generated knowledge documents stay. The analyzer already refuses document text
    that contains a name, email, identifier, or ticket-specific value.
    """
    KnowledgeGapSuggestion.objects.for_team(team_id).filter(ticket_id=ticket_id).delete()
    KnowledgeLearningRun.objects.for_team(team_id).filter(evidence_key__startswith=f"{ticket_id}:").delete()


# nosemgrep: tuple-return-prefer-dataclass -- (team_id, count) rows are the shared usage-report contract consumed by convert_team_usage_rows_to_dict.
def get_chunks_by_team(begin: datetime, end: datetime) -> list[tuple[int, int]]:
    """Chunks ingested per team in ``[begin, end)``, for the usage report."""
    # Deferred: the ledger module pulls in the usage-ingestion gRPC client.
    from products.business_knowledge.backend import billing

    return billing.get_chunks_by_team(begin, end)


# nosemgrep: tuple-return-prefer-dataclass -- (team_id, count) rows are the shared usage-report contract consumed by convert_team_usage_rows_to_dict.
def get_queries_by_team(begin: datetime, end: datetime) -> list[tuple[int, int]]:
    """Knowledge queries per team in ``[begin, end)``, for the usage report."""
    from products.business_knowledge.backend import billing

    return billing.get_queries_by_team(begin, end)
