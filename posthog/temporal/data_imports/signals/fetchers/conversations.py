from datetime import timedelta
from typing import Any

from django.utils import timezone

import structlog

from posthog.models import Team
from posthog.models.comment import Comment
from posthog.temporal.data_imports.signals.registry import SignalSourceTableConfig

from products.conversations.backend.models import Ticket

logger = structlog.get_logger(__name__)

# Cooldown period before a ticket is eligible for signal emission.
# Vibes, ensures some conversation context has accumulated.
TICKET_COOLDOWN_HOURS = 1


def conversations_ticket_fetcher(
    team: Team,
    config: SignalSourceTableConfig,
    context: dict[str, Any],
) -> list[dict[str, Any]]:
    """Fetch conversation tickets from Postgres and mark them as emitted optimistically."""
    cutoff = timezone.now() - timedelta(hours=TICKET_COOLDOWN_HOURS)
    # Pick tickets we haven't emitted signals for yet
    tickets_qs = Ticket.objects.filter(
        team=team,
        signal_emitted_at__isnull=True,
        created_at__lte=cutoff,
    )
    if config.where_clause:
        tickets_qs = tickets_qs.extra(where=[config.where_clause])
    tickets_qs = tickets_qs.values(*config.fields).order_by(config.partition_field)[: config.max_records]
    tickets = list(tickets_qs)
    if not tickets:
        return []
    ticket_ids = [t["id"] for t in tickets]
    logger.info(
        "Fetched conversation tickets for signal emission",
        team_id=team.id,
        ticket_count=len(tickets),
        signals_type="conversations-signals",
    )
    # Fetch all comments for these tickets in one query.
    # Each message is a (author_type, content) tuple so the emitter can attribute them.
    comments_by_ticket: dict[str, list[tuple[str, str]]] = {}
    comments_qs = (
        Comment.objects.filter(
            team=team,
            scope="conversations_ticket",
            item_id__in=[str(tid) for tid in ticket_ids],
            deleted=False,
        )
        .order_by("created_at")
        .values_list("item_id", "content", "item_context")
    )
    for item_id, content, item_context in comments_qs:
        if content:
            author_type = (item_context or {}).get("author_type", "customer")
            comments_by_ticket.setdefault(item_id, []).append((author_type, content))
    # Attach messages to each ticket record
    for ticket in tickets:
        ticket["messages"] = comments_by_ticket.get(str(ticket["id"]), [])
    # Mark tickets as emitted optimistically
    # TODO: Revisit if signal loss on transient pipeline failure becomes a concern
    Ticket.objects.filter(id__in=ticket_ids).update(signal_emitted_at=timezone.now())
    return tickets
