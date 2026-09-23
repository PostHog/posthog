from django.db.models import Q, QuerySet

from posthog.models.comment import Comment

# Ticket messages are stored as comments under this scope.
TICKET_MESSAGE_SCOPE = "conversations_ticket"

# "team" is analytics-only. "AI" and "customer" are not learning evidence.
PUBLIC_HUMAN_AUTHOR_TYPES = ("support", "human")


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
