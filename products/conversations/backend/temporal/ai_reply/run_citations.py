from __future__ import annotations

from uuid import UUID

from django.db import transaction

import structlog

from products.business_knowledge.backend.facade.api import record_run_citations

logger = structlog.get_logger(__name__)


def record_note_citations(
    *, team_id: int, run_id: str, ticket_id: str, citations: list[str], persist_as: str, confidence: float
) -> None:
    """Record the knowledge a run cited in the note it is saving. A failure here must not stop the note.

    Call inside the transaction that writes the note, so a rollback removes both.
    """
    if not run_id or not citations:
        return
    try:
        # Savepoint, so a failed insert cannot poison the transaction that posts the note.
        with transaction.atomic():
            record_run_citations(
                team_id=team_id,
                run_id=run_id,
                ticket_id=UUID(str(ticket_id)),
                citations=citations,
                persist_as=persist_as,
                confidence=confidence,
            )
    except Exception:
        logger.warning("support_reply_citation_record_failed", team_id=team_id, exc_info=True)
