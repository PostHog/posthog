import re
import html as html_mod
from email.utils import formataddr, make_msgid

from django.core import mail

from posthog.models.comment import Comment
from posthog.models.instance_setting import get_instance_setting
from posthog.models.team import Team

from products.conversations.backend.mailgun import send_mime
from products.conversations.backend.models import Channel, EmailChannel, EmailMessageMapping
from products.conversations.backend.models.ticket import Ticket

MAX_DERIVED_SUBJECT_LENGTH = 100
MAX_ACK_TEXT_LENGTH = 2000

DEFAULT_ACK_TEXT = (
    "Thanks for your message! We've received it and will get back to you soon. Reply to this email to add more details."
)

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


def get_widget_ack_text(team: Team) -> str:
    value = (team.conversations_settings or {}).get("widget_email_ack_text")
    if isinstance(value, str) and value.strip():
        return value.strip()[:MAX_ACK_TEXT_LENGTH]
    return DEFAULT_ACK_TEXT


def send_widget_ack_email(ticket: Ticket) -> bool:
    """Email the requester a replyable receipt of their new widget ticket.

    Not a ticket message: no Comment is created and no message events fire. The
    receipt exists so the customer has an email whose Message-ID we know — its
    mapping row anchors the thread, so a reply sent before any agent response
    still lands on the ticket.
    """
    if ticket.channel_source != Channel.WIDGET:
        return False
    if not widget_email_replies_enabled(ticket.team):
        return False
    if EmailMessageMapping.objects.filter(ticket_id=ticket.id, team_id=ticket.team_id).exists():
        return False
    if not ensure_widget_email_leg(ticket):
        return False

    first_comment = get_first_customer_comment(ticket)
    config = ticket.email_config
    if first_comment is None or config is None or not ticket.email_from:
        return False

    ack_text = get_widget_ack_text(ticket.team)
    customer_message = (first_comment.content or "").strip()

    txt_body = f"{ack_text}\n\nYour message:\n\n{customer_message}"
    html_body = (
        f"<p>{html_mod.escape(ack_text)}</p>"
        f"<p>Your message:</p>"
        f"<blockquote>{html_mod.escape(customer_message)}</blockquote>"
    )

    inbound_domain = get_instance_setting("CONVERSATIONS_EMAIL_INBOUND_DOMAIN") or config.domain
    message_id = make_msgid(domain=inbound_domain)

    email_message = mail.EmailMultiAlternatives(
        subject=ticket.email_subject or "Your support request",
        body=txt_body,
        from_email=formataddr((config.from_name, config.from_email)),
        to=[ticket.email_from],
        headers={"Message-ID": message_id},
    )
    email_message.attach_alternative(html_body, "text/html")

    send_mime(config.domain, email_message.message().as_bytes(linesep="\r\n"), recipients=[ticket.email_from])

    EmailMessageMapping.objects.get_or_create(
        message_id=message_id,
        team_id=ticket.team_id,
        defaults={"ticket_id": ticket.id, "comment_id": first_comment.id},
    )
    return True
