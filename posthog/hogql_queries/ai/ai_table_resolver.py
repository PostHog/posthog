from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING

import posthoganalytics

if TYPE_CHECKING:
    from posthog.models import Team

AI_EVENTS_TTL_DAYS = 30


def is_ai_events_enabled(team: Team) -> bool:
    return posthoganalytics.feature_enabled(
        "ai-events-table-rollout",
        str(team.id),
        groups={"organization": str(team.organization_id)},
        group_properties={"organization": {"id": str(team.organization_id)}},
        send_feature_flag_events=False,
    )


# Canonical Python list. Node.js mirror: nodejs/src/ingestion/ai/process-ai-event.ts
AI_EVENT_NAMES = frozenset(
    {
        "$ai_generation",
        "$ai_span",
        "$ai_trace",
        "$ai_embedding",
        "$ai_metric",
        "$ai_feedback",
        "$ai_evaluation",
    }
)


def is_within_ai_events_ttl(date_from: datetime, now: datetime) -> bool:
    """True if date_from is within the ai_events TTL window.

    Includes a 1-day buffer because date pickers truncate to midnight (making
    "Last 30 days" slightly over 30 calendar days) and ai_events uses
    ttl_only_drop_parts=1, so data survives until the full day partition expires.
    """
    # Strip timezone info to avoid naive/aware comparison errors
    date_from_naive = date_from.replace(tzinfo=None)
    now_naive = now.replace(tzinfo=None)
    cutoff = now_naive - timedelta(days=AI_EVENTS_TTL_DAYS + 1)
    return date_from_naive >= cutoff


def validate_ai_event_names(events: list[str]) -> None:
    """Raise if any event name is not a recognized AI event."""
    invalid = set(events) - AI_EVENT_NAMES
    if invalid:
        raise ValueError(f"AiEventsQuery only supports AI events, got: {invalid}")
