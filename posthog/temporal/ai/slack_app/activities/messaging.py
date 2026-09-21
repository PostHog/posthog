from typing import Any

import structlog
from temporalio import activity

from posthog.models.integration import Integration, SlackIntegration
from posthog.temporal.ai.slack_app.helpers import safe_react, swap_reaction
from posthog.temporal.ai.slack_app.types import (
    SLACK_APP_PROCESSING_REACTION,
    SLACK_APP_QUEUED_REACTION,
    PostHogCodeSlackMentionWorkflowInputs,
    SlackAppMessageReactionInput,
    coerce_mention_workflow_inputs,
)
from posthog.temporal.common.utils import close_db_connections

from products.slack_app.backend.services.slack_messages import post_slack_thread_reply

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
    inputs = coerce_mention_workflow_inputs(inputs)
    integration = Integration.objects.select_related("team", "team__organization").get(
        id=inputs.integration_id,
        kind="slack",
        integration_id=inputs.slack_team_id,
    )
    slack = SlackIntegration(integration)
    post_slack_thread_reply(
        slack.client,
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
    user_id: int,
) -> None:
    """Post the repository picker block in the Slack thread."""
    inputs = coerce_mention_workflow_inputs(inputs)

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


def _post_connect_personal_github_prompt(
    slack: "SlackIntegration",
    *,
    channel: str,
    thread_ts: str,
    settings_url: str,
    user_id: int,
    team_id: int,
    reconnect: bool = False,
) -> None:
    """Post the single-button prompt for a task held on an unusable personal GitHub install.

    ``reconnect`` picks the wording: a stale install (expired credentials) gets reconnect
    copy, a missing one gets first-time-setup copy. Both send the user to the same settings
    page, so the reconnect copy still reads correctly if the stale row was already discarded.
    """
    if reconnect:
        text = (
            "I can't start this task. Your personal GitHub connection has expired, so I can't open "
            "the pull request as you. Reconnect it, then mention me again."
        )
        button_text = "Reconnect GitHub"
    else:
        text = (
            "I can't start this task yet. You haven't connected your personal GitHub, so I can't open "
            "the pull request as you. Connect it, then mention me again."
        )
        button_text = "Connect GitHub"
    post_slack_thread_reply(
        slack.client,
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
                        "text": {"type": "plain_text", "text": button_text, "emoji": True},
                        "url": settings_url,
                        "style": "primary",
                    }
                ],
            },
        ],
    )
    logger.info(
        "slack_app_task_blocked_no_personal_github",
        user_id=user_id,
        team_id=team_id,
        channel=channel,
        thread_ts=thread_ts,
        reconnect=reconnect,
    )


@activity.defn
@close_db_connections
def block_posthog_code_task_if_no_personal_github_activity(
    inputs: PostHogCodeSlackMentionWorkflowInputs,
    channel: str,
    thread_ts: str,
    user_id: int,
) -> bool:
    """Gate a repo-bound coding-agent task on the mentioner having a usable personal GitHub.

    Returns True (and posts an in-thread Slack block with a Connect/Reconnect GitHub button)
    when the user has no `UserIntegration` of kind=github or has one whose credentials can't
    mint a token; the caller must then skip `create_posthog_code_task_for_repo_activity`.
    Returns False to let the task proceed.

    Checking usability rather than mere existence keeps a task with an expired install from
    clearing this gate and then failing mid-run at the credential path. A stale install gets
    reconnect wording; a missing one gets first-time-setup wording.

    The team-level GitHub App can still author commits, but PRs would land under the
    PostHog app identity instead of the user's. Rather than degrading silently, hold
    the task and surface the one-click path to the personal integration setup.
    """
    from django.conf import settings

    from posthog.models.user_integration import UserIntegration

    from products.tasks.backend.facade import api as tasks_facade

    inputs = coerce_mention_workflow_inputs(inputs)
    # Usability, not existence: a row with expired credentials would clear an existence
    # check here and then fail mid-run when the credential path can't mint a token.
    if tasks_facade.user_has_usable_personal_github(user_id):
        return False

    integration = Integration.objects.select_related("team", "team__organization").get(
        id=inputs.integration_id,
        kind="slack",
        integration_id=inputs.slack_team_id,
    )
    # A stale row (present but unusable) gets reconnect wording; a missing one gets setup wording.
    has_stale_github = UserIntegration.objects.filter(
        user_id=user_id,
        kind=UserIntegration.IntegrationKind.GITHUB,
    ).exists()
    slack = SlackIntegration(integration)
    settings_url = f"{settings.SITE_URL}/project/{integration.team_id}/settings/user-personal-integrations"
    _post_connect_personal_github_prompt(
        slack,
        channel=channel,
        thread_ts=thread_ts,
        settings_url=settings_url,
        user_id=user_id,
        team_id=integration.team_id,
        reconnect=has_stale_github,
    )
    return True


@activity.defn
@close_db_connections
def post_posthog_code_picker_timeout_activity(
    inputs: PostHogCodeSlackMentionWorkflowInputs, channel: str, thread_ts: str
) -> None:
    from products.slack_app.backend.api import _clear_pending_repo_picker
    from products.slack_app.backend.models import SlackThreadTaskMapping

    inputs = coerce_mention_workflow_inputs(inputs)
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
    post_slack_thread_reply(
        slack.client,
        channel=channel,
        thread_ts=thread_ts,
        text="Repository selection expired. Please mention PostHog again to retry.",
    )


@activity.defn
@close_db_connections
def post_posthog_code_internal_error_activity(
    inputs: PostHogCodeSlackMentionWorkflowInputs, channel: str, thread_ts: str
) -> None:
    from products.slack_app.backend.api import _clear_pending_repo_picker

    inputs = coerce_mention_workflow_inputs(inputs)
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
    post_slack_thread_reply(
        slack.client,
        channel=channel,
        thread_ts=thread_ts,
        text="Sorry, I hit an internal error while processing that request. Please try again.",
    )


@activity.defn
@close_db_connections
def mark_slack_app_message_processing_activity(input: SlackAppMessageReactionInput) -> None:
    """Swap the queued :hourglass: reaction for :eyes: when the conversation
    queue starts processing a message.

    Purely cosmetic UX feedback: never raises, so a Slack hiccup can't stall
    the conversation queue behind retries of a reaction.
    """
    try:
        integration = Integration.objects.get(
            id=input.integration_id,
            kind="slack",
            integration_id=input.slack_team_id,
        )
        slack = SlackIntegration(integration)
        swap_reaction(
            slack.client, input.channel, input.message_ts, SLACK_APP_QUEUED_REACTION, SLACK_APP_PROCESSING_REACTION
        )
    except Exception as e:
        logger.warning(
            "slack_app_processing_reaction_failed",
            channel=input.channel,
            message_ts=input.message_ts,
            error=str(e),
        )


@activity.defn
@close_db_connections
def mark_slack_app_message_queued_activity(input: SlackAppMessageReactionInput) -> None:
    """React :hourglass: on a message that entered the conversation queue
    behind another message. Messages processed immediately never get it.

    Best-effort like the processing swap above: never raises.
    """
    try:
        integration = Integration.objects.get(
            id=input.integration_id,
            kind="slack",
            integration_id=input.slack_team_id,
        )
        slack = SlackIntegration(integration)
        safe_react(slack.client, input.channel, input.message_ts, SLACK_APP_QUEUED_REACTION)
    except Exception as e:
        logger.warning(
            "slack_app_queued_reaction_failed",
            channel=input.channel,
            message_ts=input.message_ts,
            error=str(e),
        )


@activity.defn
@close_db_connections
def request_untagged_followup_confirmation_activity(
    inputs: PostHogCodeSlackMentionWorkflowInputs,
    channel: str,
    thread_ts: str,
    slack_user_id: str,
) -> bool:
    """Apply the thread creator's `ask` mode to a reply the classifier just passed.

    Returns ``True`` when the reply must not be forwarded: either the prompt is
    now waiting on its author's answer, or the creator switched the thread off
    while this run was in flight. ``False`` lets the workflow carry on.

    Every untagged reply is asked about, the creator's own included — nobody
    tagged the app, which is the ambiguity the mode exists to settle.

    Running here rather than in the webhook handler is the point of the mode:
    the classifier has already judged the reply worth the agent's attention, so
    the prompt only interrupts someone over a message that would otherwise have
    started work.
    """
    from products.slack_app.backend.api import (
        _post_untagged_followup_prompt,  # noqa: PLC0415 — keeps the webhook module off the worker import path
    )
    from products.slack_app.backend.models import SlackThreadTaskMapping, UntaggedFollowupMode  # noqa: PLC0415
    from products.slack_app.backend.services.slack_settings import resolve_untagged_followup_mode  # noqa: PLC0415

    inputs = coerce_mention_workflow_inputs(inputs)
    mapping = (
        SlackThreadTaskMapping.objects.select_related("integration")
        .filter(integration_id=inputs.integration_id, channel=channel, thread_ts=thread_ts)
        .first()
    )
    if mapping is None:
        # The thread lost its mapping mid-run; the forward activity would drop this
        # anyway, and there is nobody left to attribute a prompt to.
        return True

    integration = mapping.integration
    mode = resolve_untagged_followup_mode(integration, mapping.mentioning_slack_user_id)
    if mode == UntaggedFollowupMode.AUTO:
        return False
    if mode == UntaggedFollowupMode.NEVER:
        logger.info(
            "slack_app_untagged_followup_switched_off_mid_run",
            integration_id=integration.id,
            channel=channel,
            thread_ts=thread_ts,
            slack_user_id=slack_user_id,
        )
        return True

    prompted = _post_untagged_followup_prompt(
        SlackIntegration(integration),
        integration,
        inputs.event,
        is_ext_shared_channel=inputs.is_ext_shared_channel,
    )
    if not prompted:
        # Still held back: forwarding a reply we failed to ask about would break the
        # creator's setting. Logged loudly because the replier sees nothing at all —
        # no prompt, no answer — and that is otherwise indistinguishable from the
        # classifier dropping their message.
        logger.warning(
            "slack_app_untagged_followup_prompt_not_delivered",
            integration_id=integration.id,
            channel=channel,
            thread_ts=thread_ts,
            slack_user_id=slack_user_id,
        )
    return True
