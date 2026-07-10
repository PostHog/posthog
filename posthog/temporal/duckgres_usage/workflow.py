"""Temporal workflow that polls duckgres's billing pull API on a schedule.

Two activities: the poll (fetch + persist — potentially tens of MB of rows that
can't cross the workflow boundary) records the watermark to ack, then — if there
is one — a small ack activity performs the POST. Splitting the ack means a
transient ack failure retries just the POST, not the whole fetch+persist.
Scheduled every 10 minutes (`posthog/temporal/schedule.py`) with overlap policy
SKIP, so two polls are never in flight at once.
"""

import json
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.duckgres_usage.activities import ack_duckgres_usage, poll_duckgres_usage
from posthog.temporal.duckgres_usage.types import PollDuckgresUsageInputs, PollDuckgresUsageResult

POLL_DUCKGRES_USAGE_WORKFLOW = "poll-duckgres-usage"
POLL_DUCKGRES_USAGE_SCHEDULE_ID = "poll-duckgres-usage-schedule"


@workflow.defn(name=POLL_DUCKGRES_USAGE_WORKFLOW)
class PollDuckgresUsageWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> PollDuckgresUsageInputs:
        if not inputs:
            return PollDuckgresUsageInputs()
        return PollDuckgresUsageInputs(**json.loads(inputs[0]))

    @workflow.run
    async def run(self, inputs: PollDuckgresUsageInputs) -> PollDuckgresUsageResult:
        result = await workflow.execute_activity(
            poll_duckgres_usage,
            inputs,
            start_to_close_timeout=timedelta(minutes=10),
            retry_policy=RetryPolicy(maximum_attempts=3, initial_interval=timedelta(seconds=30)),
            heartbeat_timeout=timedelta(minutes=2),
        )
        # The poll committed the watermark (record-before-ack); acking is a small
        # POST in its own activity so a transient failure doesn't re-run the pull.
        if result.ack_watermark is not None:
            await workflow.execute_activity(
                ack_duckgres_usage,
                result.ack_watermark,
                start_to_close_timeout=timedelta(minutes=1),
                retry_policy=RetryPolicy(maximum_attempts=3, initial_interval=timedelta(seconds=10)),
            )
        return result
