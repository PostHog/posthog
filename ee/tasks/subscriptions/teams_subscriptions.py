from typing import Any

from django.conf import settings

from posthog.utils import absolute_uri

from products.exports.backend.models.exported_asset import ExportedAsset
from products.exports.backend.models.subscription import Subscription

from ee.tasks.subscriptions.subscription_utils import (
    DEBUG_PLACEHOLDER_IMAGE_URL,
    UTM_TAGS_BASE,
    _has_asset_failed,
    failed_asset_details,
    next_delivery_date_display,
    subscription_support_url,
    summary_skipped_over_budget_message,
)

TEAMS_UTM_TAGS = f"{UTM_TAGS_BASE}&utm_medium=teams"

TEAMS_WEBHOOK_URL_ERROR = (
    "This does not look like a Microsoft Teams webhook URL. Create one with the Workflows app in the "
    "channel you want reports in, then paste the URL it gives you."
)

# Teams rejects an incoming webhook payload over roughly 28KB. Images are linked rather than
# embedded and MAX_INSIGHTS bounds how many there are, so only the AI report text can approach
# that limit. The report is kept well inside it and links out for the rest.
TEAMS_TEXT_BLOCK_LIMIT = 3000


def teams_text_block(text: str, *, is_subtle: bool = False) -> dict[str, Any]:
    block: dict[str, Any] = {"type": "TextBlock", "text": text, "wrap": True}
    if is_subtle:
        block["isSubtle"] = True
    return block


def teams_open_url_action(title: str, url: str) -> dict[str, str]:
    return {"type": "Action.OpenUrl", "title": title, "url": url}


def teams_card_message(body: list[dict[str, Any]], actions: list[dict[str, str]]) -> dict[str, Any]:
    return {
        "type": "message",
        "attachments": [
            {
                "contentType": "application/vnd.microsoft.card.adaptive",
                "contentUrl": None,
                "content": {
                    "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                    "type": "AdaptiveCard",
                    "version": "1.2",
                    "body": body,
                    "actions": actions,
                },
            }
        ],
    }


def _element_for_asset(asset: ExportedAsset, resource_url: str) -> dict[str, Any]:
    if _has_asset_failed(asset):
        details = failed_asset_details(asset)
        support_url = subscription_support_url(resource_url)
        return teams_text_block(
            f"**{details.insight_name}**\n\n"
            f"There was an error generating your asset: {details.error_text}\n\n"
            f"_If this issue persists, please [contact support]({support_url})._"
        )

    image_url = DEBUG_PLACEHOLDER_IMAGE_URL if settings.DEBUG else asset.get_subscription_delivery_content_url()
    image: dict[str, Any] = {"type": "Image", "url": image_url, "size": "Stretch"}
    alt_text = (asset.insight.name or asset.insight.derived_name) if asset.insight else None
    if alt_text:
        image["altText"] = alt_text
    return image


def build_teams_subscription_card(
    subscription: Subscription,
    assets: list[ExportedAsset],
    total_asset_count: int,
    *,
    is_new_subscription: bool = False,
    change_summary: str | None = None,
    summary_skipped_over_budget: bool = False,
) -> dict[str, Any]:
    """Adaptive Card for an insight or dashboard subscription. Teams has no threading, so every
    chart is stacked in one card where the Slack path puts the extras in a thread."""
    resource_info = subscription.resource_info
    if not resource_info:
        raise NotImplementedError("This type of subscription resource is not supported")

    if subscription.title:
        display_name = f"**{subscription.title}** ({resource_info.kind}: {resource_info.name})"
    else:
        display_name = f"the {resource_info.kind} **{resource_info.name}**"

    if is_new_subscription:
        title = (
            f"This channel has been subscribed to {display_name} on PostHog! 🎉\n\n"
            f"This subscription is {subscription.summary}. "
            f"The next one will be sent on {next_delivery_date_display(subscription)}"
        )
    else:
        title = f"Your subscription to {display_name} is ready! 🎉"

    body: list[dict[str, Any]] = [teams_text_block(title)]

    if change_summary:
        body.append(teams_text_block(f"**AI summary**\n\n{change_summary}"))
    elif summary_skipped_over_budget:
        billing_url = f"{absolute_uri('/organization/billing')}?{TEAMS_UTM_TAGS}"
        notice = summary_skipped_over_budget_message(f"[Billing settings]({billing_url})")
        body.append(teams_text_block(f"_{notice}_", is_subtle=True))

    body.extend(_element_for_asset(asset, resource_url=resource_info.url) for asset in assets)

    if total_asset_count > len(assets):
        body.append(
            teams_text_block(
                f"Showing {len(assets)} of {total_asset_count} insights. "
                f"[View the rest in PostHog]({resource_info.url}?{TEAMS_UTM_TAGS})",
                is_subtle=True,
            )
        )

    actions = [
        teams_open_url_action("View in PostHog", f"{resource_info.url}?{TEAMS_UTM_TAGS}"),
        teams_open_url_action("Manage subscription", f"{subscription.url}?{TEAMS_UTM_TAGS}"),
    ]
    return teams_card_message(body, actions)
