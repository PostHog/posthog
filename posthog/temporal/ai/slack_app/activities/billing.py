import structlog
from temporalio import activity

from posthog.temporal.ai.slack_app.helpers import block_if_team_over_quota
from posthog.temporal.ai.slack_app.types import PostHogCodeSlackMentionWorkflowInputs
from posthog.temporal.common.utils import close_db_connections

logger = structlog.get_logger(__name__)


@activity.defn
@close_db_connections
def enforce_posthog_code_billing_quota_activity(
    inputs: PostHogCodeSlackMentionWorkflowInputs,
    channel: str,
    thread_ts: str,
    slack_user_id: str,
) -> bool:
    """Block the workflow when the team has exhausted its AI-credits quota.

    Returns True when the team is over quota and the workflow must stop. Called
    as the first activity in the mention workflow so the bot never proceeds to
    Slack roundtrips, thread fetches, or billable LLM calls (the classifier,
    notably) for an over-quota team.
    """
    from posthog.models.integration import Integration, SlackIntegration

    integration = Integration.objects.select_related("team").get(
        id=inputs.integration_id,
        kind="slack",
        integration_id=inputs.slack_team_id,
    )
    slack = SlackIntegration(integration)
    # An untagged reply has asked PostHog for nothing yet, because both the classifier
    # and the confirmation prompt run after this gate. The denial goes into the thread
    # where everyone in the channel reads it, so an over-quota team would collect one
    # under every reply people write in a thread PostHog owns, chitchat included. Stop
    # the run without the message and keep the message for a mention or a confirmed
    # reply, which are the turns that asked for work.
    unrequested = inputs.untagged_followup and not inputs.untagged_followup_confirmed
    blocked = block_if_team_over_quota(
        integration=integration,
        slack=slack,
        channel=channel,
        thread_ts=thread_ts,
        slack_user_id=slack_user_id,
        context="task_create",
        post_denial=not unrequested,
    )
    if blocked and unrequested:
        logger.info(
            "slack_app_untagged_followup_dropped_over_quota",
            team_id=integration.team_id,
            channel=channel,
            thread_ts=thread_ts,
        )
    return blocked
