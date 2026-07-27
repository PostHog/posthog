import json
from datetime import timedelta

import structlog
from temporalio import workflow
from temporalio.common import RetryPolicy

from posthog.temporal.ai.slack_app.activities.onboarding import run_posthog_slack_inbox_onboarding_activity
from posthog.temporal.ai.slack_app.types import PostHogSlackInboxOnboardingInputs
from posthog.temporal.common.base import PostHogWorkflow

POSTHOG_SLACK_INBOX_ONBOARDING_TIMEOUT_SECONDS = 5 * 60
logger = structlog.get_logger(__name__)


@workflow.defn(name="posthog-slack-inbox-onboarding")
class PostHogSlackInboxOnboardingWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> PostHogSlackInboxOnboardingInputs:
        loaded = json.loads(inputs[0])
        return PostHogSlackInboxOnboardingInputs(**loaded)

    @workflow.run
    async def run(self, inputs: PostHogSlackInboxOnboardingInputs) -> None:
        await workflow.execute_activity(
            run_posthog_slack_inbox_onboarding_activity,
            args=(inputs,),
            start_to_close_timeout=timedelta(seconds=POSTHOG_SLACK_INBOX_ONBOARDING_TIMEOUT_SECONDS),
            # Single attempt: the onboarding DM isn't idempotent, so a retry after a post-then-crash
            # would re-DM the installer. Onboarding is best-effort, so we accept "no retry" over a dup DM.
            retry_policy=RetryPolicy(maximum_attempts=1),
        )
