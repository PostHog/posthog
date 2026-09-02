from typing import Any

from django.conf import settings

from posthog.helpers.markdown_safety import strip_external_links_markdown
from posthog.utils import absolute_uri

from products.exports.backend.models.exported_asset import ExportedAsset
from products.exports.backend.models.subscription import Subscription

from ee.tasks.subscriptions.subscription_utils import (
    DEBUG_PLACEHOLDER_IMAGE_URL,
    TRUNCATION_MARKER,
    UTM_TAGS_BASE,
    _has_asset_failed,
    failed_asset_details,
    next_delivery_date_display,
    subscription_support_url,
    summary_skipped_over_budget_message,
)

TEAMS_UTM_TAGS = f"{UTM_TAGS_BASE}&utm_medium=teams"

TEAMS_WEBHOOK_URL_MASKED_ERROR = (
    "The saved webhook URL is hidden, so it cannot be sent back. Leave the field alone to keep it, "
    "or paste the full URL to replace it."
)

TEAMS_WEBHOOK_URL_ERROR = (
    "This does not look like a Microsoft Teams webhook URL. Create one with the Workflows app in the "
    "channel you want reports in, then paste the URL it gives you. Microsoft's setup guide: "
    "https://learn.microsoft.com/en-us/microsoftteams/platform/webhooks-and-connectors/how-to/add-incoming-webhook"
)

# Teams rejects an incoming webhook payload over roughly 28KB. This bounds the UTF-8 bytes of text
# a card carries, which is the unit Teams measures the payload in, and leaves room for the JSON
# envelope, the image URLs and the actions. Counting characters instead would let a card of emoji
# or non-Latin text pass this check and still be rejected on the wire.
TEAMS_CARD_TEXT_BUDGET = 20000


def teams_byte_size(text: str) -> int:
    return len(text.encode("utf-8"))


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


def fit_to_teams_budget(text: str, budget: int) -> str:
    if teams_byte_size(text) <= budget:
        return text
    keep = max(budget - teams_byte_size(TRUNCATION_MARKER), 0)
    # Slicing bytes can land inside a multi-byte character, so drop the partial one on decode.
    return text.encode("utf-8")[:keep].decode("utf-8", errors="ignore") + TRUNCATION_MARKER


def _element_for_asset(asset: ExportedAsset, resource_url: str) -> dict[str, Any]:
    if _has_asset_failed(asset):
        details = failed_asset_details(asset)
        support_url = subscription_support_url(resource_url)
        insight_name = strip_external_links_markdown(details.insight_name)
        error_text = strip_external_links_markdown(details.error_text)
        return teams_text_block(
            f"**{insight_name}**\n\n"
            f"There was an error generating your asset: {error_text}\n\n"
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
    resource_info = subscription.resource_info
    if not resource_info:
        raise NotImplementedError("This type of subscription resource is not supported")

    resource_name = strip_external_links_markdown(resource_info.name)
    if subscription.title:
        subscription_title = strip_external_links_markdown(subscription.title)
        display_name = f"**{subscription_title}** ({resource_info.kind}: {resource_name})"
    else:
        display_name = f"the {resource_info.kind} **{resource_name}**"

    if is_new_subscription:
        title = (
            f"This channel has been subscribed to {display_name} on PostHog! 🎉\n\n"
            f"This subscription is {subscription.summary}. "
            f"The next one will be sent on {next_delivery_date_display(subscription)}"
        )
    else:
        title = f"Your subscription to {display_name} is ready! 🎉"

    body: list[dict[str, Any]] = [teams_text_block(title)]
    remaining = TEAMS_CARD_TEXT_BUDGET - teams_byte_size(title)

    if change_summary:
        # The summary is LLM output over customer data, so it is defanged the same way the AI
        # report is before it reaches a surface that turns a URL into a link.
        summary = fit_to_teams_budget(f"**AI summary**\n\n{strip_external_links_markdown(change_summary)}", remaining)
        body.append(teams_text_block(summary))
        remaining -= teams_byte_size(summary)
    elif summary_skipped_over_budget:
        billing_url = f"{absolute_uri('/organization/billing')}?{TEAMS_UTM_TAGS}"
        link = f"[Billing settings]({billing_url})"
        notice = f"_{summary_skipped_over_budget_message(link)}_"
        body.append(teams_text_block(notice, is_subtle=True))
        remaining -= teams_byte_size(notice)

    shown = 0
    for asset in assets:
        element = _element_for_asset(asset, resource_url=resource_info.url)
        size = teams_byte_size(element.get("text", ""))
        # The first asset always goes in, so a card is never all notice and no content.
        if shown and size > remaining:
            break
        body.append(element)
        remaining -= size
        shown += 1

    if total_asset_count > shown:
        body.append(
            teams_text_block(
                f"Showing {shown} of {total_asset_count} insights. "
                f"[View the rest in PostHog]({resource_info.url}?{TEAMS_UTM_TAGS})",
                is_subtle=True,
            )
        )

    actions = [
        teams_open_url_action("View in PostHog", f"{resource_info.url}?{TEAMS_UTM_TAGS}"),
        teams_open_url_action("Manage subscription", f"{subscription.url}?{TEAMS_UTM_TAGS}"),
    ]
    return teams_card_message(body, actions)
