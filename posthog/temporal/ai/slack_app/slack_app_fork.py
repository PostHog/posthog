"""Forking a channel thread into a DM.

Someone reading a thread wants to dig into it — understand the code, ask the
obvious question — without turning the thread into their own tutorial. The "…"
menu under a reply opens a private DM that has already read the thread, and
carries on there.

The run does not start here. The DM asks what the reader wants to know, because
the menu has nowhere to type it, and their reply is the actual request. That
reply arrives as an ordinary ``message.im`` with nothing on it to say the thread
is a fork — the ``SlackThreadTaskMapping`` that would say so is written by task
creation, which has not happened yet. So the forked thread is parked in
``slack_fork_context``, and ``_handle_assistant_dm_message`` reads it back and starts
the ordinary mention workflow against it.

That workflow then answers in the DM while building its ``<slack_thread_context>``
from the channel thread instead — everything downstream, from repo selection to
follow-ups, is the mention path untouched.
"""

import json
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

from posthog.temporal.ai.slack_app.activities.fork import process_slack_app_fork_thread_activity
from posthog.temporal.ai.slack_app.types import SlackAppForkThreadInputs
from posthog.temporal.common.base import PostHogWorkflow

SLACK_APP_FORK_TIMEOUT_SECONDS = 5 * 60


@workflow.defn(name="slack-app-fork-thread")
class SlackAppForkThreadWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> SlackAppForkThreadInputs:
        loaded = json.loads(inputs[0])
        return SlackAppForkThreadInputs(**loaded)

    @workflow.run
    async def run(self, inputs: SlackAppForkThreadInputs) -> None:
        await workflow.execute_activity(
            process_slack_app_fork_thread_activity,
            args=(inputs,),
            start_to_close_timeout=timedelta(seconds=SLACK_APP_FORK_TIMEOUT_SECONDS),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
