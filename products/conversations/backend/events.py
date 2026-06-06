"""
Emit PostHog analytics events for ticket and message state changes.

These events power workflow triggers (e.g. "if ticket pending for X days, resolve it").
All events use the ticket's distinct_id so they're tied to the customer person.
Events are sent to the customer's PostHog project via their team's API token.
"""

import structlog

from posthog.api.capture import capture_internal
from posthog.event_usage import groups as build_groups
from posthog.models.organization import OrganizationMembership
from posthog.models.person.util import get_persons_by_distinct_ids
from posthog.models.team import Team

from products.conversations.backend.models import Ticket
from products.conversations.backend.models.constants import Channel
from products.conversations.backend.person_lookup import _get_persons_by_email

logger = structlog.get_logger(__name__)

EVENT_SOURCE = "conversations_events"

# Channels whose customer email is tied to a provider-verified identity and is therefore safe
# to use for organization attribution.
_EMAIL_FALLBACK_CHANNELS = frozenset({Channel.EMAIL.value, Channel.SLACK.value, Channel.TEAMS.value})


def _resolve_org_groups(ticket: Ticket, team: Team) -> tuple[bool, dict | None]:
    """Resolve the customer organization's ``$groups`` for a ticket.

    Returns ``(process_person, groups)``. ``groups`` is ``None`` when the
    customer can't be tied to a PostHog organization.

    The web widget sets ``ticket.distinct_id`` to a real PostHog distinct_id,
    so the membership is found directly. Other channels (Slack, Email, MS
    Teams) set ``distinct_id`` to the customer email (or empty), so we fall
    back to looking the person up by ``properties.email`` in ClickHouse and
    resolving the membership through that person's real distinct_ids.
    """
    # 1. Real distinct_id (web widget). An identified person is authoritative: if they
    # have no org membership, don't guess via email (a shared email could resolve to a
    # different person's org), so return early instead of falling through.
    if ticket.distinct_id:
        persons = get_persons_by_distinct_ids(team.id, [ticket.distinct_id])
        if any(p.is_identified for p in persons):
            membership = (
                OrganizationMembership.objects.select_related("organization")
                .filter(user__distinct_id=ticket.distinct_id)
                .first()
            )
            if membership:
                return True, build_groups(membership.organization, team)
            return False, None

    # 2. Email fallback, restricted to channels with a provider-verified email identity.
    # Never trust the public widget's attacker-controlled anonymous_traits.email here.
    if ticket.channel_source not in _EMAIL_FALLBACK_CHANNELS:
        return False, None

    email = (ticket.anonymous_traits or {}).get("email") or ticket.email_from
    if email:
        person = _get_persons_by_email(team, [email]).get(email.lower())
        if person is not None and person.distinct_ids:
            membership = (
                OrganizationMembership.objects.select_related("organization")
                .filter(user__distinct_id__in=person.distinct_ids)
                .first()
            )
            if membership:
                return True, build_groups(membership.organization, team)

    return False, None


def _get_ticket_base_properties(ticket: Ticket) -> dict:
    return {
        "ticket_id": str(ticket.id),
        "ticket_number": ticket.ticket_number,
        "channel_source": ticket.channel_source,
        "channel_detail": ticket.channel_detail,
        "status": ticket.status,
        "priority": ticket.priority,
    }


def capture_ticket_created(ticket: Ticket) -> None:
    properties = _get_ticket_base_properties(ticket)
    traits = ticket.anonymous_traits or {}
    properties["customer_name"] = traits.get("name", "")
    properties["customer_email"] = traits.get("email", "")

    team = ticket.team
    team_id = team.id
    process_person = False
    try:
        process_person, groups = _resolve_org_groups(ticket, team)
        if groups is not None:
            properties["$groups"] = groups
    except Exception:
        logger.exception("ticket_created_person_lookup_failed", team_id=team_id, ticket_id=str(ticket.id))

    capture_internal(
        token=team.api_token,
        event_name="$conversation_ticket_created",
        event_source=EVENT_SOURCE,
        distinct_id=ticket.distinct_id or ticket.channel_source or "unknown",
        timestamp=None,
        properties=properties,
        process_person_profile=process_person,
    )


def capture_ticket_status_changed(ticket: Ticket, old_status: str, new_status: str) -> None:
    properties = _get_ticket_base_properties(ticket)
    properties["old_status"] = old_status
    properties["new_status"] = new_status

    capture_internal(
        token=ticket.team.api_token,
        event_name="$conversation_ticket_status_changed",
        event_source=EVENT_SOURCE,
        distinct_id=ticket.distinct_id or ticket.channel_source or "unknown",
        timestamp=None,
        properties=properties,
    )


def capture_ticket_priority_changed(ticket: Ticket, old_priority: str | None, new_priority: str | None) -> None:
    properties = _get_ticket_base_properties(ticket)
    properties["old_priority"] = old_priority
    properties["new_priority"] = new_priority

    capture_internal(
        token=ticket.team.api_token,
        event_name="$conversation_ticket_priority_changed",
        event_source=EVENT_SOURCE,
        distinct_id=ticket.distinct_id or ticket.channel_source or "unknown",
        timestamp=None,
        properties=properties,
    )


def capture_ticket_assigned(ticket: Ticket, assignee_type: str | None, assignee_id: str | None) -> None:
    properties = _get_ticket_base_properties(ticket)
    properties["assignee_type"] = assignee_type
    properties["assignee_id"] = assignee_id

    capture_internal(
        token=ticket.team.api_token,
        event_name="$conversation_ticket_assigned",
        event_source=EVENT_SOURCE,
        distinct_id=ticket.distinct_id or ticket.channel_source or "unknown",
        timestamp=None,
        properties=properties,
    )


def capture_message_sent(ticket: Ticket, message_id: str, message_content: str, author_id: int | None) -> None:
    """Team member sent a message on a ticket."""
    properties = _get_ticket_base_properties(ticket)
    properties["message_id"] = message_id
    properties["message_content"] = (message_content or "")[:1000]
    properties["author_type"] = "team"
    properties["author_id"] = author_id

    capture_internal(
        token=ticket.team.api_token,
        event_name="$conversation_message_sent",
        event_source=EVENT_SOURCE,
        distinct_id=ticket.distinct_id or ticket.channel_source or "unknown",
        timestamp=None,
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

    team = ticket.team
    process_person = False
    try:
        process_person, groups = _resolve_org_groups(ticket, team)
        if groups is not None:
            properties["$groups"] = groups
    except Exception:
        logger.exception("message_received_person_lookup_failed", team_id=team.id, ticket_id=str(ticket.id))

    capture_internal(
        token=team.api_token,
        event_name="$conversation_message_received",
        event_source=EVENT_SOURCE,
        distinct_id=ticket.distinct_id or ticket.channel_source or "unknown",
        timestamp=None,
        properties=properties,
        process_person_profile=process_person,
    )
