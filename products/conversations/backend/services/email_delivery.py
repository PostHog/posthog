import re
from email.utils import make_msgid

from django.db import transaction

from posthog.models.comment import Comment
from posthog.models.instance_setting import get_instance_setting
from posthog.models.team import Team

from products.conversations.backend.models import EmailChannel, EmailMessageMapping
from products.conversations.backend.models.ticket import Ticket

MAX_DERIVED_SUBJECT_LENGTH = 100

_WHITESPACE_RE = re.compile(r"\s+")


def widget_email_replies_enabled(team: Team) -> bool:
    """Whether the team opted into emailing widget replies. Anything but True leaves it off."""
    return (team.conversations_settings or {}).get("widget_email_replies_enabled") is True


def get_default_verified_email_channel(team: Team) -> EmailChannel | None:
    """Resolve the team's send-from identity for tickets that didn't pick a channel."""
    return EmailChannel.objects.filter(team=team, is_default=True, domain_verified=True).first()


def get_first_customer_comment(ticket: Ticket) -> Comment | None:
    return (
        Comment.objects.filter(
            team_id=ticket.team_id,
            scope="conversations_ticket",
            item_id=str(ticket.id),
            item_context__author_type="customer",
            deleted=False,
        )
        .order_by("created_at")
        .first()
    )


def _derive_email_subject(ticket: Ticket) -> str | None:
    first_comment = get_first_customer_comment(ticket)
    if not first_comment or not first_comment.content:
        return None

    subject = _WHITESPACE_RE.sub(" ", first_comment.content).strip()
    if not subject:
        return None

    return subject[:MAX_DERIVED_SUBJECT_LENGTH]


def ensure_widget_email_leg(ticket: Ticket) -> bool:
    """Stamp a widget ticket with the fields the email outbox needs, and report whether it can send.

    Never resolve a recipient here: email_from comes only from the host-signed email
    claim at widget-message time. Person properties and widget traits are client-writable.
    """
    if ticket.identity_verified is not True or not ticket.email_from:
        return False

    if ticket.email_config and ticket.email_config.domain_verified:
        return True

    channel = get_default_verified_email_channel(ticket.team)
    if not channel:
        return False

    update_fields = ["email_config", "updated_at"]
    ticket.email_config = channel

    if not ticket.email_subject:
        subject = _derive_email_subject(ticket)
        if subject:
            ticket.email_subject = subject
            update_fields.append("email_subject")

    ticket.save(update_fields=update_fields)
    return True


def _thread_anchor_domain(ticket: Ticket) -> str | None:
    """The domain to mint a thread-anchor Message-ID under.

    Only a verified channel makes threading reachable: a customer's reply has to arrive at an
    address that forwards into the inbound webhook. No channel means no anchor is useful.
    """
    instance_domain = get_instance_setting("CONVERSATIONS_EMAIL_INBOUND_DOMAIN")
    if instance_domain:
        return instance_domain
    if ticket.email_config and ticket.email_config.domain_verified:
        return ticket.email_config.domain
    channel = get_default_verified_email_channel(ticket.team)
    return channel.domain if channel else None


def get_or_create_email_thread_anchor(ticket: Ticket) -> str | None:
    """A Message-ID that threads email onto this ticket, for first-party mail we don't send.

    Workflows send their own email (CSAT, acknowledgments, nudges) through a separate
    transport, so conversations never sees those Message-IDs. Including this anchor in such
    an email's References header makes a customer reply thread onto the ticket, because
    inbound matching accepts any known ID in that chain.

    Reuses an existing mapping when the ticket already has one, so the anchor is stable and
    an email-channel ticket threads under the customer's own first email.
    """
    existing = (
        EmailMessageMapping.objects.filter(ticket_id=ticket.id, team_id=ticket.team_id)
        .order_by("created_at")
        .values_list("message_id", flat=True)
        .first()
    )
    if existing:
        return existing

    domain = _thread_anchor_domain(ticket)
    if not domain:
        return None

    anchor_comment = get_first_customer_comment(ticket)
    if anchor_comment is None:
        return None

    # Lock the ticket so concurrent workflow runs can't each mint an anchor. Every mint
    # generates a fresh random Message-ID, so there is no unique key to collide on.
    with transaction.atomic():
        locked = Ticket.objects.select_for_update().filter(id=ticket.id, team_id=ticket.team_id).first()
        if locked is None:
            return None

        raced = (
            EmailMessageMapping.objects.filter(ticket_id=ticket.id, team_id=ticket.team_id)
            .order_by("created_at")
            .values_list("message_id", flat=True)
            .first()
        )
        if raced:
            return raced

        message_id = make_msgid(domain=domain)
        EmailMessageMapping.objects.create(
            message_id=message_id,
            team_id=ticket.team_id,
            ticket_id=ticket.id,
            comment_id=anchor_comment.id,
        )
        return message_id
