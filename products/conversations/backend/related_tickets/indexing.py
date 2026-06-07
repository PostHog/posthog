import structlog

from posthog.api.embedding_worker import emit_embedding_request
from posthog.exceptions_capture import capture_exception
from posthog.models.team import Team

from products.conversations.backend.related_tickets.constants import (
    DOCUMENT_TYPE,
    EMBEDDING_MODEL,
    PRODUCT_CONVERSATIONS,
    RENDERING,
)
from products.conversations.backend.related_tickets.content import compose_ticket_text

logger = structlog.get_logger(__name__)


def embed_conversations_ticket(team_id: int, ticket_id: str) -> None:
    try:
        team = Team.objects.select_related("organization").get(id=team_id)
    except Team.DoesNotExist:
        return

    if not team.organization.is_ai_data_processing_approved:
        return

    try:
        composed = compose_ticket_text(team_id, ticket_id)
        if composed is None:
            return
        content, metadata, last_activity = composed

        emit_embedding_request(
            content,
            team_id=team_id,
            product=PRODUCT_CONVERSATIONS,
            document_type=DOCUMENT_TYPE,
            rendering=RENDERING,
            document_id=str(ticket_id),
            models=[EMBEDDING_MODEL],
            timestamp=last_activity,
            metadata=metadata,
        )
        logger.info(
            "Emitted conversations ticket embedding request",
            team_id=team_id,
            ticket_id=str(ticket_id),
        )
    except Exception as e:
        capture_exception(e, {"team_id": team_id, "ticket_id": str(ticket_id)})
