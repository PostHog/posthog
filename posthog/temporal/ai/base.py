from typing import Any

from temporalio import activity

from posthog.temporal.common.base import PostHogWorkflow


class AgentBaseWorkflow(PostHogWorkflow):
    """Base temporal workflow for processing agents asynchronously."""

    async def run(self, inputs: Any) -> None:
        """Execute the agent workflow."""
        raise NotImplementedError


def is_user_initiated_activity_cancel() -> bool:
    """Whether the current activity is being cancelled because the workflow was cancelled externally.

    Distinguishes a user-initiated stop (workflow cancel propagated to the activity) from
    system-side cancellations like heartbeat starvation, start-to-close timeouts, or worker
    shutdown. Returns False if cancellation details are unavailable, including when called
    outside an activity context.

    Intended to be passed into BaseAgentRunner via `is_user_initiated_cancel` so the runner
    can suppress user-visible failure messages and error-tracking captures for stops.
    """
    details = activity.cancellation_details()
    return details is not None and details.cancel_requested
