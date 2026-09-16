from django.db.models import Q, QuerySet

from posthog.models.comment import Comment

from products.conversations.backend.models.constants import MESSAGE_SOURCE_POSTHOG

# Ticket messages are stored as comments under this scope.
TICKET_MESSAGE_SCOPE = "conversations_ticket"

# "team" is analytics-only. "AI" and "customer" are not learning evidence.
PUBLIC_HUMAN_AUTHOR_TYPES = ("support", "human")


def is_team_authored(item_context: object, created_by_id: int | None) -> bool:
    """A message from the team rather than the customer: a PostHog user, or the AI.

    That covers team members replying from inside a channel too (a Slack thread reply
    links created_by), which originated_in_channel tells apart.
    """
    if not isinstance(item_context, dict):
        return False
    author_type = item_context.get("author_type")
    return bool(created_by_id and author_type != "customer") or author_type == "AI"


def originated_in_channel(item_context: object, channel: str) -> bool:
    """True when the message was ingested from ``channel`` rather than written in PostHog.

    Every channel's ingestion stamps ``from_<channel>`` on the comment. Outbound delivery relies
    on it not to echo a message back where it came from, so a channel that forgets the flag
    loops its own messages back to itself, and message_source reads the same flag.
    """
    return isinstance(item_context, dict) and bool(item_context.get(f"from_{channel}"))


def message_source(item_context: object, created_by_id: int | None, ticket_channel: str) -> str:
    """Where a ticket message was written: the ticket's channel, or PostHog.

    A customer can only write in through the ticket's channel, so only team messages need
    telling apart, and those came from the channel exactly when delivery wouldn't echo them.
    """
    if is_team_authored(item_context, created_by_id) and not originated_in_channel(item_context, ticket_channel):
        return MESSAGE_SOURCE_POSTHOG
    return ticket_channel


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
