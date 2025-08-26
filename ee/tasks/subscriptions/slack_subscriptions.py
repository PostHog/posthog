from dataclasses import dataclass, field
from typing import Any

from django.conf import settings

import structlog

from posthog.models.exported_asset import ExportedAsset
from posthog.models.integration import Integration, SlackIntegration
from posthog.models.subscription import Subscription

logger = structlog.get_logger(__name__)

UTM_TAGS_BASE = "utm_source=posthog&utm_campaign=subscription_report"


@dataclass
class SlackMessageData:
    channel: str
    blocks: list[dict[str, Any]]
    title: str
    thread_messages: list[dict[str, Any]] = field(default_factory=list)


def _block_for_asset(asset: ExportedAsset) -> dict:
    image_url = asset.get_public_content_url()
    alt_text = None
    if asset.insight:
        alt_text = asset.insight.name or asset.insight.derived_name

    if settings.DEBUG:
        image_url = "https://source.unsplash.com/random"

    return {"type": "image", "image_url": image_url, "alt_text": alt_text}


def get_slack_integration_for_team(team_id: int) -> Integration | None:
    """Get Slack integration for a team. Returns None if not found."""
    return Integration.objects.filter(team_id=team_id, kind="slack").first()


def send_slack_subscription_report(
    subscription: Subscription,
    assets: list[ExportedAsset],
    total_asset_count: int,
    is_new_subscription: bool = False,
) -> None:
    """Send Slack subscription report."""
    integration = get_slack_integration_for_team(subscription.team_id)

    if not integration:
        # TODO: Write error to subscription...
        logger.error("No Slack integration found for team...")
        return

    send_slack_message_with_integration(integration, subscription, assets, total_asset_count, is_new_subscription)


def _prepare_slack_message(
    subscription: Subscription,
    assets: list[ExportedAsset],
    total_asset_count: int,
    is_new_subscription: bool = False,
) -> SlackMessageData:
    """Prepare Slack message content. Pure function with no side effects."""
    utm_tags = f"{UTM_TAGS_BASE}&utm_medium=slack"

    resource_info = subscription.resource_info
    if not resource_info:
        raise NotImplementedError("This type of subscription resource is not supported")

    channel = subscription.target_value.split("|")[0]
    first_asset, *other_assets = assets

    if is_new_subscription:
        title = f"This channel has been subscribed to the {resource_info.kind} *{resource_info.name}* on PostHog! 🎉"
        title += f"\nThis subscription is {subscription.summary}. The next one will be sent on {subscription.next_delivery_date.strftime('%A %B %d, %Y')}"
    else:
        title = f"Your subscription to the {resource_info.kind} *{resource_info.name}* is ready! 🎉"

    blocks = [
        {"type": "section", "text": {"type": "mrkdwn", "text": title}},
        _block_for_asset(first_asset),
    ]

    if other_assets:
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": "_See 🧵 for more Insights_"},
            }
        )

    blocks.extend(
        [
            {"type": "divider"},
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "View in PostHog"},
                        "url": f"{resource_info.url}?{utm_tags}",
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Manage Subscription"},
                        "url": f"{subscription.url}?{utm_tags}",
                    },
                ],
            },
        ]
    )

    # Prepare additional messages for thread
    thread_messages = []
    for asset in other_assets:
        thread_messages.append({"blocks": [_block_for_asset(asset)]})

    if total_asset_count > len(assets):
        thread_messages.append(
            {
                "blocks": [
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"Showing {len(assets)} of {total_asset_count} Insights. <{resource_info.url}?{utm_tags}|View the rest in PostHog>",
                        },
                    }
                ]
            }
        )

    return SlackMessageData(
        channel=channel,
        blocks=blocks,
        title=title,
        thread_messages=thread_messages,
    )


def send_slack_message_with_integration(
    integration: Integration,
    subscription: Subscription,
    assets: list[ExportedAsset],
    total_asset_count: int,
    is_new_subscription: bool = False,
) -> None:
    """Send Slack message using provided integration (sync version)."""
    message_data = _prepare_slack_message(subscription, assets, total_asset_count, is_new_subscription)
    slack_integration = SlackIntegration(integration)

    # Send main message
    message_res = slack_integration.client.chat_postMessage(
        channel=message_data.channel, blocks=message_data.blocks, text=message_data.title
    )

    thread_ts = message_res.get("ts")
    if thread_ts:
        # Send thread messages
        for thread_msg in message_data.thread_messages:
            slack_integration.client.chat_postMessage(channel=message_data.channel, thread_ts=thread_ts, **thread_msg)


async def send_slack_message_with_integration_async(
    integration: Integration,
    subscription: Subscription,
    assets: list[ExportedAsset],
    total_asset_count: int,
    is_new_subscription: bool = False,
) -> None:
    """Send Slack message using provided integration (async version)."""
    message_data = _prepare_slack_message(subscription, assets, total_asset_count, is_new_subscription)
    slack_integration = SlackIntegration(integration)

    # Send main message
    message_res = await slack_integration.async_client.chat_postMessage(
        channel=message_data.channel, blocks=message_data.blocks, text=message_data.title
    )

    thread_ts = message_res.get("ts")
    if thread_ts:
        # Send thread messages
        for thread_msg in message_data.thread_messages:
            await slack_integration.async_client.chat_postMessage(
                channel=message_data.channel, thread_ts=thread_ts, **thread_msg
            )
