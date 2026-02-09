"""Celery tasks for the conversations product."""

import structlog
from celery import shared_task

from posthog.models.integration import Integration
from posthog.models.team import Team

logger = structlog.get_logger(__name__)


@shared_task(ignore_result=True, max_retries=3, default_retry_delay=5)
def post_reply_to_slack(
    ticket_id: str,
    team_id: int,
    content: str,
    author_name: str,
    slack_channel_id: str,
    slack_thread_ts: str,
    integration_id: int,
) -> None:
    """Post a support agent's reply to the corresponding Slack thread."""
    from products.conversations.backend.formatting import content_to_slack_mrkdwn
    from products.conversations.backend.slack import get_slack_client

    try:
        team = Team.objects.get(id=team_id)
    except Team.DoesNotExist:
        logger.warning("slack_reply_team_not_found", team_id=team_id)
        return

    # Get integration if available (fallback for legacy flow)
    integration = None
    try:
        integration = Integration.objects.get(id=integration_id, team_id=team_id, kind="slack")
    except Integration.DoesNotExist:
        pass

    try:
        client = get_slack_client(team, integration)
    except ValueError:
        logger.warning(
            "slack_reply_no_credentials",
            team_id=team_id,
            integration_id=integration_id,
        )
        return

    slack_text = content_to_slack_mrkdwn(content)

    try:
        client.chat_postMessage(
            channel=slack_channel_id,
            thread_ts=slack_thread_ts,
            text=slack_text,
            username=author_name or "Support",
        )
        logger.info(
            "slack_reply_posted",
            ticket_id=ticket_id,
            channel=slack_channel_id,
        )
    except Exception as e:
        logger.exception(
            "slack_reply_post_failed",
            ticket_id=ticket_id,
            error=str(e),
        )
        raise post_reply_to_slack.retry(exc=e)
