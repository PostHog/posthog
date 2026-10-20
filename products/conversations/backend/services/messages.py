from django.db.models import Q, QuerySet

from posthog.models.comment import Comment

from products.conversations.backend.models.constants import TicketMessageType

# Ticket messages are stored as comments under this scope.
TICKET_MESSAGE_SCOPE = "conversations_ticket"

# "team" is analytics-only. "AI" and "customer" are not learning evidence.
PUBLIC_HUMAN_AUTHOR_TYPES = ("support", "human")

AI_DRAFT_PERSIST_AS = frozenset({"reply", "clarification"})


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
    # signals._is_private_message treats anything but boolean True as public.
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
