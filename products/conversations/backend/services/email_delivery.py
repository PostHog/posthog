import re

from django.core.exceptions import ValidationError
from django.core.validators import validate_email

from posthog.models.comment import Comment
from posthog.models.person.util import get_persons_by_distinct_ids
from posthog.models.team import Team
from posthog.personhog_client.caller_tag import personhog_caller_tag

from products.conversations.backend.models import EmailChannel
from products.conversations.backend.models.ticket import Ticket

MAX_DERIVED_SUBJECT_LENGTH = 100

_WHITESPACE_RE = re.compile(r"\s+")


def widget_email_replies_enabled(team: Team) -> bool:
    """Whether the team opted into emailing widget replies. Anything but True leaves it off."""
    return (team.conversations_settings or {}).get("widget_email_replies_enabled") is True


def get_default_verified_email_channel(team: Team) -> EmailChannel | None:
    """Resolve the team's send-from identity for tickets that didn't pick a channel."""
    return EmailChannel.objects.filter(team=team, is_default=True, domain_verified=True).first()


def resolve_verified_customer_email(team: Team, ticket: Ticket) -> str | None:
    """Resolve the requester's email from the attested person profile, never from widget traits."""
    if ticket.identity_verified is not True or not ticket.distinct_id:
        return None

    with personhog_caller_tag("conversations/widget-email-leg"):
        persons = get_persons_by_distinct_ids(team.id, [ticket.distinct_id], distinct_id_limit=0)

    if not persons:
        return None

    email = (persons[0].properties or {}).get("email")
    if not isinstance(email, str):
        return None

    email = email.strip()
    try:
        validate_email(email)
    except ValidationError:
        return None

    return email


def _derive_email_subject(ticket: Ticket) -> str | None:
    first_message = (
        Comment.objects.filter(
            team_id=ticket.team_id,
            scope="conversations_ticket",
            item_id=str(ticket.id),
            item_context__author_type="customer",
            deleted=False,
        )
        .order_by("created_at")
        .values_list("content", flat=True)
        .first()
    )
    if not first_message:
        return None

    subject = _WHITESPACE_RE.sub(" ", first_message).strip()
    if not subject:
        return None

    return subject[:MAX_DERIVED_SUBJECT_LENGTH]


def ensure_widget_email_leg(ticket: Ticket) -> bool:
    """Stamp a widget ticket with the fields the email outbox needs, and report whether it can send."""
    if ticket.email_from and ticket.email_config and ticket.email_config.domain_verified:
        return True

    channel = get_default_verified_email_channel(ticket.team)
    if not channel:
        return False

    email = ticket.email_from or resolve_verified_customer_email(ticket.team, ticket)
    if not email:
        return False

    update_fields = ["email_from", "email_config", "updated_at"]
    ticket.email_from = email
    ticket.email_config = channel

    if not ticket.email_subject:
        subject = _derive_email_subject(ticket)
        if subject:
            ticket.email_subject = subject
            update_fields.append("email_subject")

    ticket.save(update_fields=update_fields)
    return True
