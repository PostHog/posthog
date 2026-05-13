"""Emit $mcp_intent_clusters events to ClickHouse."""

import dataclasses
import uuid
from typing import Any

from posthog.models.event.util import create_event
from posthog.models.team import Team
from posthog.temporal.mcp_analytics.constants import EVENT_NAME_INTENT_CLUSTERS
from posthog.temporal.mcp_analytics.models import IntentClusteringResult


def emit_intent_clusters_event(team_id: int, result: IntentClusteringResult) -> uuid.UUID:
    """Write the final clustering result as a single $mcp_intent_clusters event.

    The frontend reads this event as the latest snapshot of candidate missing tools,
    same pattern as $ai_trace_clusters for LLM analytics.
    """
    team = Team.objects.get(id=team_id)
    event_uuid = uuid.uuid4()

    properties: dict[str, Any] = {
        "$mcp_clustering_run_id": result.clustering_run_id,
        "$mcp_window_start": result.window_start,
        "$mcp_window_end": result.window_end,
        "$mcp_total_intents_analyzed": result.num_intents_analyzed,
        "$mcp_clusters": [dataclasses.asdict(c) for c in result.clusters],
    }

    create_event(
        event_uuid=event_uuid,
        event=EVENT_NAME_INTENT_CLUSTERS,
        team=team,
        distinct_id=f"mcp_analytics_clustering_{team_id}",
        properties=properties,
    )
    return event_uuid
