from collections.abc import Sequence
from typing import TYPE_CHECKING

from django.db.models import Q, QuerySet

from posthog.models.comment import Comment

from products.conversations.backend.models.constants import WORKFLOW_AUTHOR_TYPE, Channel, TicketMessageType

if TYPE_CHECKING:
    from products.conversations.backend.models import Ticket

# Ticket messages are stored as comments under this scope.
TICKET_MESSAGE_SCOPE = "conversations_ticket"
# Marks a team reply written after the customer confirmed their address on a ticket from another channel.
DELIVERED_BY_EMAIL_CONTEXT_KEY = "delivered_by_email"

# "team" is analytics-only. "AI" and "customer" are not learning evidence.
PUBLIC_HUMAN_AUTHOR_TYPES = ("support", "human")

AI_DRAFT_PERSIST_AS = frozenset({"reply", "clarification"})


def is_private_message(item_context: object) -> bool:
    """Check if a message is marked as private."""
    if not isinstance(item_context, dict):
        return False
    return item_context.get("is_private", False) is True


def is_outbound_reply(item_context: object, created_by_id: int | None) -> bool:
    """True for messages that should be delivered to the customer's channel.

    This includes human team replies (has created_by, non-customer, non-private) and
    public AI replies (author_type == "AI" with is_private == False).
    """
    if not isinstance(item_context, dict):
        return False
    if is_private_message(item_context):
        return False
    author_type = item_context.get("author_type")
    if created_by_id and author_type != "customer":
        return True
    # No created_by: only these authors are team replies. A workflow message with any other
    # type would be stored and never delivered.
    if author_type in ("AI", WORKFLOW_AUTHOR_TYPE):
        return True
    return False


def ticket_message_type(item_context: object, created_by_id: int | None) -> TicketMessageType:
    context = item_context if isinstance(item_context, dict) else {}
    if context.get("is_private") is not True:
        if context.get("author_type", "customer") == "customer":
            return TicketMessageType.CUSTOMER_MESSAGE
        return TicketMessageType.SENT_REPLY
    if (
        created_by_id is None
        and context.get("author_type") == "AI"
        and "internal_note_key" not in context
        and context.get("persist_as", "reply") in AI_DRAFT_PERSIST_AS
    ):
        return TicketMessageType.AI_DRAFT
    return TicketMessageType.INTERNAL_NOTE


def _public_ticket_message_context() -> Q:
    # isnull keeps comments with no is_private key, because ~Q alone drops SQL NULL.
    # is_private_message treats anything but boolean True as public.
    return ~Q(item_context__is_private=True) | Q(item_context__is_private__isnull=True)


def visible_ticket_messages(team_id: int, ticket_id: str) -> QuerySet[Comment]:
    """
    Messages on a ticket that the customer is allowed to read: not soft-deleted, and not a
    private team note. Getting this predicate wrong shows a private team note to a customer,
    so callers should reuse it rather than write their own.

    widget.py keeps its own copy of the predicate. It filters on a Team object, which
    RootTeamQuerySet does not rewrite, where this helper filters on an id, which it does.
    The two agree while no team sets parent_team. If environments ship they diverge, and this
    helper is the correct form, because RootTeamMixin.save stores comments on the root team.
    """
    return Comment.objects.filter(
        team_id=team_id,
        scope=TICKET_MESSAGE_SCOPE,
        item_id=ticket_id,
        deleted=False,
    ).filter(_public_ticket_message_context())


def _tickets_with_authenticated_mail_from(team_id: int, ticket_ids: list[str], address: str) -> set[str]:
    return set(
        Comment.objects.filter(
            team_id=team_id,
            scope=TICKET_MESSAGE_SCOPE,
            item_id__in=ticket_ids,
            deleted=False,
            item_context__from_email=True,
            item_context__email_sender_authenticated=True,
            item_context__email_from__iexact=address,
        ).values_list("item_id", flat=True)
    )


def _is_ticket_address(ticket: "Ticket", viewer_email: str | None) -> bool:
    return bool(viewer_email and ticket.email_from and ticket.email_from.lower() == viewer_email.lower())


def widget_email_reader_address(ticket: "Ticket", viewer_email: str | None) -> str | None:
    """The address whose emails a widget viewer may read on a ticket from another channel.

    `viewer_email` is the viewer's signed email claim, or None for a viewer known only by a
    widget session. Such a ticket gets emails once email delivery is requested for it, from
    whoever holds the mailbox, and a widget session never proved it is that person. The viewer
    reads them under the conditions of the email bridge: a signed email equal to the ticket's
    address, and mail from that address that passed sender authentication. They read only the
    emails from that address, because the ticket can hold mail from an address it had before.
    """
    if ticket.channel_source == Channel.EMAIL or not _is_ticket_address(ticket, viewer_email):
        return None
    ticket_id = str(ticket.id)
    if ticket_id not in _tickets_with_authenticated_mail_from(ticket.team_id, [ticket_id], viewer_email or ""):
        return None
    return viewer_email


def messages_shown_in_widget(
    ticket: "Ticket", messages: QuerySet[Comment], reader_address: str | None
) -> QuerySet[Comment]:
    """Narrow a ticket's customer-visible messages to what a widget viewer may read.

    On an email ticket the emails are the conversation, and the viewer already passed the email
    bridge to reach it. On any other ticket `reader_address` comes from
    `widget_email_reader_address`.
    """
    if ticket.channel_source == Channel.EMAIL:
        return messages
    return messages.filter(_shown_to_widget_viewer(reader_address))


def _context_flag_unset(key: str) -> Q:
    # isnull keeps comments with no such key, because ~Q alone drops SQL NULL.
    return ~Q(**{f"item_context__{key}": True}) | Q(**{f"item_context__{key}__isnull": True})


def _shown_to_widget_viewer(reader_address: str | None) -> Q:
    """Messages of a ticket from another channel that a widget viewer may read.

    A viewer known only by a widget session reads neither the emails nor the replies written
    after the address was confirmed. Those replies were written for the mailbox owner.
    """
    if reader_address is None:
        return _context_flag_unset("from_email") & _context_flag_unset(DELIVERED_BY_EMAIL_CONTEXT_KEY)
    return _context_flag_unset("from_email") | Q(item_context__email_from__iexact=reader_address)


def _last_visible_contents(team_id: int, ticket_ids: list[str], reader_address: str | None) -> dict[str, str]:
    if not ticket_ids:
        return {}
    return dict(
        Comment.objects.filter(team_id=team_id, scope=TICKET_MESSAGE_SCOPE, item_id__in=ticket_ids, deleted=False)
        .filter(_public_ticket_message_context())
        .filter(_shown_to_widget_viewer(reader_address))
        .order_by("item_id", "-created_at")
        .distinct("item_id")
        .values_list("item_id", "content")
    )


def last_message_texts_shown_in_widget(tickets: Sequence["Ticket"], viewer_email: str | None) -> dict[str, str | None]:
    """Each ticket's last-message preview for a widget viewer, keyed by ticket ID.

    `Ticket.last_message_text` is shared with the inbox, so it can hold an email the viewer
    must not read. The tickets must belong to one team.
    """
    previews: dict[str, str | None] = {str(ticket.id): ticket.last_message_text for ticket in tickets}
    # email_from is set on a ticket from another channel when email delivery is requested for it,
    # and nothing clears it afterwards. The email channel can be deleted, so it is not a signal.
    with_emails = [ticket for ticket in tickets if ticket.channel_source != Channel.EMAIL and ticket.email_from]
    if not with_emails:
        return previews

    team_id = with_emails[0].team_id
    own = [str(ticket.id) for ticket in with_emails if _is_ticket_address(ticket, viewer_email)]
    readable = _tickets_with_authenticated_mail_from(team_id, own, viewer_email or "") if own else set()
    session_only = [str(ticket.id) for ticket in with_emails if str(ticket.id) not in readable]
    last_visible = {
        **_last_visible_contents(team_id, session_only, None),
        **_last_visible_contents(team_id, sorted(readable), viewer_email),
    }
    for ticket in with_emails:
        content = last_visible.get(str(ticket.id))
        previews[str(ticket.id)] = None if content is None else content[:500]
    return previews


def public_human_ticket_replies(
    comment_team_ids: set[int],
    ticket_ids: list[str] | None = None,
) -> QuerySet[Comment]:
    qs = (
        Comment.objects.filter(
            team_id__in=comment_team_ids,
            scope=TICKET_MESSAGE_SCOPE,
            deleted=False,
            item_context__author_type__in=PUBLIC_HUMAN_AUTHOR_TYPES,
        )
        .filter(_public_ticket_message_context())
        .filter(content__regex=r"\S")
    )
    if ticket_ids is not None:
        qs = qs.filter(item_id__in=ticket_ids)
    return qs
