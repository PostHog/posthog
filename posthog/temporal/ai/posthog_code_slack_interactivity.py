import json
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import structlog
from temporalio import activity, workflow
from temporalio.common import RetryPolicy

from posthog.temporal.common.base import PostHogWorkflow

POSTHOG_CODE_SLACK_INTERACTIVITY_TIMEOUT_SECONDS = 5 * 60
logger = structlog.get_logger(__name__)


@dataclass
class PostHogCodeSlackInteractivityInputs:
    payload: dict[str, Any]


@workflow.defn(name="posthog-code-slack-terminate-task-processing")
class PostHogCodeSlackTerminateTaskWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> PostHogCodeSlackInteractivityInputs:
        loaded = json.loads(inputs[0])
        return PostHogCodeSlackInteractivityInputs(**loaded)

    @workflow.run
    async def run(self, inputs: PostHogCodeSlackInteractivityInputs) -> None:
        await workflow.execute_activity(
            process_posthog_code_terminate_task_activity,
            args=(inputs,),
            start_to_close_timeout=timedelta(seconds=POSTHOG_CODE_SLACK_INTERACTIVITY_TIMEOUT_SECONDS),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )


@activity.defn
def process_posthog_code_terminate_task_activity(inputs: PostHogCodeSlackInteractivityInputs) -> None:
    process_posthog_code_task_termination_payload(inputs.payload)


def process_posthog_code_task_termination_payload(payload: dict[str, Any]) -> None:
    from posthog.models.integration import Integration, SlackIntegration
    from posthog.temporal.common.client import sync_connect

    from products.tasks.backend.models import TaskRun
    from products.tasks.backend.services.agent_command import send_cancel
    from products.tasks.backend.services.connection_token import create_sandbox_connection_token
    from products.tasks.backend.temporal.process_task.workflow import ProcessTaskWorkflow

    actions = payload.get("actions", [])
    action = next((a for a in actions if a.get("action_id") == "posthog_code_terminate_task"), None)
    if not action:
        logger.warning("posthog_code_terminate_no_action")
        return

    action_value = action.get("value", "")
    if not action_value:
        logger.warning("posthog_code_terminate_no_value")
        return

    try:
        value = json.loads(action_value)
    except json.JSONDecodeError:
        logger.warning("posthog_code_terminate_invalid_value")
        return

    run_id = value.get("run_id")
    integration_id = value.get("integration_id")
    expected_user_id = value.get("mentioning_slack_user_id")
    thread_ts_from_value = value.get("thread_ts")
    requesting_user_id = payload.get("user", {}).get("id")
    slack_team_id = payload.get("team", {}).get("id")

    if not run_id or not integration_id:
        logger.warning("posthog_code_terminate_missing_context", run_id=run_id, integration_id=integration_id)
        return

    if not slack_team_id:
        logger.warning("posthog_code_terminate_missing_slack_team", run_id=run_id)
        return

    if not expected_user_id:
        logger.warning("posthog_code_terminate_missing_expected_user", run_id=run_id)
        return

    if requesting_user_id != expected_user_id:
        logger.warning(
            "posthog_code_terminate_user_mismatch",
            expected=expected_user_id,
            actual=requesting_user_id,
            run_id=run_id,
        )
        return

    try:
        integration = Integration.objects.get(
            id=integration_id, kind="slack-posthog-code", integration_id=slack_team_id
        )
    except Integration.DoesNotExist:
        logger.warning("posthog_code_terminate_integration_not_found", integration_id=integration_id)
        return

    channel = payload.get("channel", {}).get("id") or payload.get("container", {}).get("channel_id")
    message_ts = payload.get("message", {}).get("ts")
    thread_ts = thread_ts_from_value or payload.get("message", {}).get("thread_ts") or message_ts

    try:
        task_run = TaskRun.objects.select_related("task").get(id=run_id, team_id=integration.team_id)
    except TaskRun.DoesNotExist:
        logger.warning("posthog_code_terminate_run_not_found", run_id=run_id)
        return

    if task_run.is_terminal:
        logger.info("posthog_code_terminate_run_already_terminal", run_id=run_id, status=task_run.status)
        if channel and thread_ts:
            try:
                slack_client = SlackIntegration(integration).client
                slack_client.chat_postMessage(
                    channel=channel,
                    thread_ts=thread_ts,
                    text=f"This run is already `{task_run.status}`. There is nothing to terminate.",
                )
            except Exception:
                logger.warning("posthog_code_terminate_terminal_feedback_failed", run_id=run_id)
        return

    auth_token = None
    created_by = task_run.task.created_by
    if created_by and isinstance(created_by.id, int):
        distinct_id = created_by.distinct_id or f"user_{created_by.id}"
        try:
            auth_token = create_sandbox_connection_token(task_run, user_id=created_by.id, distinct_id=distinct_id)
        except Exception as e:
            logger.warning("posthog_code_terminate_auth_token_failed", run_id=run_id, error=str(e))

    cancel_result = send_cancel(task_run, auth_token=auth_token)
    if cancel_result.success:
        logger.info("posthog_code_terminate_command_dispatched", run_id=run_id)
    else:
        logger.warning(
            "posthog_code_terminate_command_failed_fallback_signal",
            run_id=run_id,
            error=cancel_result.error,
            status_code=cancel_result.status_code,
            retryable=cancel_result.retryable,
        )

    try:
        client = sync_connect()
        workflow_id = task_run.workflow_id
        handle = client.get_workflow_handle(workflow_id)
        import asyncio

        asyncio.run(handle.signal(ProcessTaskWorkflow.complete_task, args=["cancelled", "Run terminated from Slack"]))
        logger.info("posthog_code_terminate_signaled", run_id=run_id, workflow_id=workflow_id)
    except Exception as e:
        logger.exception("posthog_code_terminate_signal_failed", run_id=run_id, error=str(e))
        if not cancel_result.success:
            return

    if channel and message_ts:
        try:
            slack_client = SlackIntegration(integration).client
            progress_text = "*Working on task...* :hourglass_flowing_sand:\nTermination requested. Stopping run and cleaning up sandbox..."
            slack_client.chat_update(
                channel=channel,
                ts=message_ts,
                text=progress_text,
                blocks=[
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": progress_text,
                        },
                    }
                ],
            )
        except Exception:
            logger.warning("posthog_code_terminate_message_update_failed", run_id=run_id)
