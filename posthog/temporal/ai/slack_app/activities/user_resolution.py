from temporalio import activity

from posthog.temporal.ai.slack_app.types import PostHogCodeSlackMentionCommandWorkflowInputs
from posthog.temporal.common.utils import close_db_connections


@activity.defn
@close_db_connections
def resolve_posthog_code_slack_command_user_activity(
    inputs: PostHogCodeSlackMentionCommandWorkflowInputs,
) -> int | None:
    from posthog.models.integration import Integration, SlackIntegration

    from products.slack_app.backend.api import resolve_posthog_user_from_event

    event = inputs.event
    channel = event.get("channel")
    # Empty anchor posts feedback at the channel root — correct for a slash command outside a thread.
    thread_ts = event.get("thread_ts") or event.get("ts") or ""
    slack_user_id = event.get("user")
    if not channel or not slack_user_id or not inputs.integration_ids:
        return None

    candidates = list(
        Integration.objects.filter(
            id__in=inputs.integration_ids,
            kind="slack",
            integration_id=inputs.slack_team_id,
        ).select_related("team", "team__organization")
    )
    if not candidates:
        return None

    probe = candidates[0]
    posthog_user = resolve_posthog_user_from_event(
        slack_user_id=slack_user_id,
        probe_integration=probe,
        candidate_integrations=candidates,
    )
    if posthog_user is None:
        SlackIntegration(probe).client.chat_postEphemeral(
            channel=channel,
            user=slack_user_id,
            thread_ts=thread_ts,
            text=(
                "I couldn't find your PostHog account in any organization connected to this Slack "
                "workspace. Ask an admin to invite you, then try again."
            ),
        )
        return None
    return posthog_user.id
