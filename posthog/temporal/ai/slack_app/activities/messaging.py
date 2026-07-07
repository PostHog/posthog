import json
import dataclasses
from typing import TYPE_CHECKING, Any

import structlog
from temporalio import activity

from posthog.temporal.ai.slack_app.types import PostHogCodeSlackMentionWorkflowInputs
from posthog.temporal.common.utils import close_db_connections

if TYPE_CHECKING:
    from posthog.models.integration import SlackIntegration

logger = structlog.get_logger(__name__)

POSTHOG_CODE_SLACK_MENTION_PICKER_GUIDANCE = (
    "Please select the repository for this task. "
    "Or click *No repo needed* to continue without one. "
    "Or @mention me again and include the exact repository as `org/repo`. "
    'You can also add routing rules with `@PostHog rules add "description" [org/repo]`.'
)
POSTHOG_CODE_SLACK_RULES_ADD_PICKER_GUIDANCE = "Select the repository for this routing rule."


def coerce_mention_inputs(inputs: Any) -> PostHogCodeSlackMentionWorkflowInputs:
    """Rebuild the mention-inputs dataclass when Temporal hands it over as a raw dict.

    Temporal reconstructs a dataclass activity argument from its JSON payload only when the
    activity is invoked with as many positional arguments as it declares. An activity called
    with fewer (e.g. a caller that omits a trailing defaulted parameter) receives ``inputs`` as
    a plain dict, so the first attribute access raises ``AttributeError``. Filtering to declared
    fields keeps the reconstruction safe across a rolling deploy that adds or removes a field on
    the dataclass, where an older history's payload can carry keys the current class no longer has.
    """
    if isinstance(inputs, PostHogCodeSlackMentionWorkflowInputs):
        return inputs
    field_names = {field.name for field in dataclasses.fields(PostHogCodeSlackMentionWorkflowInputs)}
    return PostHogCodeSlackMentionWorkflowInputs(**{key: inputs[key] for key in inputs if key in field_names})


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


def _post_connect_personal_github_prompt(
    slack: "SlackIntegration",
    *,
    channel: str,
    thread_ts: str,
    settings_url: str,
    user_id: int,
    team_id: int,
) -> None:
    """Post the single-button "Connect GitHub" prompt for a task held on a missing personal GitHub install."""
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
        "slack_app_task_blocked_no_personal_github",
        user_id=user_id,
        team_id=team_id,
        channel=channel,
        thread_ts=thread_ts,
    )


@activity.defn
@close_db_connections
def block_posthog_code_task_if_no_personal_github_activity(
    inputs: PostHogCodeSlackMentionWorkflowInputs,
    channel: str,
    thread_ts: str,
    user_id: int,
    allow_bot_prs: bool = False,
) -> bool:
    """Gate a repo-bound coding-agent task on the mentioner having a personal GitHub.

    Returns True (and posts an in-thread Slack block with a "Connect GitHub" button)
    when the user has no `UserIntegration` of kind=github; the caller must then skip
    `create_posthog_code_task_for_repo_activity`. Returns False to let the task proceed.

    The team-level GitHub App can still author commits, but PRs would land under the
    PostHog app identity instead of the user's. Rather than degrading silently, hold
    the task and surface the one-click path to the personal integration setup.
    """
    # The workflow invokes this activity without the trailing ``allow_bot_prs`` (relying on its
    # default), so Temporal delivers ``inputs`` as a raw dict rather than the dataclass; rebuild it
    # here instead of making the parameter required, which would break in-flight histories already
    # scheduled with the shorter arg list. See ``coerce_mention_inputs`` for the full rationale.
    inputs = coerce_mention_inputs(inputs)

    from django.conf import settings

    from posthog.models.integration import Integration, SlackIntegration
    from posthog.models.user_integration import UserIntegration

    from products.slack_app.backend.feature_flags import is_slack_app_bot_prs_enabled

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
    if allow_bot_prs:
        team_has_github = Integration.objects.filter(
            team=integration.team, kind=Integration.IntegrationKind.GITHUB
        ).exists()
        if team_has_github and is_slack_app_bot_prs_enabled(integration.team):
            return False

    slack = SlackIntegration(integration)
    settings_url = f"{settings.SITE_URL}/project/{integration.team_id}/settings/user-personal-integrations"
    _post_connect_personal_github_prompt(
        slack,
        channel=channel,
        thread_ts=thread_ts,
        settings_url=settings_url,
        user_id=user_id,
        team_id=integration.team_id,
    )
    return True


@activity.defn
@close_db_connections
def resolve_posthog_code_authorship_activity(
    inputs: PostHogCodeSlackMentionWorkflowInputs,
    channel: str,
    thread_ts: str,
    slack_user_id: str,
    user_id: int,
    workflow_id: str,
    repository: str,
) -> str:
    """Gate PR authorship for a repo-bound task: returns "proceed", "awaiting_confirmation", or "blocked"."""
    from django.conf import settings

    from posthog.models.integration import Integration, SlackIntegration
    from posthog.models.user_integration import UserIntegration

    from products.slack_app.backend.feature_flags import is_slack_app_bot_prs_enabled
    from products.tasks.backend.facade import api as tasks_facade

    if tasks_facade.user_can_author_repository(user_id, repository):
        return "proceed"

    has_personal_github = UserIntegration.objects.filter(
        user_id=user_id,
        kind=UserIntegration.IntegrationKind.GITHUB,
    ).exists()
    integration = Integration.objects.select_related("team", "team__organization").get(
        id=inputs.integration_id,
        kind="slack",
        integration_id=inputs.slack_team_id,
    )
    team = integration.team
    slack = SlackIntegration(integration)
    settings_url = f"{settings.SITE_URL}/project/{integration.team_id}/settings/user-personal-integrations"
    team_has_github = Integration.objects.filter(team=team, kind=Integration.IntegrationKind.GITHUB).exists()

    if is_slack_app_bot_prs_enabled(team) and team_has_github:
        if has_personal_github:
            text = (
                f"Your personal GitHub can't author PRs in `{repository}`, so the PR will be authored by the "
                "PostHog bot.\nTo change this, update your personal integration."
            )
        else:
            text = (
                "You have no personal integration setup yet. The PR will be authored by the PostHog bot.\n"
                "To change this, set up a personal integration."
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
                            "action_id": "posthog_code_continue_as_bot",
                            "text": {"type": "plain_text", "text": "Continue as PostHog", "emoji": True},
                            "value": json.dumps(
                                {
                                    "workflow_id": workflow_id,
                                    "integration_id": integration.id,
                                    "mentioning_slack_user_id": slack_user_id,
                                }
                            ),
                        },
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "Connect GitHub", "emoji": True},
                            "url": settings_url,
                            "style": "primary",
                        },
                    ],
                },
            ],
            metadata={"event_type": "posthog_code_authorship", "event_payload": {"workflow_id": workflow_id}},
        )
        logger.info(
            "slack_app_authorship_confirmation_posted",
            user_id=user_id,
            team_id=integration.team_id,
            channel=channel,
            thread_ts=thread_ts,
        )
        return "awaiting_confirmation"

    if has_personal_github:
        slack.client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text=(
                f"I can't start this task yet — your personal GitHub can't author PRs in `{repository}`. "
                "Update your personal integration, then mention me again."
            ),
        )
        logger.info(
            "slack_app_task_blocked_personal_github_missing_repo",
            user_id=user_id,
            team_id=integration.team_id,
            channel=channel,
            thread_ts=thread_ts,
        )
        return "blocked"

    _post_connect_personal_github_prompt(
        slack,
        channel=channel,
        thread_ts=thread_ts,
        settings_url=settings_url,
        user_id=user_id,
        team_id=integration.team_id,
    )
    return "blocked"


@activity.defn
@close_db_connections
def post_posthog_code_authorship_timeout_activity(
    inputs: PostHogCodeSlackMentionWorkflowInputs, channel: str, thread_ts: str
) -> None:
    from posthog.models.integration import Integration, SlackIntegration

    from products.slack_app.backend.models import SlackThreadTaskMapping

    # Skip the expired message if another workflow already created a task for this thread.
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
        text="I didn't hear back, so I haven't started the task. Mention PostHog again to retry.",
    )


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
