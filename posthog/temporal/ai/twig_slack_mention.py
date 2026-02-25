import json
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from temporalio import activity, workflow
from temporalio.common import RetryPolicy

from posthog.temporal.common.base import PostHogWorkflow

TWIG_SLACK_MENTION_TIMEOUT_SECONDS = 10 * 60
TWIG_SLACK_PICKER_TIMEOUT_MINUTES = 15
TWIG_SLACK_MENTION_PICKER_GUIDANCE = (
    "Please select the repository for this task. "
    "Or @mention me again and include the exact repository as `org/repo`. "
    "You can also set a default with `@Twig default repo set` or `@Twig default repo set org/repo`."
)


@dataclass
class TwigSlackMentionWorkflowInputs:
    event: dict[str, Any]
    integration_id: int
    slack_team_id: str


@dataclass
class TwigSlackRepoDecisionData:
    mode: str
    repository: str | None
    reason: str
    repo_count: int


@workflow.defn(name="twig-slack-mention-processing")
class TwigSlackMentionWorkflow(PostHogWorkflow):
    def __init__(self) -> None:
        self._selected_repo: str | None = None

    @workflow.signal
    async def repo_selected(self, repository: str) -> None:
        if not self._selected_repo:
            self._selected_repo = repository

    @staticmethod
    def parse_inputs(inputs: list[str]) -> TwigSlackMentionWorkflowInputs:
        loaded = json.loads(inputs[0])
        return TwigSlackMentionWorkflowInputs(**loaded)

    @workflow.run
    async def run(self, inputs: TwigSlackMentionWorkflowInputs) -> None:
        event = inputs.event
        channel = event.get("channel")
        thread_ts = event.get("thread_ts") or event.get("ts")
        slack_user_id = event.get("user")

        if not channel or not thread_ts or not slack_user_id:
            return

        try:
            user_id = await _execute_twig_activity(
                resolve_twig_slack_user_activity, inputs, channel, thread_ts, slack_user_id
            )
            if not user_id:
                return

            handled_default_command = await _execute_twig_activity(
                handle_twig_default_repo_command_activity,
                inputs,
                channel,
                thread_ts,
                slack_user_id,
                user_id,
            )
            if handled_default_command:
                return

            thread_messages = await _execute_twig_activity(
                collect_twig_thread_messages_activity,
                inputs,
                channel,
                thread_ts,
            )
            if not thread_messages:
                return

            decision = await _execute_twig_activity(
                select_twig_repository_activity,
                inputs,
                channel,
                event.get("text", ""),
                thread_messages,
                user_id,
            )

            if decision.mode == "picker":
                if decision.reason == "no_repos":
                    await _execute_twig_activity(post_twig_no_repos_activity, inputs, channel, thread_ts)
                    return

                await _execute_twig_activity(
                    post_twig_repo_picker_activity,
                    inputs,
                    channel,
                    thread_ts,
                    slack_user_id,
                    event,
                    workflow.info().workflow_id,
                )
                try:
                    await workflow.wait_condition(
                        lambda: self._selected_repo is not None,
                        timeout=timedelta(minutes=TWIG_SLACK_PICKER_TIMEOUT_MINUTES),
                    )
                except TimeoutError:
                    await _execute_twig_activity(post_twig_picker_timeout_activity, inputs, channel, thread_ts)
                    return

                if not self._selected_repo:
                    return

                await _execute_twig_activity(
                    create_twig_task_for_repo_activity,
                    inputs,
                    channel,
                    thread_ts,
                    slack_user_id,
                    user_id,
                    event,
                    thread_messages,
                    self._selected_repo,
                )
                return

            repository = decision.repository
            if not repository:
                return

            await _execute_twig_activity(
                create_twig_task_for_repo_activity,
                inputs,
                channel,
                thread_ts,
                slack_user_id,
                user_id,
                event,
                thread_messages,
                repository,
            )
        except Exception:
            await _execute_twig_activity(
                post_twig_internal_error_activity,
                inputs,
                channel,
                thread_ts,
            )


async def _execute_twig_activity(activity_fn: Any, *args: Any) -> Any:
    return await workflow.execute_activity(
        activity_fn,
        args=args,
        start_to_close_timeout=timedelta(seconds=TWIG_SLACK_MENTION_TIMEOUT_SECONDS),
        retry_policy=RetryPolicy(maximum_attempts=3),
    )


@activity.defn
def resolve_twig_slack_user_activity(
    inputs: TwigSlackMentionWorkflowInputs,
    channel: str,
    thread_ts: str,
    slack_user_id: str,
) -> int | None:
    from posthog.models.integration import Integration, SlackIntegration

    from products.slack_app.backend.api import resolve_slack_user

    integration = Integration.objects.select_related("team", "team__organization").get(
        id=inputs.integration_id,
        kind="slack-twig",
        integration_id=inputs.slack_team_id,
    )
    slack = SlackIntegration(integration)
    user_context = resolve_slack_user(slack, integration, slack_user_id, channel, thread_ts)
    return user_context.user.id if user_context else None


@activity.defn
def handle_twig_default_repo_command_activity(
    inputs: TwigSlackMentionWorkflowInputs,
    channel: str,
    thread_ts: str,
    slack_user_id: str,
    user_id: int,
) -> bool:
    from posthog.models.integration import Integration, SlackIntegration

    from products.slack_app.backend.api import (
        _clear_user_default_repo,
        _extract_explicit_repo,
        _get_full_repo_names,
        _get_user_default_repo,
        _parse_default_repo_command,
        _post_repo_picker_message,
        _set_user_default_repo,
    )

    integration = Integration.objects.select_related("team", "team__organization").get(
        id=inputs.integration_id,
        kind="slack-twig",
        integration_id=inputs.slack_team_id,
    )
    slack = SlackIntegration(integration)

    default_repo_command = _parse_default_repo_command(inputs.event.get("text", ""))
    if not default_repo_command:
        return False

    if default_repo_command.action == "show":
        default_repo = _get_user_default_repo(integration.team_id, user_id, channel)
        if default_repo:
            slack.client.chat_postMessage(
                channel=channel,
                thread_ts=thread_ts,
                text=f"Your default repository in this channel is `{default_repo}`.",
            )
        else:
            slack.client.chat_postMessage(
                channel=channel,
                thread_ts=thread_ts,
                text=(
                    "You don't have a default repository set. "
                    "Use `@Twig default repo set org/repo`, "
                    "or include `org/repo` directly in a single task request."
                ),
            )
        return True

    if default_repo_command.action == "clear":
        cleared = _clear_user_default_repo(integration.team_id, user_id, channel)
        text = (
            "Cleared your default repository for this channel."
            if cleared
            else "You don't have a default repository set for this channel."
        )
        slack.client.chat_postMessage(channel=channel, thread_ts=thread_ts, text=text)
        return True

    all_repos = _get_full_repo_names(integration)
    command_repo = default_repo_command.repository or ""
    if default_repo_command.action == "set" and not command_repo:
        if not all_repos:
            slack.client.chat_postMessage(
                channel=channel,
                thread_ts=thread_ts,
                text="I couldn't find any connected GitHub repositories for this project.",
            )
            return True

        _post_repo_picker_message(
            slack=slack,
            integration=integration,
            channel=channel,
            thread_ts=thread_ts,
            slack_user_id=slack_user_id,
            event_text=inputs.event.get("text", ""),
            user_message_ts=inputs.event.get("ts"),
            guidance=(
                "Pick a default repository for future generic requests. "
                "You can still override by explicitly writing `org/repo` in a task request."
            ),
            action_id="twig_default_repo_select",
        )
        return True

    if not all_repos:
        slack.client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text="I couldn't find any connected GitHub repositories for this project.",
        )
        return True

    explicit_repo = _extract_explicit_repo(command_repo, all_repos)
    if not explicit_repo:
        slack.client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text="That repository is not connected to this project. Use `@Twig default repo show` to inspect current setting.",
        )
        return True

    _set_user_default_repo(integration.team_id, user_id, channel, explicit_repo)
    slack.client.chat_postMessage(
        channel=channel,
        thread_ts=thread_ts,
        text=f"Set your default repository for this channel to `{explicit_repo}`.",
    )
    return True


@activity.defn
def collect_twig_thread_messages_activity(
    inputs: TwigSlackMentionWorkflowInputs,
    channel: str,
    thread_ts: str,
) -> list[dict[str, str]]:
    from posthog.models.integration import Integration, SlackIntegration

    from products.slack_app.backend.api import _collect_thread_messages

    integration = Integration.objects.select_related("team", "team__organization").get(
        id=inputs.integration_id,
        kind="slack-twig",
        integration_id=inputs.slack_team_id,
    )
    slack = SlackIntegration(integration)
    auth_response = slack.client.auth_test()
    our_bot_id = auth_response.get("bot_id")
    return _collect_thread_messages(slack, integration, channel, thread_ts, our_bot_id)


@activity.defn
def select_twig_repository_activity(
    inputs: TwigSlackMentionWorkflowInputs,
    channel: str,
    event_text: str,
    thread_messages: list[dict[str, str]],
    user_id: int,
) -> TwigSlackRepoDecisionData:
    from posthog.models.integration import Integration
    from posthog.models.user import User

    from products.slack_app.backend.api import _get_full_repo_names, select_repository

    integration = Integration.objects.select_related("team", "team__organization").get(
        id=inputs.integration_id,
        kind="slack-twig",
        integration_id=inputs.slack_team_id,
    )
    all_repos = _get_full_repo_names(integration)
    user = User.objects.get(id=user_id)
    decision = select_repository(
        event_text=event_text,
        thread_messages=thread_messages,
        integration=integration,
        user=user,
        channel=channel,
        all_repos=all_repos,
    )
    return TwigSlackRepoDecisionData(
        mode=decision.mode,
        repository=decision.repository,
        reason=decision.reason,
        repo_count=len(all_repos),
    )


@activity.defn
def post_twig_no_repos_activity(inputs: TwigSlackMentionWorkflowInputs, channel: str, thread_ts: str) -> None:
    from posthog.models.integration import Integration, SlackIntegration

    integration = Integration.objects.select_related("team", "team__organization").get(
        id=inputs.integration_id,
        kind="slack-twig",
        integration_id=inputs.slack_team_id,
    )
    slack = SlackIntegration(integration)
    slack.client.chat_postMessage(
        channel=channel,
        thread_ts=thread_ts,
        text=(
            "I couldn't find any connected GitHub repositories. "
            "Please make sure a GitHub integration is set up in your PostHog project."
        ),
    )


@activity.defn
def post_twig_repo_picker_activity(
    inputs: TwigSlackMentionWorkflowInputs,
    channel: str,
    thread_ts: str,
    slack_user_id: str,
    event: dict[str, Any],
    workflow_id: str,
) -> None:
    from posthog.models.integration import Integration, SlackIntegration

    from products.slack_app.backend.api import _post_repo_picker_message

    integration = Integration.objects.select_related("team", "team__organization").get(
        id=inputs.integration_id,
        kind="slack-twig",
        integration_id=inputs.slack_team_id,
    )
    slack = SlackIntegration(integration)

    _post_repo_picker_message(
        slack=slack,
        integration=integration,
        channel=channel,
        thread_ts=thread_ts,
        slack_user_id=slack_user_id,
        event_text=event.get("text", ""),
        user_message_ts=event.get("ts"),
        guidance=TWIG_SLACK_MENTION_PICKER_GUIDANCE,
        action_id="twig_repo_select",
        workflow_id=workflow_id,
    )


@activity.defn
def create_twig_task_for_repo_activity(
    inputs: TwigSlackMentionWorkflowInputs,
    channel: str,
    thread_ts: str,
    slack_user_id: str,
    user_id: int,
    event: dict[str, Any],
    thread_messages: list[dict[str, str]],
    repository: str,
) -> None:
    from posthog.models.integration import Integration, SlackIntegration

    from products.slack_app.backend.api import _create_task_for_repo

    integration = Integration.objects.select_related("team", "team__organization").get(
        id=inputs.integration_id,
        kind="slack-twig",
        integration_id=inputs.slack_team_id,
    )
    slack = SlackIntegration(integration)
    _create_task_for_repo(
        repository=repository,
        integration=integration,
        slack=slack,
        channel=channel,
        thread_ts=thread_ts,
        user_message_ts=event.get("ts"),
        event_text=event.get("text", ""),
        thread_messages=thread_messages,
        user_id=user_id,
        slack_user_id=slack_user_id,
    )


@activity.defn
def post_twig_picker_timeout_activity(inputs: TwigSlackMentionWorkflowInputs, channel: str, thread_ts: str) -> None:
    from posthog.models.integration import Integration, SlackIntegration

    integration = Integration.objects.select_related("team", "team__organization").get(
        id=inputs.integration_id,
        kind="slack-twig",
        integration_id=inputs.slack_team_id,
    )
    slack = SlackIntegration(integration)
    slack.client.chat_postMessage(
        channel=channel,
        thread_ts=thread_ts,
        text="Repository selection expired. Please mention Twig again to retry.",
    )


@activity.defn
def post_twig_internal_error_activity(inputs: TwigSlackMentionWorkflowInputs, channel: str, thread_ts: str) -> None:
    from posthog.models.integration import Integration, SlackIntegration

    integration = Integration.objects.select_related("team", "team__organization").get(
        id=inputs.integration_id,
        kind="slack-twig",
        integration_id=inputs.slack_team_id,
    )
    slack = SlackIntegration(integration)
    slack.client.chat_postMessage(
        channel=channel,
        thread_ts=thread_ts,
        text="Sorry, I hit an internal error while processing that request. Please try again.",
    )
