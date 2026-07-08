import json
from datetime import timedelta

import structlog
from temporalio import workflow
from temporalio.common import RetryPolicy

from posthog.temporal.ai.slack_app.activities.first_patrol import (
    collect_first_patrol_digest_activity,
    post_first_patrol_digest_activity,
)
from posthog.temporal.ai.slack_app.types import PostHogSlackFirstPatrolInputs
from posthog.temporal.common.base import PostHogWorkflow

# Give the immediate first runs (dispatched at provisioning, ~15 min ceiling each) time to
# finish before the first check; retry once for coordinator/queue lag, then give up silently.
FIRST_PATROL_INITIAL_DELAY_SECONDS = 45 * 60
FIRST_PATROL_RETRY_DELAY_SECONDS = 30 * 60
FIRST_PATROL_ACTIVITY_TIMEOUT_SECONDS = 2 * 60

logger = structlog.get_logger(__name__)


@workflow.defn(name="posthog-slack-first-patrol")
class PostHogSlackFirstPatrolWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> PostHogSlackFirstPatrolInputs:
        loaded = json.loads(inputs[0])
        return PostHogSlackFirstPatrolInputs(**loaded)

    @workflow.run
    async def run(self, inputs: PostHogSlackFirstPatrolInputs) -> None:
        await workflow.sleep(timedelta(seconds=FIRST_PATROL_INITIAL_DELAY_SECONDS))
        digest = await workflow.execute_activity(
            collect_first_patrol_digest_activity,
            args=(inputs,),
            start_to_close_timeout=timedelta(seconds=FIRST_PATROL_ACTIVITY_TIMEOUT_SECONDS),
            retry_policy=RetryPolicy(maximum_attempts=2),
        )
        if digest is None:
            # Nothing to DM yet — no completed runs (queue lag, quota skip) or a clean patrol
            # so far. One more chance for a late finding, then silence.
            await workflow.sleep(timedelta(seconds=FIRST_PATROL_RETRY_DELAY_SECONDS))
            digest = await workflow.execute_activity(
                collect_first_patrol_digest_activity,
                args=(inputs,),
                start_to_close_timeout=timedelta(seconds=FIRST_PATROL_ACTIVITY_TIMEOUT_SECONDS),
                retry_policy=RetryPolicy(maximum_attempts=2),
            )
        if digest is None:
            return
        await workflow.execute_activity(
            post_first_patrol_digest_activity,
            args=(inputs, digest),
            start_to_close_timeout=timedelta(seconds=FIRST_PATROL_ACTIVITY_TIMEOUT_SECONDS),
            # Single attempt: the DM isn't idempotent — a retry after a post-then-crash
            # would double-message the user. Best-effort over duplicates.
            retry_policy=RetryPolicy(maximum_attempts=1),
        )
