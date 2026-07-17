from temporalio import activity

from posthog.temporal.ai.slack_app.helpers import block_if_team_over_quota
from posthog.temporal.ai.slack_app.types import PostHogCodeSlackMentionWorkflowInputs
from posthog.temporal.common.utils import close_db_connections


@activity.defn
@close_db_connections
def enforce_posthog_code_billing_quota_activity(
    inputs: PostHogCodeSlackMentionWorkflowInputs,
    channel: str,
    thread_ts: str,
    slack_user_id: str,
) -> bool:
    """Block the workflow when the team has exhausted its AI-credits quota.

    Returns True when a denial was posted and the workflow should stop. Called
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
    return block_if_team_over_quota(
        integration=integration,
        slack=slack,
        channel=channel,
        thread_ts=thread_ts,
        slack_user_id=slack_user_id,
        context="task_create",
    )
