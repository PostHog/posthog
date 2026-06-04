"""MCP analytics intent clustering — Temporal workflow exports.

Registered against ``settings.MCPA_TASK_QUEUE`` by
``posthog/management/commands/start_temporal_worker.py``.
"""

from posthog.temporal.mcp_analytics.intent_clustering.activities import compute_intent_clusters_activity
from posthog.temporal.mcp_analytics.intent_clustering.workflow import DailyIntentClusteringWorkflow

MCP_ANALYTICS_INTENT_CLUSTERING_WORKFLOWS = [
    DailyIntentClusteringWorkflow,
]

MCP_ANALYTICS_INTENT_CLUSTERING_ACTIVITIES = [
    compute_intent_clusters_activity,
]

__all__ = [
    "DailyIntentClusteringWorkflow",
    "MCP_ANALYTICS_INTENT_CLUSTERING_ACTIVITIES",
    "MCP_ANALYTICS_INTENT_CLUSTERING_WORKFLOWS",
    "compute_intent_clusters_activity",
]
