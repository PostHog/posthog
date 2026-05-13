"""MCP analytics Temporal workflows."""

import json
from datetime import timedelta

from temporalio import workflow

from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.mcp_analytics.activities import cluster_intents_activity, emit_mcp_embedding_requests_activity
from posthog.temporal.mcp_analytics.constants import (
    COMPUTE_ACTIVITY_TIMEOUT,
    DEFAULT_RETRY_POLICY,
    EMBEDDING_ACTIVITY_TIMEOUT,
    EMBEDDING_EMIT_WORKFLOW_NAME,
    INTENT_CLUSTERING_WORKFLOW_NAME,
)
from posthog.temporal.mcp_analytics.models import (
    EmbeddingEmitActivityInputs,
    EmbeddingEmitResult,
    EmbeddingEmitWorkflowInputs,
    IntentClusteringActivityInputs,
    IntentClusteringResult,
    IntentClusteringWorkflowInputs,
)


@workflow.defn(name=EMBEDDING_EMIT_WORKFLOW_NAME)
class MCPEmbeddingEmitWorkflow(PostHogWorkflow):
    """Daily workflow that emits embedding requests for new MCP intents and span text.

    The Rust embedding-worker handles OpenAI calls + ClickHouse writes asynchronously,
    so this workflow just queues requests and returns.
    """

    @staticmethod
    def parse_inputs(inputs: list[str]) -> EmbeddingEmitWorkflowInputs:
        if inputs:
            return EmbeddingEmitWorkflowInputs(**json.loads(inputs[0]))
        return EmbeddingEmitWorkflowInputs(team_id=0)

    @workflow.run
    async def run(self, inputs: EmbeddingEmitWorkflowInputs) -> EmbeddingEmitResult:
        now = workflow.now()
        window_end = now.isoformat()
        window_start = (now - timedelta(days=inputs.lookback_days)).isoformat()

        return await workflow.execute_activity(
            emit_mcp_embedding_requests_activity,
            args=[
                EmbeddingEmitActivityInputs(
                    team_id=inputs.team_id,
                    window_start=window_start,
                    window_end=window_end,
                    max_intent_samples=inputs.max_intent_samples,
                    max_span_samples=inputs.max_span_samples,
                    embedding_model=inputs.embedding_model,
                )
            ],
            start_to_close_timeout=EMBEDDING_ACTIVITY_TIMEOUT,
            retry_policy=DEFAULT_RETRY_POLICY,
        )


@workflow.defn(name=INTENT_CLUSTERING_WORKFLOW_NAME)
class MCPIntentClusteringWorkflow(PostHogWorkflow):
    """Daily workflow that clusters $mcp_intent values and emits $mcp_intent_clusters.

    Reads embeddings produced by `MCPEmbeddingEmitWorkflow`. Intents whose embeddings
    haven't landed yet are skipped and picked up on the next run.
    """

    @staticmethod
    def parse_inputs(inputs: list[str]) -> IntentClusteringWorkflowInputs:
        if inputs:
            return IntentClusteringWorkflowInputs(**json.loads(inputs[0]))
        return IntentClusteringWorkflowInputs(team_id=0)

    @workflow.run
    async def run(self, inputs: IntentClusteringWorkflowInputs) -> IntentClusteringResult:
        now = workflow.now()
        window_end = now.isoformat()
        window_start = (now - timedelta(days=inputs.lookback_days)).isoformat()

        return await workflow.execute_activity(
            cluster_intents_activity,
            args=[
                IntentClusteringActivityInputs(
                    team_id=inputs.team_id,
                    window_start=window_start,
                    window_end=window_end,
                    max_samples=inputs.max_samples,
                    embedding_model=inputs.embedding_model,
                )
            ],
            start_to_close_timeout=COMPUTE_ACTIVITY_TIMEOUT,
            retry_policy=DEFAULT_RETRY_POLICY,
        )
