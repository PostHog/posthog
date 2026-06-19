import structlog
from temporalio import activity

from posthog.temporal.ai.slack_app.types import (
    PostHogCodeRulesCommandResult,
    PostHogCodeSlackMentionCommandResult,
    PostHogCodeSlackMentionCommandWorkflowInputs,
    PostHogCodeSlackMentionWorkflowInputs,
)
from posthog.temporal.common.utils import close_db_connections

logger = structlog.get_logger(__name__)


@activity.defn
@close_db_connections
def handle_posthog_code_rules_command_activity(
    inputs: PostHogCodeSlackMentionWorkflowInputs,
    channel: str,
    thread_ts: str,
    slack_user_id: str,
    user_id: int,
) -> PostHogCodeRulesCommandResult:
    from posthog.models.integration import Integration, SlackIntegration

    from products.slack_app.backend.api import _parse_rules_command
    from products.slack_app.backend.services.commands import dispatch_rules_command

    command = _parse_rules_command(inputs.event.get("text", ""))
    if not command:
        return PostHogCodeRulesCommandResult(status="not_a_command")
    # Picker flow is unique to this workflow; the command service can't drive a
    # workflow signal, so catch it here before delegating.
    if command.action == "add" and not command.repository:
        return PostHogCodeRulesCommandResult(status="needs_picker", pending_rule_text=command.rule_text)

    integration = Integration.objects.select_related("team", "team__organization").get(
        id=inputs.integration_id,
        kind="slack",
        integration_id=inputs.slack_team_id,
    )
    dispatch_rules_command(
        command,
        SlackIntegration(integration),
        integration,
        channel=channel,
        thread_ts=thread_ts,
        slack_user_id=slack_user_id,
        slack_workspace_id=inputs.slack_team_id,
        user_id=user_id,
    )
    return PostHogCodeRulesCommandResult(status="handled")


@activity.defn
@close_db_connections
def create_posthog_code_routing_rule_activity(
    inputs: PostHogCodeSlackMentionWorkflowInputs,
    channel: str,
    thread_ts: str,
    user_id: int,
    rule_text: str,
    repository: str,
) -> None:
    from posthog.models.integration import Integration, SlackIntegration
    from posthog.models.repo_routing_rule import RepoRoutingRule

    from products.slack_app.backend.api import _extract_explicit_repo, _get_full_repo_names

    integration = Integration.objects.select_related("team", "team__organization").get(
        id=inputs.integration_id,
        kind="slack",
        integration_id=inputs.slack_team_id,
    )
    slack = SlackIntegration(integration)

    all_repos = _get_full_repo_names(integration, user_id=user_id)
    matched_repo = _extract_explicit_repo(repository, all_repos)
    if not matched_repo:
        logger.warning(
            "posthog_code_rules_add_repo_no_longer_connected",
            repo=repository,
            team_id=integration.team_id,
            user_id=user_id,
        )
        slack.client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text=f"Repository `{repository}` is no longer connected to your account.",
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
@close_db_connections
def handle_posthog_code_slack_mention_command_activity(
    inputs: PostHogCodeSlackMentionCommandWorkflowInputs,
    user_id: int,
) -> PostHogCodeSlackMentionCommandResult:
    from posthog.models.integration import SlackIntegration

    from products.slack_app.backend.api import _parse_rules_command
    from products.slack_app.backend.services.commands import dispatch_rules_command, resolve_command_target

    event = inputs.event
    channel = event.get("channel")
    thread_ts = event.get("thread_ts") or event.get("ts")
    slack_user_id = event.get("user")
    if not channel or not thread_ts or not slack_user_id:
        return PostHogCodeSlackMentionCommandResult(status="done")

    command = _parse_rules_command(event.get("text", ""))
    if command is None:
        return PostHogCodeSlackMentionCommandResult(status="done")

    candidates, result = resolve_command_target(
        slack_team_id=inputs.slack_team_id,
        command=command,
        slack_user_id=slack_user_id,
        user_id=user_id,
        channel=channel,
        thread_ts=thread_ts,
    )
    if not candidates:
        return PostHogCodeSlackMentionCommandResult(status="done")
    if result.integration is None:
        # Disambiguate "no access" (empty after access filtering) from
        # "multiple projects available" so users get an actionable hint.
        if not result.candidates:
            text = (
                "You don't have access to any PostHog project connected to this Slack workspace. "
                "Ask an admin to grant you access, then try again."
            )
        else:
            text = (
                "This Slack workspace is connected to multiple PostHog projects. "
                "Use `@PostHog project <id>` to set a default first, then re-run your command."
            )
        SlackIntegration(candidates[0]).client.chat_postEphemeral(
            channel=channel,
            user=slack_user_id,
            thread_ts=thread_ts,
            text=text,
        )
        return PostHogCodeSlackMentionCommandResult(status="done")

    target = result.integration

    # ``rules add`` without an inline repo needs the interactive picker, which
    # only a workflow can drive (it owns the signal). Hand control back so the
    # workflow can post the picker against the resolved target and wait for
    # the user's selection.
    if command.action == "add" and not command.repository:
        return PostHogCodeSlackMentionCommandResult(
            status="needs_picker",
            pending_rule_text=command.rule_text,
            target_integration_id=target.id,
        )

    dispatch_rules_command(
        command,
        SlackIntegration(target),
        target,
        channel=channel,
        thread_ts=thread_ts,
        slack_user_id=slack_user_id,
        slack_workspace_id=inputs.slack_team_id,
        user_id=user_id,
        workspace_candidates=candidates,
    )
    return PostHogCodeSlackMentionCommandResult(status="done")
