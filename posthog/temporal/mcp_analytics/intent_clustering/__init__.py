"""MCP analytics intent clustering — Temporal workflow exports.

Registered against ``settings.MCPA_TASK_QUEUE`` by
``posthog/management/commands/start_temporal_worker.py``.
"""

from posthog.temporal.mcp_analytics.intent_clustering.activities import compute_intent_clusters_activity
from posthog.temporal.mcp_analytics.intent_clustering.coordinator import IntentClusteringCoordinatorWorkflow
from posthog.temporal.mcp_analytics.intent_clustering.team_discovery import get_team_ids_for_mcp_analytics
from posthog.temporal.mcp_analytics.intent_clustering.workflow import DailyIntentClusteringWorkflow

MCP_ANALYTICS_INTENT_CLUSTERING_WORKFLOWS = [
    DailyIntentClusteringWorkflow,
    IntentClusteringCoordinatorWorkflow,
]

MCP_ANALYTICS_INTENT_CLUSTERING_ACTIVITIES = [
    compute_intent_clusters_activity,
    get_team_ids_for_mcp_analytics,
]

__all__ = [
    "DailyIntentClusteringWorkflow",
    "IntentClusteringCoordinatorWorkflow",
    "MCP_ANALYTICS_INTENT_CLUSTERING_ACTIVITIES",
    "MCP_ANALYTICS_INTENT_CLUSTERING_WORKFLOWS",
    "compute_intent_clusters_activity",
    "get_team_ids_for_mcp_analytics",
]
