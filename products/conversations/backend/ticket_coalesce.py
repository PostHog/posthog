from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from django.db.models import CharField, OuterRef, Q, Subquery
from django.db.models.functions import Cast, Coalesce, Greatest

from posthog.models.comment import Comment

from products.conversations.backend.models import Ticket
from products.conversations.backend.models.constants import Status

IDENTICAL_REPLAY_WINDOW_SECONDS = 30
APPEND_WINDOW_SECONDS = 180

_CANDIDATE_LIMIT = 5
_APPENDABLE_STATUSES = (Status.NEW, Status.OPEN, Status.PENDING, Status.ON_HOLD)


@dataclass(frozen=True, kw_only=True)
class AppendTarget:
    ticket: Ticket


@dataclass(frozen=True, kw_only=True)
class ReplayTarget:
    ticket: Ticket
    comment: Comment


def _ticket_ids_with_non_customer_replies(*, team_id: int, ticket_ids: list[UUID]) -> set[str]:
    return set(
        Comment.objects.filter(
            team_id=team_id,
            scope="conversations_ticket",
            item_id__in=[str(ticket_id) for ticket_id in ticket_ids],
            deleted=False,
        )
        .filter(~Q(item_context__author_type="customer") | Q(item_context__author_type__isnull=True))
        .values_list("item_id", flat=True)
    )


def resolve(*, team_id: int, widget_session_id: str, content: str, now: datetime) -> AppendTarget | ReplayTarget | None:
    """
    Decide whether a ticket-less widget send should create, append, or replay.

    Caller must hold the widget-session advisory lock so concurrent creates see
    each other's commits. Keys on widget_session_id (not distinct_id) so the
    returned ticket stays readable by the anonymous widget messages endpoint.

    The latest comment participates in recency because last_message_at is updated
    on commit and can briefly lag behind release of the advisory lock.

    Replay only applies to the latest customer message on the newest unanswered ticket.
    A matching message on any older ticket appends to the newest ticket instead.
    """
    replay_cutoff = now - timedelta(seconds=IDENTICAL_REPLAY_WINDOW_SECONDS)
    append_cutoff = now - timedelta(seconds=APPEND_WINDOW_SECONDS)
    latest_comment = (
        Comment.objects.filter(
            team_id=team_id,
            scope="conversations_ticket",
            item_id=Cast(OuterRef("id"), output_field=CharField()),
            deleted=False,
        )
        .order_by("-created_at")
        .values("created_at")[:1]
    )

    candidates = list(
        Ticket.objects.filter(
            team_id=team_id,
            widget_session_id=widget_session_id,
            channel_source="widget",
            status__in=_APPENDABLE_STATUSES,
        )
        .annotate(latest_comment_at=Subquery(latest_comment))
        .annotate(
            last_activity=Greatest(
                Coalesce("last_message_at", "created_at"),
                Coalesce("latest_comment_at", "created_at"),
            )
        )
        .filter(last_activity__gte=append_cutoff)
        .order_by("-last_activity", "-created_at", "-id")[:_CANDIDATE_LIMIT]
    )

    answered_ticket_ids = _ticket_ids_with_non_customer_replies(
        team_id=team_id, ticket_ids=[ticket.id for ticket in candidates]
    )
    unanswered = [ticket for ticket in candidates if str(ticket.id) not in answered_ticket_ids]

    if not unanswered:
        return None

    ticket = unanswered[0]
    latest_customer_comment = (
        Comment.objects.filter(
            team_id=team_id,
            scope="conversations_ticket",
            item_id=str(ticket.id),
            deleted=False,
            item_context__author_type="customer",
        )
        .order_by("-created_at")
        .first()
    )
    if (
        latest_customer_comment is not None
        and latest_customer_comment.created_at >= replay_cutoff
        and latest_customer_comment.content == content
    ):
        return ReplayTarget(ticket=ticket, comment=latest_customer_comment)

    return AppendTarget(ticket=ticket)
