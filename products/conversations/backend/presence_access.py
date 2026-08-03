"""Enables presence on support tickets, so agents can see who else is on a ticket."""

from posthog.presence import model_access_check, register_presence_scope

from products.conversations.backend.models.ticket import Ticket

PRESENCE_SCOPE_TICKET = "conversations_ticket"


def register() -> None:
    register_presence_scope(
        PRESENCE_SCOPE_TICKET,
        # Viewer, not editor: presence is a read-shaped signal, and an agent who can only read a
        # ticket still benefits from knowing someone else is already on it. The write paths stay
        # gated by TicketViewSet and CommentViewSet.
        model_access_check(
            lambda team_id, item_id: Ticket.objects.filter(team_id=team_id, id=item_id).first(),
            required_level="viewer",
        ),
    )
