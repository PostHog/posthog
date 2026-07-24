from datetime import timedelta
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy

from posthog.temporal.ai.telegram_app.activities import (
    cascade_telegram_repository_activity,
    classify_telegram_task_needs_repo_activity,
    create_telegram_task_activity,
    enforce_telegram_billing_quota_activity,
    post_telegram_reply_activity,
)
from posthog.temporal.ai.telegram_app.types import TelegramAppMentionWorkflowInputs
from posthog.temporal.common.base import PostHogWorkflow

_ACTIVITY_TIMEOUT = timedelta(minutes=2)
_CREATE_TIMEOUT = timedelta(minutes=5)
_RETRY_POLICY = RetryPolicy(maximum_attempts=3)


async def _execute(activity_fn: Any, *args: Any, timeout: timedelta = _ACTIVITY_TIMEOUT) -> Any:
    return await workflow.execute_activity(
        activity_fn,
        args=args,
        start_to_close_timeout=timeout,
        retry_policy=_RETRY_POLICY,
    )


@workflow.defn(name="telegram-app-mention-processing")
class TelegramAppMentionWorkflow(PostHogWorkflow):
    """Minimal Telegram mention loop: quota gate, fast repo cascade, task creation.

    No picker, no discovery agent, no signals — when the cascade can't resolve a
    repository on its own, the workflow asks the user to name one and stops.
    """

    @workflow.run
    async def run(self, inputs: TelegramAppMentionWorkflowInputs) -> None:
        if await _execute(enforce_telegram_billing_quota_activity, inputs):
            await _execute(
                post_telegram_reply_activity,
                inputs,
                "Your team is out of AI credits, so I can't start this task. Manage billing in PostHog to top up.",
            )
            return

        outcome = await _execute(cascade_telegram_repository_activity, inputs)
        if outcome.mode == "agent_needed":
            # Multiple repos and no explicit mention. Analytics and config questions
            # don't need a repo at all — classify before demanding one, otherwise
            # every question in a multi-repo workspace dead-ends here.
            if await _execute(classify_telegram_task_needs_repo_activity, inputs):
                await _execute(
                    post_telegram_reply_activity,
                    inputs,
                    "You have several repos connected. Tell me which one to use (like org/repo) and mention me again.",
                )
                return
            await _execute(create_telegram_task_activity, inputs, None, timeout=_CREATE_TIMEOUT)
            return
        if outcome.mode == "needs_user_github":
            await _execute(
                post_telegram_reply_activity,
                inputs,
                "Connect your GitHub account in PostHog first, then mention me again.",
            )
            return

        # "auto" and "no_repo" both create a task; no-repo tasks can still investigate data.
        await _execute(create_telegram_task_activity, inputs, outcome.repository, timeout=_CREATE_TIMEOUT)
