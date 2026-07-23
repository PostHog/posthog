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
    from posthog.models.integration import Integration

    from products.slack_app.backend.providers import ConversationRef, SlackChatProvider

    integration = Integration.objects.select_related("team", "team__organization").get(
        id=inputs.integration_id,
        kind="slack",
        integration_id=inputs.slack_team_id,
    )
    # Uncached: the snapshot feeds the persisted task description (the foundational
    # `<slack_thread_context>` block the agent reads forever); a 10-second-stale read
    # would silently bake missing messages into permanent state.
    provider = SlackChatProvider(integration)
    return provider.collect_thread_messages(ConversationRef(channel_id=channel, thread_id=thread_ts))
