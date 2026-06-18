import json
from dataclasses import dataclass
from datetime import timedelta

import structlog
from temporalio import activity, workflow
from temporalio.common import RetryPolicy

from posthog.temporal.common.base import PostHogWorkflow

POSTHOG_SLACK_INBOX_ONBOARDING_TIMEOUT_SECONDS = 5 * 60
logger = structlog.get_logger(__name__)


@dataclass
class PostHogSlackInboxOnboardingInputs:
    integration_id: int


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
            # Single attempt: the onboarding DM is not idempotent, so a retry after a post-then-crash
            # would re-DM the installer. Channel create/invite are idempotent and onboarding is
            # best-effort, so we accept "no retry" over "possible duplicate DM".
            retry_policy=RetryPolicy(maximum_attempts=1),
        )


@activity.defn
def run_posthog_slack_inbox_onboarding_activity(inputs: PostHogSlackInboxOnboardingInputs) -> None:
    run_posthog_slack_inbox_onboarding(inputs.integration_id)


def run_posthog_slack_inbox_onboarding(integration_id: int) -> None:
    """Create #posthog-inbox and DM the installer for a fresh Slack install. Plain function so it
    is callable outside the Temporal worker (and unit-testable without an activity environment)."""
    from posthog.models.integration import Integration

    from products.slack_app.backend.onboarding import run_install_onboarding

    try:
        integration = Integration.objects.select_related("team", "team__organization").get(
            id=integration_id, kind="slack"
        )
    except Integration.DoesNotExist:
        logger.info("posthog_slack_inbox_onboarding_integration_gone", integration_id=integration_id)
        return
    run_install_onboarding(integration)
