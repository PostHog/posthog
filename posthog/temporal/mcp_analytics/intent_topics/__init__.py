"""MCP analytics intent topics pipeline — Temporal exports.

Registered against ``settings.MCPA_TASK_QUEUE`` next to the legacy intent clustering workflows.
"""

from posthog.temporal.mcp_analytics.intent_topics.activities import (
    assign_intent_topics_activity,
    reassign_after_refit_activity,
    refit_intent_topics_activity,
    sync_intent_embeddings_activity,
)
from posthog.temporal.mcp_analytics.intent_topics.coordinator import IntentTopicsCoordinatorWorkflow
from posthog.temporal.mcp_analytics.intent_topics.workflow import IntentTopicsWorkflow

MCP_ANALYTICS_INTENT_TOPICS_WORKFLOWS = [IntentTopicsWorkflow, IntentTopicsCoordinatorWorkflow]

MCP_ANALYTICS_INTENT_TOPICS_ACTIVITIES = [
    sync_intent_embeddings_activity,
    assign_intent_topics_activity,
    refit_intent_topics_activity,
    reassign_after_refit_activity,
]

__all__ = [
    "IntentTopicsCoordinatorWorkflow",
    "IntentTopicsWorkflow",
    "MCP_ANALYTICS_INTENT_TOPICS_ACTIVITIES",
    "MCP_ANALYTICS_INTENT_TOPICS_WORKFLOWS",
]
