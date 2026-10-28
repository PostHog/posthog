"""Per-team intent topics workflow: one run kind per execution."""

import json

from temporalio import workflow
from temporalio.exceptions import ApplicationError

from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.mcp_analytics.intent_topics.activities import (
    assign_intent_topics_activity,
    reassign_after_refit_activity,
    refit_intent_topics_activity,
    sync_intent_embeddings_activity,
)
from posthog.temporal.mcp_analytics.intent_topics.constants import (
    ACTIVITY_HEARTBEAT_TIMEOUT,
    ACTIVITY_RETRY_POLICY,
    ASSIGN_ACTIVITY_TIMEOUT,
    REFIT_ACTIVITY_TIMEOUT,
    SYNC_ACTIVITY_TIMEOUT,
    WORKFLOW_NAME,
)
from posthog.temporal.mcp_analytics.intent_topics.models import (
    RUN_KINDS,
    IntentTopicsWorkflowInputs,
    IntentTopicsWorkflowResult,
)


@workflow.defn(name=WORKFLOW_NAME)
class IntentTopicsWorkflow(PostHogWorkflow):
    """Run the hourly sync, the nightly assignment, or the weekly refit for one team."""

    @staticmethod
    def parse_inputs(inputs: list[str]) -> IntentTopicsWorkflowInputs:
        if inputs:
            return IntentTopicsWorkflowInputs(**json.loads(inputs[0]))
        return IntentTopicsWorkflowInputs(team_id=0)

    @workflow.run
    async def run(self, inputs: IntentTopicsWorkflowInputs) -> IntentTopicsWorkflowResult:
        if inputs.kind not in RUN_KINDS:
            raise ApplicationError(f"Unknown run kind {inputs.kind!r}; expected one of {RUN_KINDS}", non_retryable=True)
        result = IntentTopicsWorkflowResult(team_id=inputs.team_id, kind=inputs.kind)

        if inputs.kind == "sync":
            result.runs.append(
                await workflow.execute_activity(
                    sync_intent_embeddings_activity,
                    inputs,
                    start_to_close_timeout=SYNC_ACTIVITY_TIMEOUT,
                    heartbeat_timeout=ACTIVITY_HEARTBEAT_TIMEOUT,
                    retry_policy=ACTIVITY_RETRY_POLICY,
                )
            )
        elif inputs.kind == "assign":
            result.runs.append(
                await workflow.execute_activity(
                    assign_intent_topics_activity,
                    inputs,
                    start_to_close_timeout=ASSIGN_ACTIVITY_TIMEOUT,
                    heartbeat_timeout=ACTIVITY_HEARTBEAT_TIMEOUT,
                    retry_policy=ACTIVITY_RETRY_POLICY,
                )
            )
        else:
            refit = await workflow.execute_activity(
                refit_intent_topics_activity,
                inputs,
                start_to_close_timeout=REFIT_ACTIVITY_TIMEOUT,
                heartbeat_timeout=ACTIVITY_HEARTBEAT_TIMEOUT,
                retry_policy=ACTIVITY_RETRY_POLICY,
            )
            result.runs.append(refit)
            if refit.status == "succeeded":
                result.runs.append(
                    await workflow.execute_activity(
                        reassign_after_refit_activity,
                        inputs,
                        start_to_close_timeout=ASSIGN_ACTIVITY_TIMEOUT,
                        heartbeat_timeout=ACTIVITY_HEARTBEAT_TIMEOUT,
                        retry_policy=ACTIVITY_RETRY_POLICY,
                    )
                )
        return result
