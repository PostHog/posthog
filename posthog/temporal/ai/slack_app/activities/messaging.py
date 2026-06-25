from typing import Any

import structlog
from temporalio import activity

from posthog.temporal.ai.slack_app.types import PostHogCodeSlackMentionWorkflowInputs
from posthog.temporal.common.utils import close_db_connections

logger = structlog.get_logger(__name__)

POSTHOG_CODE_SLACK_MENTION_PICKER_GUIDANCE = (
    "Please select the repository for this task. "
    "Or click *No repo needed* to continue without one. "
    "Or @mention me again and include the exact repository as `org/repo`. "
    'You can also add routing rules with `@PostHog rules add "description" [org/repo]`.'
)
POSTHOG_CODE_SLACK_RULES_ADD_PICKER_GUIDANCE = "Select the repository for this routing rule."


@activity.defn
@close_db_connections
def post_posthog_code_no_repos_activity(
    inputs: PostHogCodeSlackMentionWorkflowInputs, channel: str, thread_ts: str
) -> None:
    from posthog.models.integration import Integration, SlackIntegration

    integration = Integration.objects.select_related("team", "team__organization").get(
        id=inputs.integration_id,
        kind="slack",
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
@close_db_connections
def post_posthog_code_repo_picker_activity(
    inputs: PostHogCodeSlackMentionWorkflowInputs,
    channel: str,
    thread_ts: str,
    slack_user_id: str,
    event: dict[str, Any],
    workflow_id: str,
    guidance: str,
    allow_no_repo: bool,
    user_id: int | None = None,
) -> None:
    """Post the repository picker block in the Slack thread.

    ``user_id`` is appended last and defaults to ``None`` so a worker draining an
    activity task scheduled by a pre-2026-06 workflow (recorded with 8 positional
    args) still binds: the eight legacy slots align by position and ``user_id``
    falls through to the default. The body short-circuits in that case rather than
    posting a picker with a missing ``mentioning_user_id``, which would break the
    downstream external-select handler. New workflows go through the patched call
    site at the workflow body and pass ``user_id`` as the final positional arg.
    """
    from posthog.models.integration import Integration, SlackIntegration

    if user_id is None:
        logger.warning(
            "posthog_code_picker_legacy_call_skipped",
            integration_id=inputs.integration_id,
            slack_team_id=inputs.slack_team_id,
        )
        return

    from products.slack_app.backend.api import _post_repo_picker_message

    integration = Integration.objects.select_related("team", "team__organization").get(
        id=inputs.integration_id,
        kind="slack",
        integration_id=inputs.slack_team_id,
    )
    slack = SlackIntegration(integration)

    _post_repo_picker_message(
        slack=slack,
        integration=integration,
        channel=channel,
        thread_ts=thread_ts,
        slack_user_id=slack_user_id,
        user_id=user_id,
        event_text=event.get("text", ""),
        user_message_ts=event.get("ts"),
        guidance=guidance,
        action_id="posthog_code_repo_select",
        workflow_id=workflow_id,
        allow_no_repo=allow_no_repo,
    )


@activity.defn
@close_db_connections
def block_posthog_code_task_if_no_personal_github_activity(
    inputs: PostHogCodeSlackMentionWorkflowInputs,
    channel: str,
    thread_ts: str,
    user_id: int,
) -> bool:
    """Gate a repo-bound coding-agent task on the mentioner having a personal GitHub.

    Returns True (and posts an in-thread Slack block with a "Connect GitHub" button)
    when the user has no `UserIntegration` of kind=github; the caller must then skip
    `create_posthog_code_task_for_repo_activity`. Returns False to let the task proceed.

    The team-level GitHub App can still author commits, but PRs would land under the
    PostHog app identity instead of the user's. Rather than degrading silently, hold
    the task and surface the one-click path to the personal integration setup.
    """
    from django.conf import settings

    from posthog.models.integration import Integration, SlackIntegration
    from posthog.models.user_integration import UserIntegration

    has_personal_github = UserIntegration.objects.filter(
        user_id=user_id,
        kind=UserIntegration.IntegrationKind.GITHUB,
    ).exists()
    if has_personal_github:
        return False

    integration = Integration.objects.select_related("team", "team__organization").get(
        id=inputs.integration_id,
        kind="slack",
        integration_id=inputs.slack_team_id,
    )
    slack = SlackIntegration(integration)

    settings_url = f"{settings.SITE_URL}/project/{integration.team_id}/settings/user-personal-integrations"
    text = (
        "I can't start this task yet — you haven't connected your personal GitHub. "
        "Connect it so I can open the pull request as you, then mention me again."
    )
    slack.client.chat_postMessage(
        channel=channel,
        thread_ts=thread_ts,
        text=text,
        blocks=[
            {"type": "section", "text": {"type": "mrkdwn", "text": text}},
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Connect GitHub", "emoji": True},
                        "url": settings_url,
                        "style": "primary",
                    }
                ],
            },
        ],
    )
    logger.info(
        "posthog_code_task_blocked_no_personal_github",
        user_id=user_id,
        team_id=integration.team_id,
        channel=channel,
        thread_ts=thread_ts,
    )
    return True


@activity.defn
@close_db_connections
def post_posthog_code_picker_timeout_activity(
    inputs: PostHogCodeSlackMentionWorkflowInputs, channel: str, thread_ts: str
) -> None:
    from posthog.models.integration import Integration, SlackIntegration

    from products.slack_app.backend.api import _clear_pending_repo_picker
    from products.slack_app.backend.models import SlackThreadTaskMapping

    slack_user_id = inputs.event.get("user")
    if isinstance(slack_user_id, str) and slack_user_id:
        _clear_pending_repo_picker(
            integration_id=inputs.integration_id,
            channel=channel,
            thread_ts=thread_ts,
            slack_user_id=slack_user_id,
        )

    # If another workflow already created a task for this thread (e.g. the user
    # sent a follow-up message instead of using the picker), skip the expired
    # message — the thread is already being handled.
    if SlackThreadTaskMapping.objects.filter(
        integration_id=inputs.integration_id,
        channel=channel,
        thread_ts=thread_ts,
    ).exists():
        return

    integration = Integration.objects.select_related("team", "team__organization").get(
        id=inputs.integration_id,
        kind="slack",
        integration_id=inputs.slack_team_id,
    )
    slack = SlackIntegration(integration)
    slack.client.chat_postMessage(
        channel=channel,
        thread_ts=thread_ts,
        text="Repository selection expired. Please mention PostHog again to retry.",
    )


@activity.defn
@close_db_connections
def post_posthog_code_internal_error_activity(
    inputs: PostHogCodeSlackMentionWorkflowInputs, channel: str, thread_ts: str
) -> None:
    from posthog.models.integration import Integration, SlackIntegration

    from products.slack_app.backend.api import _clear_pending_repo_picker

    slack_user_id = inputs.event.get("user")
    if isinstance(slack_user_id, str) and slack_user_id:
        _clear_pending_repo_picker(
            integration_id=inputs.integration_id,
            channel=channel,
            thread_ts=thread_ts,
            slack_user_id=slack_user_id,
        )

    integration = Integration.objects.select_related("team", "team__organization").get(
        id=inputs.integration_id,
        kind="slack",
        integration_id=inputs.slack_team_id,
    )
    slack = SlackIntegration(integration)
    slack.client.chat_postMessage(
        channel=channel,
        thread_ts=thread_ts,
        text="Sorry, I hit an internal error while processing that request. Please try again.",
    )
