"""Daily intent clustering workflow.

Thin wrapper over ``compute_intent_clusters_activity``. The single-activity
design is justified in ``activities.py``; the workflow's job here is to
provide retry semantics, the deterministic replay envelope, and a stable
workflow-id namespace.
"""

import json

from temporalio import workflow

from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.mcp_analytics.intent_clustering.activities import compute_intent_clusters_activity
from posthog.temporal.mcp_analytics.intent_clustering.constants import (
    COMPUTE_ACTIVITY_RETRY_POLICY,
    COMPUTE_ACTIVITY_TIMEOUT,
    COMPUTE_HEARTBEAT_TIMEOUT,
    COMPUTE_SCHEDULE_TO_CLOSE_TIMEOUT,
    WORKFLOW_NAME,
)
from posthog.temporal.mcp_analytics.intent_clustering.models import (
    IntentClusteringResult,
    IntentClusteringWorkflowInputs,
)


@workflow.defn(name=WORKFLOW_NAME)
class DailyIntentClusteringWorkflow(PostHogWorkflow):
    """Recompute the intent cluster snapshot for one team."""

    @staticmethod
    def parse_inputs(inputs: list[str]) -> IntentClusteringWorkflowInputs:
        """Parse workflow inputs from CLI arguments (JSON string).

        Used by ``execute_temporal_workflow`` and similar entrypoints.
        """
        if inputs:
            data = json.loads(inputs[0])
            return IntentClusteringWorkflowInputs(**data)
        return IntentClusteringWorkflowInputs(team_id=0)

    @workflow.run
    async def run(self, inputs: IntentClusteringWorkflowInputs) -> IntentClusteringResult:
        return await workflow.execute_activity(
            compute_intent_clusters_activity,
            inputs,
            start_to_close_timeout=COMPUTE_ACTIVITY_TIMEOUT,
            schedule_to_close_timeout=COMPUTE_SCHEDULE_TO_CLOSE_TIMEOUT,
            heartbeat_timeout=COMPUTE_HEARTBEAT_TIMEOUT,
            retry_policy=COMPUTE_ACTIVITY_RETRY_POLICY,
        )
