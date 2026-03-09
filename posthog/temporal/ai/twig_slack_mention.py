import re
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from slack_sdk.errors import SlackApiError
from temporalio import activity, workflow
from temporalio.common import RetryPolicy

from posthog.temporal.common.base import PostHogWorkflow


def _safe_react(client: Any, channel: str, timestamp: str, name: str) -> None:
    try:
        client.reactions_add(channel=channel, timestamp=timestamp, name=name)
    except SlackApiError as e:
        if e.response.get("error") == "already_reacted":
            pass
        else:
            raise


TWIG_SLACK_MENTION_TIMEOUT_SECONDS = 10 * 60
TWIG_SLACK_PICKER_TIMEOUT_MINUTES = 15
TWIG_SLACK_MENTION_PICKER_GUIDANCE = (
    "Please select the repository for this task. "
    "Or @mention me again and include the exact repository as `org/repo`. "
    'You can also add routing rules with `@Twig rules add "description" [org/repo]`.'
)
TWIG_SLACK_RULES_ADD_PICKER_GUIDANCE = "Select the repository for this routing rule."


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


@dataclass
class TwigRulesCommandResult:
    status: str  # "not_a_command" | "handled" | "needs_picker"
    pending_rule_text: str | None = None


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
            followup_handled = await _execute_twig_activity(
                forward_twig_followup_activity,
                inputs,
                channel,
                thread_ts,
                slack_user_id,
                event.get("text", ""),
                event.get("ts"),
            )
            if followup_handled:
                return

            user_id = await _execute_twig_activity(
                resolve_twig_slack_user_activity, inputs, channel, thread_ts, slack_user_id
            )
            if not user_id:
                return

            rules_result = await _execute_twig_activity(
                handle_twig_rules_command_activity,
                inputs,
                channel,
                thread_ts,
                slack_user_id,
                user_id,
            )
            if rules_result.status == "handled":
                return
            if rules_result.status == "needs_picker":
                await _execute_twig_activity(
                    post_twig_repo_picker_activity,
                    inputs,
                    channel,
                    thread_ts,
                    slack_user_id,
                    event,
                    workflow.info().workflow_id,
                    TWIG_SLACK_RULES_ADD_PICKER_GUIDANCE,
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
                    create_twig_routing_rule_activity,
                    inputs,
                    channel,
                    thread_ts,
                    user_id,
                    rules_result.pending_rule_text,
                    self._selected_repo,
                )
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
                event.get("text", ""),
                thread_messages,
                user_id,
                channel,
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
                    TWIG_SLACK_MENTION_PICKER_GUIDANCE,
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
def handle_twig_rules_command_activity(
    inputs: TwigSlackMentionWorkflowInputs,
    channel: str,
    thread_ts: str,
    slack_user_id: str,
    user_id: int,
) -> TwigRulesCommandResult:
    from posthog.models.integration import Integration, SlackIntegration

    from products.slack_app.backend.api import _parse_rules_command

    command = _parse_rules_command(inputs.event.get("text", ""))
    if not command:
        return TwigRulesCommandResult(status="not_a_command")

    integration = Integration.objects.select_related("team", "team__organization").get(
        id=inputs.integration_id,
        kind="slack-twig",
        integration_id=inputs.slack_team_id,
    )
    slack = SlackIntegration(integration)

    if command.action == "help":
        _handle_help(slack, channel, thread_ts)
    elif command.action == "list":
        _handle_rules_list(slack, integration, channel, thread_ts)
    elif command.action == "add":
        if not command.repository:
            return TwigRulesCommandResult(status="needs_picker", pending_rule_text=command.rule_text)
        _handle_rules_add(slack, integration, channel, thread_ts, user_id, command.rule_text or "", command.repository)
    elif command.action == "remove":
        _handle_rules_remove(slack, integration, channel, thread_ts, command.rule_number)
    elif command.action == "default_set":
        _handle_default_repo_set(slack, integration, channel, thread_ts, user_id, command.repository or "")
    elif command.action == "default_show":
        _handle_default_repo_show(slack, integration, channel, thread_ts, user_id)
    elif command.action == "default_clear":
        _handle_default_repo_clear(slack, integration, channel, thread_ts, user_id)

    return TwigRulesCommandResult(status="handled")


def _handle_help(slack: Any, channel: str, thread_ts: str) -> None:
    slack.client.chat_postMessage(
        channel=channel,
        thread_ts=thread_ts,
        text=(
            "*Available commands:*\n\n"
            "`@Twig <task description>` — Create a task for the agent to work on\n"
            "`@Twig rules list` — Show all routing rules\n"
            '`@Twig rules add "description" org/repo` — Add a routing rule\n'
            '`@Twig rules add "description"` — Add a routing rule (pick repo from list)\n'
            "`@Twig rules remove <number>` — Remove a routing rule by number\n"
            "`@Twig default repo set org/repo` — Set your default repository for this channel\n"
            "`@Twig default repo show` — Show your default repository for this channel\n"
            "`@Twig default repo clear` — Clear your default repository for this channel\n"
            "`@Twig help` — Show this message\n\n"
            "You can also reply in an active thread to send follow-up messages to the agent."
        ),
    )


def _handle_rules_list(slack: Any, integration: Any, channel: str, thread_ts: str) -> None:
    from posthog.models.repo_routing_rule import RepoRoutingRule

    rules = list(RepoRoutingRule.objects.filter(team_id=integration.team_id).order_by("priority", "id"))
    if not rules:
        slack.client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text='No routing rules configured. Add one with `@Twig rules add "description" [org/repo]`. Omit the repo to pick from a list.',
        )
        return

    lines = [f"{i + 1}. {r.rule_text} → `{r.repository}`" for i, r in enumerate(rules)]
    slack.client.chat_postMessage(
        channel=channel,
        thread_ts=thread_ts,
        text="*Routing rules:*\n" + "\n".join(lines),
    )


def _handle_rules_add(
    slack: Any,
    integration: Any,
    channel: str,
    thread_ts: str,
    user_id: int,
    rule_text: str,
    repository: str,
) -> None:
    from posthog.models.repo_routing_rule import RepoRoutingRule

    from products.slack_app.backend.api import _extract_explicit_repo, _get_full_repo_names

    all_repos = _get_full_repo_names(integration)
    if not all_repos:
        slack.client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text="No connected GitHub repositories found for this project.",
        )
        return

    matched_repo = _extract_explicit_repo(repository, all_repos)
    if not matched_repo:
        slack.client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text=f"Repository `{repository}` is not connected to this project.",
        )
        return

    current_max = (
        RepoRoutingRule.objects.filter(team_id=integration.team_id)
        .order_by("-priority")
        .values_list("priority", flat=True)
        .first()
    )
    max_priority = (current_max + 1) if current_max is not None else 0
    RepoRoutingRule.objects.create(
        team_id=integration.team_id,
        rule_text=rule_text,
        repository=matched_repo,
        priority=max_priority,
        created_by_id=user_id,
    )
    slack.client.chat_postMessage(
        channel=channel,
        thread_ts=thread_ts,
        text=f"Added rule: {rule_text} → `{matched_repo}`",
    )


def _handle_rules_remove(
    slack: Any,
    integration: Any,
    channel: str,
    thread_ts: str,
    rule_number: int | None,
) -> None:
    from posthog.models.repo_routing_rule import RepoRoutingRule

    if rule_number is None or rule_number < 1:
        slack.client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text="Please provide a valid rule number. Use `@Twig rules list` to see current rules.",
        )
        return

    rules = list(RepoRoutingRule.objects.filter(team_id=integration.team_id).order_by("priority", "id"))
    if rule_number > len(rules):
        slack.client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text=f"Rule #{rule_number} does not exist. There are {len(rules)} rule(s). Use `@Twig rules list` to see them.",
        )
        return

    rule = rules[rule_number - 1]
    rule_text = rule.rule_text
    rule.delete()
    slack.client.chat_postMessage(
        channel=channel,
        thread_ts=thread_ts,
        text=f"Removed rule #{rule_number}: {rule_text}",
    )


def _handle_default_repo_set(
    slack: Any,
    integration: Any,
    channel: str,
    thread_ts: str,
    user_id: int,
    repository: str,
) -> None:
    from posthog.models.user_repo_preference import UserRepoPreference

    from products.slack_app.backend.api import _extract_explicit_repo, _get_full_repo_names

    all_repos = _get_full_repo_names(integration)
    matched_repo = _extract_explicit_repo(repository, all_repos)
    if not matched_repo:
        slack.client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text=f"Repository `{repository}` is not connected to this project.",
        )
        return

    UserRepoPreference.set_default(
        team_id=integration.team_id,
        user_id=user_id,
        scope_type="slack_channel",
        scope_id=channel,
        repository=matched_repo,
    )
    slack.client.chat_postMessage(
        channel=channel,
        thread_ts=thread_ts,
        text=f"Default repository for this channel set to `{matched_repo}`.",
    )


def _handle_default_repo_show(
    slack: Any,
    integration: Any,
    channel: str,
    thread_ts: str,
    user_id: int,
) -> None:
    from posthog.models.user_repo_preference import UserRepoPreference

    default = UserRepoPreference.get_default(
        team_id=integration.team_id,
        user_id=user_id,
        scope_type="slack_channel",
        scope_id=channel,
    )
    if default:
        slack.client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text=f"Your default repository for this channel is `{default}`.",
        )
    else:
        slack.client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text="No default repository set for this channel. Use `@Twig default repo set org/repo` to set one.",
        )


def _handle_default_repo_clear(
    slack: Any,
    integration: Any,
    channel: str,
    thread_ts: str,
    user_id: int,
) -> None:
    from posthog.models.user_repo_preference import UserRepoPreference

    cleared = UserRepoPreference.clear_default(
        team_id=integration.team_id,
        user_id=user_id,
        scope_type="slack_channel",
        scope_id=channel,
    )
    if cleared:
        slack.client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text="Default repository for this channel has been cleared.",
        )
    else:
        slack.client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text="No default repository was set for this channel.",
        )


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
    event_text: str,
    thread_messages: list[dict[str, str]],
    user_id: int | None = None,
    channel: str = "",
) -> TwigSlackRepoDecisionData:
    from posthog.models.integration import Integration

    from products.slack_app.backend.api import _get_full_repo_names, select_repository

    integration = Integration.objects.select_related("team", "team__organization").get(
        id=inputs.integration_id,
        kind="slack-twig",
        integration_id=inputs.slack_team_id,
    )
    all_repos = _get_full_repo_names(integration)
    decision = select_repository(
        event_text=event_text,
        thread_messages=thread_messages,
        integration=integration,
        all_repos=all_repos,
        user_id=user_id,
        channel=channel,
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
    guidance: str,
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
        guidance=guidance,
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
    import structlog

    from posthog.models.integration import Integration, SlackIntegration

    from products.slack_app.backend.models import SlackThreadTaskMapping
    from products.slack_app.backend.slack_thread import SlackThreadContext
    from products.tasks.backend.models import Task
    from products.tasks.backend.temporal.client import execute_task_processing_workflow

    log = structlog.get_logger(__name__)

    integration = Integration.objects.select_related("team", "team__organization").get(
        id=inputs.integration_id,
        kind="slack-twig",
        integration_id=inputs.slack_team_id,
    )
    slack = SlackIntegration(integration)
    user_message_ts = event.get("ts")
    if user_message_ts:
        _safe_react(slack.client, channel, user_message_ts, "seedling")

    user_text = re.sub(r"<@[A-Z0-9]+>", "", event.get("text", "")).strip()
    title = user_text[:255] if user_text else "Task from Slack"
    description = "\n".join(f"{msg['user']}: {msg['text']}" for msg in thread_messages)

    slack_thread_context = SlackThreadContext(
        integration_id=integration.id,
        channel=channel,
        thread_ts=thread_ts,
        user_message_ts=user_message_ts,
        mentioning_slack_user_id=slack_user_id,
    )

    slack_thread_url = None
    try:
        permalink_resp = slack.client.chat_getPermalink(channel=channel, message_ts=thread_ts)
        if permalink_resp.get("ok"):
            slack_thread_url = permalink_resp["permalink"]
    except Exception:
        log.warning("twig_slack_permalink_failed", channel=channel, thread_ts=thread_ts)

    # 1. Create task + run WITHOUT starting the workflow
    try:
        task = Task.create_and_run(
            team=integration.team,
            title=title,
            description=description,
            origin_product=Task.OriginProduct.SLACK,
            user_id=user_id,
            repository=repository,
            slack_thread_context=slack_thread_context,
            slack_thread_url=slack_thread_url,
            start_workflow=False,
            posthog_mcp_scopes="full",
        )
    except Exception as e:
        log.exception(
            "twig_task_creation_failed",
            error=str(e),
            team_id=integration.team_id,
            channel=channel,
            thread_ts=thread_ts,
        )
        try:
            slack.client.chat_postMessage(
                channel=channel,
                thread_ts=thread_ts,
                text="Sorry, I ran into an internal error creating the task. Please try again in a minute.",
            )
        except Exception:
            log.warning("twig_error_notification_failed", channel=channel, thread_ts=thread_ts)
        return

    log.info(
        "twig_task_created",
        team_id=integration.team_id,
        repository=repository,
        channel=channel,
        thread_ts=thread_ts,
    )

    # 2. Create mapping BEFORE starting the workflow to avoid race condition
    # where the agent finishes and tries to relay before the mapping exists
    if task:
        task_run = task.latest_run
        if task_run:
            SlackThreadTaskMapping.objects.update_or_create(
                integration=integration,
                channel=channel,
                thread_ts=thread_ts,
                defaults={
                    "team": integration.team,
                    "slack_workspace_id": inputs.slack_team_id,
                    "task": task,
                    "task_run": task_run,
                    "mentioning_slack_user_id": slack_user_id,
                },
            )

    # 3. Now start the workflow
    if task and task_run:
        execute_task_processing_workflow(
            task_id=str(task.id),
            run_id=str(task_run.id),
            team_id=task.team.id,
            user_id=user_id,
            slack_thread_context=slack_thread_context,
        )


@activity.defn
def create_twig_routing_rule_activity(
    inputs: TwigSlackMentionWorkflowInputs,
    channel: str,
    thread_ts: str,
    user_id: int,
    rule_text: str,
    repository: str,
) -> None:
    import structlog

    from posthog.models.integration import Integration, SlackIntegration
    from posthog.models.repo_routing_rule import RepoRoutingRule

    from products.slack_app.backend.api import _extract_explicit_repo, _get_full_repo_names

    log = structlog.get_logger(__name__)

    integration = Integration.objects.select_related("team", "team__organization").get(
        id=inputs.integration_id,
        kind="slack-twig",
        integration_id=inputs.slack_team_id,
    )
    slack = SlackIntegration(integration)

    all_repos = _get_full_repo_names(integration)
    matched_repo = _extract_explicit_repo(repository, all_repos)
    if not matched_repo:
        log.warning("twig_rules_add_repo_no_longer_connected", repo=repository, team_id=integration.team_id)
        slack.client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text=f"Repository `{repository}` is no longer connected to this project.",
        )
        return

    current_max = (
        RepoRoutingRule.objects.filter(team_id=integration.team_id)
        .order_by("-priority")
        .values_list("priority", flat=True)
        .first()
    )
    max_priority = (current_max + 1) if current_max is not None else 0
    RepoRoutingRule.objects.create(
        team_id=integration.team_id,
        rule_text=rule_text,
        repository=matched_repo,
        priority=max_priority,
        created_by_id=user_id,
    )
    slack.client.chat_postMessage(
        channel=channel,
        thread_ts=thread_ts,
        text=f"Added rule: {rule_text} → `{matched_repo}`",
    )


@activity.defn
def forward_twig_followup_activity(
    inputs: TwigSlackMentionWorkflowInputs,
    channel: str,
    thread_ts: str,
    slack_user_id: str,
    event_text: str,
    user_message_ts: str | None,
) -> bool:
    """Forward a follow-up message to the running agent if a mapping exists.

    Returns True if the message was handled (forwarded or rejected), False if
    no mapping exists and the caller should continue with the normal new-task flow.
    """
    import structlog

    from posthog.models.integration import Integration, SlackIntegration

    from products.slack_app.backend.models import SlackThreadTaskMapping
    from products.tasks.backend.services.agent_command import send_user_message
    from products.tasks.backend.services.connection_token import create_sandbox_connection_token

    log = structlog.get_logger(__name__)

    try:
        mapping = SlackThreadTaskMapping.objects.select_related("task_run", "task__created_by").get(
            integration_id=inputs.integration_id,
            channel=channel,
            thread_ts=thread_ts,
        )
    except SlackThreadTaskMapping.DoesNotExist:
        log.info("twig_followup_not_handled", channel=channel, thread_ts=thread_ts)
        return False

    task_run = mapping.task_run

    integration = Integration.objects.select_related("team", "team__organization").get(
        id=inputs.integration_id,
        kind="slack-twig",
        integration_id=inputs.slack_team_id,
    )
    slack = SlackIntegration(integration)

    if slack_user_id != mapping.mentioning_slack_user_id:
        log.info(
            "twig_followup_unauthorized_actor",
            channel=channel,
            thread_ts=thread_ts,
            expected=mapping.mentioning_slack_user_id,
            actual=slack_user_id,
        )
        slack.client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text="Only the person who started this task can send follow-up messages to the agent.",
        )
        return True

    if task_run.is_terminal:
        return _resume_task_with_new_run(
            mapping,
            task_run,
            slack,
            inputs,
            channel,
            thread_ts,
            slack_user_id,
            event_text,
            user_message_ts,
        )

    sandbox_url = (task_run.state or {}).get("sandbox_url")
    if not sandbox_url:
        log.info("twig_followup_sandbox_not_ready", channel=channel, thread_ts=thread_ts)
        slack.client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text="The agent is still starting up. Give it a moment and try again.",
        )
        return True

    user_text = re.sub(r"<@[A-Z0-9]+>", "", event_text).strip()
    if not user_text:
        return True

    if user_message_ts:
        _safe_react(slack.client, channel, user_message_ts, "eyes")

    auth_token = None
    created_by = mapping.task.created_by
    if created_by and created_by.id:
        distinct_id = created_by.distinct_id or f"user_{created_by.id}"
        auth_token = create_sandbox_connection_token(task_run, user_id=created_by.id, distinct_id=distinct_id)

    result = send_user_message(task_run, user_text, auth_token=auth_token, timeout=90)
    if not result.success and result.retryable and result.status_code != 504:
        result = send_user_message(task_run, user_text, auth_token=auth_token, timeout=90)

    if not result.success:
        log.warning(
            "twig_followup_forwarding_failed",
            channel=channel,
            thread_ts=thread_ts,
            error=result.error,
            status_code=result.status_code,
        )
        if result.retryable and result.status_code == 504:
            timeout_reply_text = _extract_recent_assistant_text_from_logs(task_run)
            if timeout_reply_text:
                _set_followup_done_reaction(slack, channel, user_message_ts, "white_check_mark")
                mention_prefix = f"<@{slack_user_id}> " if slack_user_id else ""
                slack.client.chat_postMessage(
                    channel=channel,
                    thread_ts=thread_ts,
                    text=f"{mention_prefix}{timeout_reply_text}",
                )
                _delete_followup_progress(
                    integration_id=inputs.integration_id,
                    channel=channel,
                    thread_ts=thread_ts,
                    user_message_ts=user_message_ts,
                    mentioning_slack_user_id=mapping.mentioning_slack_user_id,
                )
                return True

            _set_followup_done_reaction(slack, channel, user_message_ts, "x")
            slack.client.chat_postMessage(
                channel=channel,
                thread_ts=thread_ts,
                text=(
                    "Message delivery to the sandbox timed out. "
                    "It may still be processing - check agent logs and retry once if needed."
                ),
            )
            return True

        _set_followup_done_reaction(slack, channel, user_message_ts, "x")
        slack.client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text="I couldn't deliver your message to the agent. The sandbox may have stopped. Please try starting a new task.",
        )
        return True

    _set_followup_done_reaction(slack, channel, user_message_ts, "white_check_mark")

    reply_text = _resolve_followup_reply_text(task_run, getattr(result, "data", None))
    if not reply_text:
        reply_text = "I processed your message but couldn't fetch the reply text. Check logs."

    mention_prefix = f"<@{slack_user_id}> " if slack_user_id else ""
    slack.client.chat_postMessage(
        channel=channel,
        thread_ts=thread_ts,
        text=f"{mention_prefix}{reply_text}",
    )

    _delete_followup_progress(
        integration_id=inputs.integration_id,
        channel=channel,
        thread_ts=thread_ts,
        user_message_ts=user_message_ts,
        mentioning_slack_user_id=mapping.mentioning_slack_user_id,
    )

    log.info("twig_followup_forwarded", channel=channel, thread_ts=thread_ts, task_run_id=str(task_run.id))
    return True


def _resume_task_with_new_run(
    mapping: Any,
    previous_run: Any,
    slack: Any,
    inputs: "TwigSlackMentionWorkflowInputs",
    channel: str,
    thread_ts: str,
    slack_user_id: str,
    event_text: str,
    user_message_ts: str | None,
) -> bool:
    """Create a new run on the same task when a follow-up arrives after the previous run completed."""

    import structlog

    from products.slack_app.backend.slack_thread import SlackThreadContext
    from products.tasks.backend.temporal.client import execute_task_processing_workflow

    log = structlog.get_logger(__name__)

    user_text = re.sub(r"<@[A-Z0-9]+>", "", event_text).strip()
    if not user_text:
        return True

    created_by = mapping.task.created_by
    if not created_by:
        slack.client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text="I can't restart the agent — the original task creator is no longer available.",
        )
        return True

    extra_state: dict[str, Any] = {
        "interaction_origin": "slack",
    }

    previous_state = previous_run.state or {}
    if previous_state.get("slack_thread_url"):
        extra_state["slack_thread_url"] = previous_state["slack_thread_url"]

    previous_pr_url = (previous_run.output or {}).get("pr_url")
    initial_prompt_override = user_text
    if previous_pr_url:
        initial_prompt_override = (
            f"[CONTEXT: This task already has an open pull request: {previous_pr_url}\n"
            f"Check out the existing PR branch with `gh pr checkout {previous_pr_url}`, "
            "make your changes, commit, and push to that branch. "
            "Do NOT create a new branch or PR.]\n\n" + user_text
        )
        extra_state["slack_pr_opened_notified"] = True
        extra_state["slack_notified_pr_url"] = previous_pr_url

    extra_state["initial_prompt_override"] = initial_prompt_override

    new_run = mapping.task.create_run(extra_state=extra_state)

    slack_thread_context = SlackThreadContext(
        integration_id=inputs.integration_id,
        channel=channel,
        thread_ts=thread_ts,
        user_message_ts=user_message_ts,
        mentioning_slack_user_id=slack_user_id,
    )

    try:
        execute_task_processing_workflow(
            task_id=str(mapping.task.id),
            run_id=str(new_run.id),
            team_id=mapping.task.team_id,
            user_id=created_by.id,
            slack_thread_context=slack_thread_context,
        )
    except Exception:
        log.exception(
            "twig_resume_workflow_start_failed",
            channel=channel,
            thread_ts=thread_ts,
            task_id=str(mapping.task.id),
            run_id=str(new_run.id),
        )
        slack.client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text="Sorry, I ran into an internal error restarting the agent. Please try again in a minute.",
        )
        return True

    mapping.task_run = new_run
    mapping.save(update_fields=["task_run", "updated_at"])

    if user_message_ts:
        _safe_react(slack.client, channel, user_message_ts, "eyes")

    slack.client.chat_postMessage(
        channel=channel,
        thread_ts=thread_ts,
        text="Got it — restarting the agent to work on this.",
    )

    log.info(
        "twig_task_resumed",
        channel=channel,
        thread_ts=thread_ts,
        task_id=str(mapping.task.id),
        new_run_id=str(new_run.id),
        previous_run_id=str(previous_run.id),
    )
    return True


def _resolve_followup_reply_text(task_run: Any, command_result_data: Any) -> str | None:
    command_text = _extract_assistant_text_from_command_result(command_result_data)
    if command_text:
        return command_text
    return _extract_recent_assistant_text_from_logs(task_run)


def _delete_followup_progress(
    integration_id: int,
    channel: str,
    thread_ts: str,
    user_message_ts: str | None,
    mentioning_slack_user_id: str | None,
) -> None:
    from products.slack_app.backend.slack_thread import SlackThreadContext, SlackThreadHandler

    try:
        SlackThreadHandler(
            SlackThreadContext(
                integration_id=integration_id,
                channel=channel,
                thread_ts=thread_ts,
                user_message_ts=user_message_ts,
                mentioning_slack_user_id=mentioning_slack_user_id,
            )
        ).delete_progress()
    except Exception:
        pass


def _set_followup_done_reaction(slack: Any, channel: str, user_message_ts: str | None, done_emoji: str) -> None:
    if not user_message_ts:
        return

    for stale_emoji in ("eyes", "seedling"):
        try:
            slack.client.reactions_remove(channel=channel, timestamp=user_message_ts, name=stale_emoji)
        except Exception:
            pass

    _safe_react(slack.client, channel, user_message_ts, done_emoji)


def _extract_assistant_text_from_command_result(command_result_data: Any) -> str | None:
    if not isinstance(command_result_data, dict):
        return None

    result = command_result_data.get("result")
    if isinstance(result, dict):
        direct_text = result.get("assistant_message") or result.get("output_text")
        if isinstance(direct_text, str) and direct_text.strip():
            return direct_text.strip()

        messages = result.get("messages")
        if isinstance(messages, list):
            for message in reversed(messages):
                if not isinstance(message, dict) or message.get("role") != "assistant":
                    continue
                text = _extract_text_from_message_payload(message)
                if text:
                    return text

        if result.get("role") == "assistant":
            return _extract_text_from_message_payload(result)

    return None


def _extract_text_from_message_payload(message: dict[str, Any]) -> str | None:
    content = message.get("content")
    if isinstance(content, str) and content.strip():
        return content.strip()

    if isinstance(content, list):
        text_parts: list[str] = []
        for part in content:
            if not isinstance(part, dict):
                continue
            if part.get("type") == "text" and isinstance(part.get("text"), str):
                text = part["text"].strip()
                if text:
                    text_parts.append(text)
        if text_parts:
            return "\n".join(text_parts)

    text_value = message.get("text")
    if isinstance(text_value, str) and text_value.strip():
        return text_value.strip()

    return None


def _extract_recent_assistant_text_from_logs(task_run: Any) -> str | None:
    from posthog.storage import object_storage

    log_content = object_storage.read(task_run.log_url, missing_ok=True) or ""

    if not log_content.strip():
        return None

    latest_text: str | None = None
    latest_agent_timestamp: datetime | None = None
    latest_user_timestamp: datetime | None = None
    cutoff = datetime.utcnow() - timedelta(minutes=5)

    for line in log_content.strip().split("\n"):
        line = line.strip()
        if not line:
            continue

        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue

        notification = entry.get("notification")
        if not isinstance(notification, dict) or notification.get("method") != "session/update":
            continue

        params = notification.get("params")
        update = params.get("update") if isinstance(params, dict) else None
        if not isinstance(update, dict):
            continue

        timestamp = _parse_iso_datetime(entry.get("timestamp"))
        if timestamp and timestamp < cutoff:
            continue

        session_update = update.get("sessionUpdate")
        if session_update in {"user_message", "user_message_chunk"}:
            if timestamp and (latest_user_timestamp is None or timestamp >= latest_user_timestamp):
                latest_user_timestamp = timestamp
            continue

        if session_update not in {"agent_message", "agent_message_chunk"}:
            continue

        content = update.get("content")
        text: str | None = None
        if isinstance(content, dict) and content.get("type") == "text" and isinstance(content.get("text"), str):
            candidate = content["text"].strip()
            text = candidate or None
        elif isinstance(update.get("message"), str):
            candidate = update["message"].strip()
            text = candidate or None

        if not text:
            continue

        if latest_agent_timestamp is None or (timestamp and timestamp >= latest_agent_timestamp):
            latest_agent_timestamp = timestamp
            latest_text = text

    if not latest_text:
        return None

    if latest_agent_timestamp and latest_user_timestamp and latest_agent_timestamp < latest_user_timestamp:
        return None

    return latest_text


def _parse_iso_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None

    normalized = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None

    if parsed.tzinfo is not None:
        return parsed.replace(tzinfo=None)
    return parsed


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
