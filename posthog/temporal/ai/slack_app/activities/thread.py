from temporalio import activity

from posthog.temporal.ai.slack_app.types import PostHogCodeSlackMentionWorkflowInputs
from posthog.temporal.common.utils import close_db_connections


@activity.defn
@close_db_connections
def collect_posthog_code_thread_messages_activity(
    inputs: PostHogCodeSlackMentionWorkflowInputs,
    channel: str,
    thread_ts: str,
) -> list[dict[str, str]]:
    from posthog.models.integration import Integration, SlackIntegration

    from products.slack_app.backend.services.slack_messages import collect_thread_messages

    integration = Integration.objects.select_related("team", "team__organization").get(
        id=inputs.integration_id,
        kind="slack",
        integration_id=inputs.slack_team_id,
    )
    slack = SlackIntegration(integration)
    auth_response = slack.client.auth_test()
    our_bot_id = auth_response.get("bot_id")
    # Uncached: the snapshot feeds the persisted task description (the foundational
    # `<slack_thread_context>` block the agent reads forever); a 10-second-stale read
    # would silently bake missing messages into permanent state.
    return collect_thread_messages(slack, integration, channel, thread_ts, our_bot_id)
