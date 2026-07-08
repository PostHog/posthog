"""Temporal workflow that polls duckgres's billing pull API on a schedule.

Thin wrapper around the single poll activity — see `activities.py` for the
fetch → commit → ack mechanics and `acking.py` for the day-boundary rule.
Scheduled every 10 minutes (`posthog/temporal/schedule.py`) with overlap
policy SKIP, so two polls are never in flight at once.
"""

import json
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.duckgres_usage.activities import poll_duckgres_usage
from posthog.temporal.duckgres_usage.types import PollDuckgresUsageInputs, PollDuckgresUsageResult


@workflow.defn(name="poll-duckgres-usage")
class PollDuckgresUsageWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> PollDuckgresUsageInputs:
        if not inputs:
            return PollDuckgresUsageInputs()
        return PollDuckgresUsageInputs(**json.loads(inputs[0]))

    @workflow.run
    async def run(self, inputs: PollDuckgresUsageInputs) -> PollDuckgresUsageResult:
        return await workflow.execute_activity(
            poll_duckgres_usage,
            inputs,
            start_to_close_timeout=timedelta(minutes=10),
            retry_policy=RetryPolicy(maximum_attempts=3, initial_interval=timedelta(seconds=30)),
            heartbeat_timeout=timedelta(minutes=2),
        )
