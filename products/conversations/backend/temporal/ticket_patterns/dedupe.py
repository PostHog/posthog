"""Redis memory of which tickets a spike has already been reported for.

The coordinator re-reads the same window every 15 minutes, so without this a single spike would
fire on every tick until its tickets aged out. A cluster is only worth reporting when enough of
its tickets are new, which makes an ongoing incident re-fire as it grows rather than on a timer.
"""

from __future__ import annotations

from django.core.cache import cache

import structlog

from products.conversations.backend.temporal.ticket_patterns.constants import REPORTED_TICKET_TTL_SECONDS

logger = structlog.get_logger(__name__)


def _key(team_id: int, ticket_id: str) -> str:
    return f"conversations:ticket_patterns:reported:{team_id}:{ticket_id}"


def unreported_ticket_ids(team_id: int, ticket_ids: list[str]) -> list[str]:
    """The subset of ``ticket_ids`` no cluster has been reported for yet, order preserved.

    Fails open: a Redis outage means a duplicate report, which is a duplicate Slack post. Failing
    closed would mean silence during the outage, and silence is the failure this feature exists
    to prevent.
    """
    if not ticket_ids:
        return []
    keys = {_key(team_id, ticket_id): ticket_id for ticket_id in ticket_ids}
    try:
        reported = set(cache.get_many(list(keys)))
    except Exception:
        logger.warning("ticket_patterns: dedupe read failed", team_id=team_id, exc_info=True)
        return list(ticket_ids)
    return [ticket_id for key, ticket_id in keys.items() if key not in reported]


def mark_reported(team_id: int, ticket_ids: list[str]) -> None:
    if not ticket_ids:
        return
    try:
        cache.set_many({_key(team_id, t): True for t in ticket_ids}, timeout=REPORTED_TICKET_TTL_SECONDS)
    except Exception:
        logger.warning("ticket_patterns: dedupe write failed", team_id=team_id, exc_info=True)
