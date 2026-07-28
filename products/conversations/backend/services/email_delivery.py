"""Email delivery targets for tickets that didn't arrive over the email channel.

A widget ticket has no outbound channel of its own: an embedded widget only shows a
reply if the customer comes back to it, and a ticket submitted straight to the widget
API has no customer-facing surface at all. When the submitter left an email address and
the team runs a verified email channel, we point the ticket at that channel so agent
replies go out through the normal outbox path — and so the customer's answer threads
back onto the same ticket.

The address is a claim typed into a form on a public endpoint, never an attestation: it
must not promote `identity_verified`, and nothing downstream should read it as proof of
who the requester is (see `_tickets_with_verified_org` in the Salesforce enrichment for
the shape of check that has to stay email-channel only).
"""

from django.core.exceptions import ValidationError
from django.core.validators import validate_email

from posthog.models.team import Team

from products.conversations.backend.models import EmailChannel
from products.conversations.backend.models.constants import Channel
from products.conversations.backend.models.ticket import Ticket

# Matches the max length of Ticket.email_from (Django's EmailField default).
MAX_EMAIL_LENGTH = 254


def customer_email_from_traits(traits: dict | None) -> str | None:
    """The address the customer left on a widget submission, or None if unusable.

    Traits are arbitrary strings from a public endpoint, so the value is validated here
    rather than trusted — an unparseable or over-long address would otherwise reach the
    MIME builder.
    """
    email = (traits or {}).get("email")
    if not isinstance(email, str):
        return None
    email = email.strip()
    if not email or len(email) > MAX_EMAIL_LENGTH:
        return None
    try:
        validate_email(email)
    except ValidationError:
        return None
    return email


def _sending_channel(team_id: int) -> EmailChannel | None:
    """The channel to send from when a ticket didn't come in through one.

    Prefers the team's default channel, falling back to the oldest verified one so a
    team that never picked a default still gets a stable sender identity.
    """
    return (
        EmailChannel.objects.filter(team_id=team_id, domain_verified=True).order_by("-is_default", "created_at").first()
    )


def widget_email_delivery_target(team: Team, traits: dict | None) -> tuple[str, EmailChannel] | None:
    """Recipient address and sending channel for a widget ticket, if it can be emailed."""
    if not (team.conversations_settings or {}).get("email_enabled"):
        return None
    recipient = customer_email_from_traits(traits)
    if not recipient:
        return None
    config = _sending_channel(team.id)
    if config is None:
        return None
    return recipient, config


def link_widget_ticket_to_email(ticket: Ticket) -> bool:
    """Point a widget ticket at the address and channel its replies go out on.

    Tickets are stamped at creation too, so this mostly catches ones opened before the
    team connected an email channel, and follow-ups where the customer corrected the
    address they left. Returns whether the ticket has a recipient at all — a stale one
    counts, so a team that disconnects its email channel mid-thread gets a visible
    delivery failure instead of a reply that quietly goes nowhere.
    """
    if ticket.channel_source != Channel.WIDGET:
        return False
    if not (ticket.team.conversations_settings or {}).get("email_enabled"):
        return bool(ticket.email_from)

    recipient = customer_email_from_traits(ticket.anonymous_traits) or ticket.email_from
    if not recipient:
        return False

    # Keep the identity the thread started on for as long as it still sends, so a change
    # of primary channel doesn't move an in-flight conversation to a new From address.
    config = ticket.email_config if ticket.email_config and ticket.email_config.domain_verified else None
    config = config or _sending_channel(ticket.team_id)
    if config is None:
        return bool(ticket.email_from)

    if ticket.email_from != recipient or ticket.email_config_id != config.id:
        ticket.email_from, ticket.email_config = recipient, config
        ticket.save(update_fields=["email_from", "email_config", "updated_at"])
    return True
