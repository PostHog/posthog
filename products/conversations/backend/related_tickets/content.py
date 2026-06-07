from datetime import datetime
from typing import Any

from django.db.models import Q

from posthog.models.comment import Comment
from posthog.temporal.data_imports.signals.conversations_tickets import (
    MAX_DESCRIPTION_CHARS,
    _author_tag,
    _truncate_to_budget,
)

from products.conversations.backend.models import Ticket
from products.conversations.backend.related_tickets.constants import PRODUCT_CONVERSATIONS

_TITLE_PREVIEW_CHARS = 120


def _fetch_ticket_messages(team_id: int, ticket_id: str) -> list[tuple[str, str]]:
    """Assemble a ticket's (author_type, content) message thread, oldest first."""
    comments = (
        Comment.objects.filter(
            team_id=team_id,
            scope="conversations_ticket",
            item_id=str(ticket_id),
            deleted=False,
        )
        .filter(~Q(item_context__is_private=True) | Q(item_context__is_private__isnull=True))
        .order_by("created_at")
        .values_list("content", "item_context")
    )
    messages: list[tuple[str, str]] = []
    for content, item_context in comments:
        if not content:
            continue
        author_type = (item_context or {}).get("author_type", "customer")
        messages.append((author_type, content))
    return messages


def _derive_title(ticket: Ticket, messages: list[tuple[str, str]]) -> str:
    if ticket.email_subject:
        return ticket.email_subject
    first_customer = next((content for author_type, content in messages if author_type == "customer"), None)
    preview = first_customer or (messages[0][1] if messages else None)
    if preview:
        return preview[:_TITLE_PREVIEW_CHARS]
    return f"Ticket #{ticket.ticket_number}"


def compose_ticket_text(team_id: int, ticket_id: str) -> tuple[str, dict[str, Any], datetime | None] | None:
    """Build the embeddable text and render metadata for a Conversations ticket."""
    ticket = Ticket.objects.filter(id=ticket_id, team_id=team_id).first()
    if ticket is None:
        return None

    messages = _fetch_ticket_messages(team_id, str(ticket.id))

    tagged_lines = _truncate_to_budget(
        [f"{_author_tag(author_type)}: {content}" for author_type, content in messages],
        MAX_DESCRIPTION_CHARS,
    )

    subject = ticket.email_subject
    if subject and tagged_lines:
        content = f"{subject}\n" + "\n".join(tagged_lines)
    elif tagged_lines:
        content = "\n".join(tagged_lines)
    elif subject:
        content = subject
    elif ticket.last_message_text:
        content = ticket.last_message_text
    else:
        return None

    last_activity = ticket.last_message_at or ticket.created_at
    metadata: dict[str, Any] = {
        "source": PRODUCT_CONVERSATIONS,
        "title": _derive_title(ticket, messages),
        "status": ticket.status,
        "ticket_number": ticket.ticket_number,
        "ticket_id": str(ticket.id),
        "last_activity": last_activity.isoformat() if last_activity else None,
    }
    return content, metadata, last_activity
