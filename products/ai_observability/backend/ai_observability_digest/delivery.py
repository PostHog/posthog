from __future__ import annotations

import structlog
from markdown_to_mrkdwn import SlackMarkdownConverter

from posthog.models.integration import Integration, SlackIntegration

from products.ai_observability.backend.ai_observability_digest.schema import AIObservabilityOverview

logger = structlog.get_logger(__name__)

# Slack `section` blocks and message text cap out at 3000 characters.
_SLACK_TEXT_LIMIT = 3000
# Slack `header` blocks cap out at 150 characters.
_SLACK_HEADER_LIMIT = 150

_slack_converter = SlackMarkdownConverter()


class SlackDeliveryError(RuntimeError):
    """Raised when the digest cannot be delivered to Slack."""


def _section_mrkdwn(title: str, body: str) -> str:
    return f"*{title}*\n{_slack_converter.convert(body)}"[:_SLACK_TEXT_LIMIT]


def deliver_overview_to_slack(
    *,
    team_id: int,
    integration_id: int | str | None,
    channel: str,
    overview: AIObservabilityOverview,
) -> str:
    """Post the overview to a Slack channel via the team's connected Slack integration.

    Main message = headline (header) + summary + first section. Remaining sections are
    posted as thread replies. Returns the Slack message timestamp (`ts`).
    """
    if not integration_id or not channel:
        raise SlackDeliveryError(f"Missing Slack integration or channel for team {team_id}")

    # Scoped by team_id so a config can't deliver through another team's integration.
    try:
        integration = Integration.objects.get(id=integration_id, team_id=team_id, kind="slack")
    except Integration.DoesNotExist as e:
        raise SlackDeliveryError(
            f"No Slack integration {integration_id} for team {team_id} (deleted or wrong kind)"
        ) from e
    client = SlackIntegration(integration).client

    header_text = overview.headline[:_SLACK_HEADER_LIMIT]
    blocks: list[dict] = [
        {"type": "header", "text": {"type": "plain_text", "text": header_text}},
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": _slack_converter.convert(overview.summary)[:_SLACK_TEXT_LIMIT]},
        },
    ]
    if overview.sections:
        blocks.append({"type": "divider"})
        first = overview.sections[0]
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": _section_mrkdwn(first.title, first.body)}})

    result = client.chat_postMessage(channel=channel, blocks=blocks, text=header_text)
    thread_ts = result.get("ts")

    if thread_ts and len(overview.sections) > 1:
        for section in overview.sections[1:]:
            client.chat_postMessage(
                channel=channel,
                thread_ts=thread_ts,
                text=_section_mrkdwn(section.title, section.body),
            )

    logger.info(
        "ai_observability_digest_delivered",
        team_id=team_id,
        channel=channel,
        section_count=len(overview.sections),
        ts=thread_ts,
    )
    return thread_ts or ""
