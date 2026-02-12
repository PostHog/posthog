"""
Emit PostHog analytics events for ticket and message state changes.

These events power workflow triggers (e.g. "if ticket pending for X days, resolve it").
All events use the ticket's distinct_id so they're tied to the customer person.
"""

import posthoganalytics

from products.conversations.backend.models import Ticket


def _get_ticket_base_properties(ticket: Ticket) -> dict:
    return {
        "ticket_id": str(ticket.id),
        "ticket_number": ticket.ticket_number,
        "channel_source": ticket.channel_source,
        "status": ticket.status,
        "priority": ticket.priority,
    }


def capture_ticket_created(ticket: Ticket) -> None:
    properties = _get_ticket_base_properties(ticket)
    traits = ticket.anonymous_traits or {}
    properties["customer_name"] = traits.get("name", "")
    properties["customer_email"] = traits.get("email", "")

    posthoganalytics.capture(
        distinct_id=ticket.distinct_id,
        event="$conversation_ticket_created",
        properties=properties,
    )


def capture_ticket_status_changed(ticket: Ticket, old_status: str, new_status: str) -> None:
    properties = _get_ticket_base_properties(ticket)
    properties["old_status"] = old_status
    properties["new_status"] = new_status

    posthoganalytics.capture(
        distinct_id=ticket.distinct_id,
        event="$conversation_ticket_status_changed",
        properties=properties,
    )


def capture_ticket_priority_changed(ticket: Ticket, old_priority: str | None, new_priority: str | None) -> None:
    properties = _get_ticket_base_properties(ticket)
    properties["old_priority"] = old_priority
    properties["new_priority"] = new_priority

    posthoganalytics.capture(
        distinct_id=ticket.distinct_id,
        event="$conversation_ticket_priority_changed",
        properties=properties,
    )


def capture_ticket_assigned(ticket: Ticket, assignee_type: str | None, assignee_id: str | None) -> None:
    properties = _get_ticket_base_properties(ticket)
    properties["assignee_type"] = assignee_type
    properties["assignee_id"] = assignee_id

    posthoganalytics.capture(
        distinct_id=ticket.distinct_id,
        event="$conversation_ticket_assigned",
        properties=properties,
    )


def capture_message_sent(ticket: Ticket, message_id: str, message_content: str, author_id: int | None) -> None:
    """Team member sent a message on a ticket."""
    properties = _get_ticket_base_properties(ticket)
    properties["message_id"] = message_id
    properties["message_content"] = (message_content or "")[:1000]
    properties["author_type"] = "team"
    properties["author_id"] = author_id

    posthoganalytics.capture(
        distinct_id=ticket.distinct_id,
        event="$conversation_message_sent",
        properties=properties,
    )


def capture_message_received(ticket: Ticket, message_id: str, message_content: str) -> None:
    """Customer sent a message on a ticket."""
    properties = _get_ticket_base_properties(ticket)
    properties["message_id"] = message_id
    properties["message_content"] = (message_content or "")[:1000]
    properties["author_type"] = "customer"
    traits = ticket.anonymous_traits or {}
    properties["customer_name"] = traits.get("name", "")
    properties["customer_email"] = traits.get("email", "")

    posthoganalytics.capture(
        distinct_id=ticket.distinct_id,
        event="$conversation_message_received",
        properties=properties,
    )
