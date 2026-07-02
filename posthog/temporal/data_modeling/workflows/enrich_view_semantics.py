import json
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.data_modeling.activities.enrich_view_semantics import (
    EnrichViewSemanticsInputs,
    enrich_view_semantics_activity,
)


@workflow.defn(name="data-modeling-enrich-view-semantics")
class EnrichViewSemanticsWorkflow(PostHogWorkflow):
    """Generate semantic descriptions for one data-modeling view. Fire-and-forget, on the metadata queue."""

    @staticmethod
    def parse_inputs(inputs: list[str]) -> EnrichViewSemanticsInputs:
        loaded = json.loads(inputs[0])
        return EnrichViewSemanticsInputs(team_id=loaded["team_id"], saved_query_id=loaded["saved_query_id"])

    @workflow.run
    async def run(self, inputs: EnrichViewSemanticsInputs) -> None:
        await workflow.execute_activity(
            enrich_view_semantics_activity,
            inputs,
            start_to_close_timeout=timedelta(minutes=15),
            heartbeat_timeout=timedelta(minutes=2),
            retry_policy=RetryPolicy(maximum_attempts=2),
        )
