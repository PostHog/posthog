"""Redis record of the spikes a team was told about recently, for the inbox banner.

The captured event stays the durable record. This is a short-lived copy the inbox can read
without going through ingestion, so a banner appears as soon as detection runs rather than once
the event lands in ClickHouse. An eviction costs a banner, never a report.
"""

from __future__ import annotations

import json

from django.core.cache import cache
from django.utils import timezone

import structlog

logger = structlog.get_logger(__name__)

RECENT_SPIKES_TTL_SECONDS = 24 * 60 * 60
MAX_RECENT_SPIKES = 5


def _key(team_id: int) -> str:
    return f"conversations:ticket_patterns:recent:{team_id}"


def spike_key(spike: dict) -> str:
    """Identity of one reported spike: the topic and when detection reported it.

    Keyed on both so the same topic firing again later is a new spike rather than one that
    inherits an old dismissal.
    """
    return f"{spike.get('topic', '')}:{spike.get('detected_at', '')}"


def dismiss_spike(team_id: int, key: str, user_name: str) -> bool:
    """Mark one spike dismissed for the whole project. False when the key matches nothing.

    Dismissal lives on the spike record, so it expires with the banner it hides. There is nothing
    to clean up, and a team never inherits a dismissal for a spike they can no longer see.
    """
    spikes = recent_spikes(team_id)
    for spike in spikes:
        if spike_key(spike) == key:
            spike["dismissed_by"] = user_name
            spike["dismissed_at"] = timezone.now().isoformat()
            break
    else:
        return False
    try:
        cache.set(_key(team_id), json.dumps(spikes), timeout=RECENT_SPIKES_TTL_SECONDS)
    except Exception:
        logger.warning("ticket_patterns: dismiss write failed", team_id=team_id, exc_info=True)
        return False
    return True


def record_spike(team_id: int, spike: dict) -> None:
    """Put one spike at the front of the team's recent list, newest first."""
    try:
        spikes = [spike, *recent_spikes(team_id)][:MAX_RECENT_SPIKES]
        cache.set(_key(team_id), json.dumps(spikes), timeout=RECENT_SPIKES_TTL_SECONDS)
    except Exception:
        # The banner is a convenience; losing it must not fail the run that already reported.
        logger.warning("ticket_patterns: recent write failed", team_id=team_id, exc_info=True)


def recent_spikes(team_id: int) -> list[dict]:
    try:
        raw = cache.get(_key(team_id))
    except Exception:
        logger.warning("ticket_patterns: recent read failed", team_id=team_id, exc_info=True)
        return []
    if not raw:
        return []
    try:
        spikes = json.loads(raw)
    except (TypeError, ValueError):
        return []
    return spikes if isinstance(spikes, list) else []
