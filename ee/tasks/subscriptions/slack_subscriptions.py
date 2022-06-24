from typing import Dict, List

import structlog
from django.conf import settings

from posthog.models.exported_asset import ExportedAsset
from posthog.models.integration import Integration, SlackIntegration
from posthog.models.subscription import Subscription

logger = structlog.get_logger(__name__)

UTM_TAGS_BASE = "utm_source=posthog&utm_campaign=subscription_report"


def _block_for_asset(asset: ExportedAsset) -> Dict:
    image_url = asset.get_public_content_url()
    alt_text = None
    if asset.insight:
        alt_text = asset.insight.name or asset.insight.derived_name

    if settings.DEBUG:
        image_url = "https://source.unsplash.com/random"

    return {"type": "image", "image_url": image_url, "alt_text": alt_text}


def send_slack_subscription_report(
    subscription: Subscription, assets: List[ExportedAsset], total_asset_count: int, is_new_subscription: bool = False
) -> None:
    utm_tags = f"{UTM_TAGS_BASE}&utm_medium=slack"

    resource_info = subscription.resource_info
    if not resource_info:
        raise NotImplementedError("This type of subscription resource is not supported")

    integration = Integration.objects.filter(team=subscription.team, kind="slack").first()

    if not integration:
        # TODO: Write error to subscription...
        logger.error("No Slack integration found for team...")
        return

    slack_integration = SlackIntegration(integration)

    channel = subscription.target_value.split("|")[0]

    first_asset, *other_assets = assets

    if is_new_subscription:
        title = f"This channel has been subscribed to the {resource_info.kind} *{resource_info.name}* on PostHog! 🎉"
        title += f"\nThis subscription is {subscription.summary}. The next one will be sent on {subscription.next_delivery_date.strftime('%A %B %d, %Y')}"
    else:
        title = f"Your subscription to the {resource_info.kind} *{resource_info.name}* is ready! 🎉"

    blocks = []

    blocks.extend([{"type": "section", "text": {"type": "mrkdwn", "text": title}}, _block_for_asset(first_asset)])

    if other_assets:
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "_See 🧵 for more Insights_"}})

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

    message_res = slack_integration.client.chat_postMessage(channel=channel, blocks=blocks, text=title)

    thread_ts = message_res.get("ts")

    if thread_ts:
        for asset in other_assets:
            slack_integration.client.chat_postMessage(
                channel=channel, thread_ts=thread_ts, blocks=[_block_for_asset(asset)]
            )

        if total_asset_count > len(assets):
            slack_integration.client.chat_postMessage(
                channel=channel,
                thread_ts=thread_ts,
                blocks=[
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"Showing {len(assets)} of {total_asset_count} Insights. <{resource_info.url}?{utm_tags}|View the rest in PostHog>",
                        },
                    }
                ],
            )
