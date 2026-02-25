import json
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from temporalio import activity, workflow
from temporalio.common import RetryPolicy

from posthog.temporal.common.base import PostHogWorkflow

TWIG_SLACK_INTERACTIVITY_TIMEOUT_SECONDS = 5 * 60


@dataclass
class TwigSlackInteractivityInputs:
    payload: dict[str, Any]


@workflow.defn(name="twig-slack-default-repo-selection-processing")
class TwigSlackDefaultRepoSelectionWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> TwigSlackInteractivityInputs:
        loaded = json.loads(inputs[0])
        return TwigSlackInteractivityInputs(**loaded)

    @workflow.run
    async def run(self, inputs: TwigSlackInteractivityInputs) -> None:
        await workflow.execute_activity(
            process_twig_default_repo_selection_activity,
            args=(inputs,),
            start_to_close_timeout=timedelta(seconds=TWIG_SLACK_INTERACTIVITY_TIMEOUT_SECONDS),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )


@workflow.defn(name="twig-slack-terminate-task-processing")
class TwigSlackTerminateTaskWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> TwigSlackInteractivityInputs:
        loaded = json.loads(inputs[0])
        return TwigSlackInteractivityInputs(**loaded)

    @workflow.run
    async def run(self, inputs: TwigSlackInteractivityInputs) -> None:
        await workflow.execute_activity(
            process_twig_terminate_task_activity,
            args=(inputs,),
            start_to_close_timeout=timedelta(seconds=TWIG_SLACK_INTERACTIVITY_TIMEOUT_SECONDS),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )


@activity.defn
def process_twig_default_repo_selection_activity(inputs: TwigSlackInteractivityInputs) -> None:
    from products.slack_app.backend.tasks import process_twig_repo_selection

    process_twig_repo_selection(inputs.payload)


@activity.defn
def process_twig_terminate_task_activity(inputs: TwigSlackInteractivityInputs) -> None:
    from products.slack_app.backend.tasks import process_twig_task_termination

    process_twig_task_termination(inputs.payload)
