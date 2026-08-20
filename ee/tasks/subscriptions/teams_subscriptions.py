import re
from typing import Any
from urllib.parse import urlparse

from django.conf import settings

from posthog.security.url_validation import has_authority_bypass_chars
from posthog.utils import absolute_uri

from products.exports.backend.models.exported_asset import ExportedAsset
from products.exports.backend.models.subscription import Subscription

from ee.tasks.subscriptions.subscription_utils import (
    ASSET_GENERATION_FAILED_MESSAGE,
    DEBUG_PLACEHOLDER_IMAGE_URL,
    UTM_TAGS_BASE,
    _has_asset_failed,
    next_delivery_date_display,
    subscription_asset_error_message,
)

UTM_TAGS = f"{UTM_TAGS_BASE}&utm_medium=teams"

ADAPTIVE_CARD_CONTENT_TYPE = "application/vnd.microsoft.card.adaptive"
ADAPTIVE_CARD_SCHEMA = "http://adaptivecards.io/schemas/adaptive-card.json"
ADAPTIVE_CARD_VERSION = "1.2"

# Host and path pairs a Microsoft Teams webhook URL may use. Deliberately not shared with
# posthog/cdp/templates/microsoft_teams, whose equivalents live inside a Hog source string and
# leave the dots unescaped, so hosts like `evilpowerautomate.com` satisfy them. Every dot here is
# escaped and the host is anchored at both ends, so only a real subdomain of a Microsoft domain
# matches. Since subscriptions expose no generic webhook target, this set is the only thing
# deciding where a report can be posted.
_TEAMS_WEBHOOK_URL_PATTERNS: tuple[tuple[re.Pattern[str], re.Pattern[str]], ...] = (
    # Azure Logic Apps, which is what the Teams "Workflows" app hands out.
    (re.compile(r"^(?:[a-z0-9-]+\.)+logic\.azure\.com$"), re.compile(r"^/workflows/")),
    # Incoming webhook connector added to a channel.
    (re.compile(r"^(?:[a-z0-9-]+\.)+webhook\.office\.com$"), re.compile(r"^/webhookb2/")),
    (re.compile(r"^(?:[a-z0-9-]+\.)+powerautomate\.com$"), re.compile(r"^/.")),
    (re.compile(r"^(?:[a-z0-9-]+\.)+flow\.microsoft\.com$"), re.compile(r"^/.")),
    (
        re.compile(r"^(?:[a-z0-9-]+\.)+environment\.api\.powerplatform\.com$"),
        re.compile(r"^/powerautomate/automations/direct/"),
    ),
)

TEAMS_WEBHOOK_URL_ERROR = (
    "This does not look like a Microsoft Teams webhook URL. Create one with the Workflows app in the "
    "channel you want reports in, then paste the URL it gives you."
)

# Teams rejects an incoming webhook payload over roughly 28KB. Images are linked rather than
# embedded and MAX_INSIGHTS bounds how many there are, so only the AI report text can approach
# the limit; keep the report well inside it and link out for the rest.
TEAMS_TEXT_BLOCK_LIMIT = 3000
TEAMS_REPORT_CHARACTER_BUDGET = 20000

# Bounds one failed chart's exception text, so a run where several fail cannot push the card
# past the payload limit on its own.
_MAX_ASSET_ERROR_LENGTH = 2000


def is_teams_webhook_url(url: str) -> bool:
    """Scheme and host check only, with no name resolution, so it is safe on the save path.
    The delivery path runs the full SSRF validation, because DNS can change in between."""
    if has_authority_bypass_chars(url):
        return False
    try:
        parsed = urlparse(url)
        port = parsed.port
    except ValueError:
        return False
    if parsed.scheme != "https" or port not in (None, 443):
        return False
    host = (parsed.hostname or "").lower()
    path = parsed.path or ""
    return any(
        host_pattern.match(host) and path_pattern.match(path)
        for host_pattern, path_pattern in _TEAMS_WEBHOOK_URL_PATTERNS
    )


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
                "contentType": ADAPTIVE_CARD_CONTENT_TYPE,
                "contentUrl": None,
                "content": {
                    "$schema": ADAPTIVE_CARD_SCHEMA,
                    "type": "AdaptiveCard",
                    "version": ADAPTIVE_CARD_VERSION,
                    "body": body,
                    "actions": actions,
                },
            }
        ],
    }


def _summary_skipped_over_budget_message(billing_url: str) -> str:
    return (
        "_AI summary skipped. Your organization has reached its AI credit usage limit. "
        f"Increase the limit in [Billing settings]({billing_url}) to resume summaries._"
    )


def _element_for_asset(asset: ExportedAsset, resource_url: str) -> dict[str, Any]:
    if _has_asset_failed(asset):
        insight_name = asset.insight.name or asset.insight.derived_name if asset.insight else "Unknown insight"
        if asset.exception:
            exception_text = subscription_asset_error_message(asset)
            if len(exception_text) > _MAX_ASSET_ERROR_LENGTH:
                exception_text = exception_text[:_MAX_ASSET_ERROR_LENGTH] + "... (truncated)"
        else:
            exception_text = ASSET_GENERATION_FAILED_MESSAGE

        support_url = f"{resource_url}#panel=support:bug:analytics_platform:high:true"
        return teams_text_block(
            f"**{insight_name}**\n\n"
            f"There was an error generating your asset: {exception_text}\n\n"
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
        billing_url = f"{absolute_uri('/organization/billing')}?{UTM_TAGS}"
        body.append(teams_text_block(_summary_skipped_over_budget_message(billing_url), is_subtle=True))

    body.extend(_element_for_asset(asset, resource_url=resource_info.url) for asset in assets)

    if total_asset_count > len(assets):
        body.append(
            teams_text_block(
                f"Showing {len(assets)} of {total_asset_count} insights. "
                f"[View the rest in PostHog]({resource_info.url}?{UTM_TAGS})",
                is_subtle=True,
            )
        )

    actions = [
        teams_open_url_action("View in PostHog", f"{resource_info.url}?{UTM_TAGS}"),
        teams_open_url_action("Manage subscription", f"{subscription.url}?{UTM_TAGS}"),
    ]
    return teams_card_message(body, actions)
