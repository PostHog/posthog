import asyncio
from dataclasses import dataclass, field
from typing import Any

from django.conf import settings

import aiohttp
import structlog
from slack_sdk.errors import SlackApiError

from posthog.helpers.slack_subscription_explore import build_explore_hint
from posthog.models.integration import Integration, SlackIntegration
from posthog.storage import object_storage
from posthog.sync import database_sync_to_async
from posthog.utils import absolute_uri

from products.exports.backend.models.exported_asset import ExportedAsset
from products.exports.backend.models.subscription import Subscription

from ee.tasks.subscriptions.subscription_utils import ASSET_GENERATION_FAILED_MESSAGE, UTM_TAGS_BASE, _has_asset_failed

logger = structlog.get_logger(__name__)


# Shown in place of the AI summary when generation was skipped because the org is
# over its AI credit budget. Wording kept in sync with the email template's notice.
def summary_skipped_over_budget_message(billing_url: str) -> str:
    return (
        "_AI summary skipped — your organization has reached its AI credit usage limit. "
        f"Increase the limit in <{billing_url}|Billing settings> to resume summaries._"
    )


# Slack API error codes that indicate transient server-side issues — safe to retry.
# These are 5xx-equivalents in Slack's string-coded error model. Permanent errors
# (channel_not_found, invalid_auth, etc.) are NOT in this set and should fail fast.
_RETRYABLE_SLACK_ERRORS = frozenset(
    {
        "internal_error",
        "service_unavailable",
        "fatal_error",
        "request_timeout",
        "ratelimited",
        "rate_limited",
    }
)


def _next_delivery_date_display(subscription: Subscription) -> str:
    next_delivery_date = subscription.next_delivery_date
    return next_delivery_date.strftime("%A %B %d, %Y") if next_delivery_date is not None else "an upcoming date"


@dataclass
class SlackMessageData:
    channel: str
    blocks: list[dict[str, Any]]
    title: str
    thread_messages: list[dict[str, Any]] = field(default_factory=list)
    # When False, Slack won't auto-unfurl links in the message — set by callers delivering
    # untrusted (e.g. LLM-generated) content to close the server-side link-fetch exfil channel.
    unfurl: bool = True


@dataclass
class SlackDeliveryResult:
    main_message_sent: bool
    total_thread_messages: int
    failed_thread_message_indices: list[int]

    @property
    def is_partial_failure(self) -> bool:
        return self.main_message_sent and len(self.failed_thread_message_indices) > 0

    @property
    def is_complete_success(self) -> bool:
        return self.main_message_sent and len(self.failed_thread_message_indices) == 0


@dataclass
class SlackGalleryData:
    channel: str
    initial_comment: str
    file_uploads: list[dict[str, Any]] = field(default_factory=list)


def _asset_image_bytes(asset: ExportedAsset) -> bytes | None:
    if asset.content:
        return bytes(asset.content)
    if asset.content_location:
        return object_storage.read_bytes(asset.content_location, missing_ok=True)
    return None


def _prepare_slack_gallery(
    subscription: Subscription,
    assets: list[ExportedAsset],
    total_asset_count: int,
    is_new_subscription: bool = False,
    change_summary: str | None = None,
    summary_skipped_over_budget: bool = False,
    integration: Integration | None = None,
) -> SlackGalleryData:
    utm_tags = f"{UTM_TAGS_BASE}&utm_medium=slack"
    resource_info = subscription.resource_info
    if not resource_info:
        raise NotImplementedError("This type of subscription resource is not supported")
    channel = subscription.target_value.split("|")[0]

    if subscription.title:
        display_name = f"*{subscription.title}* ({resource_info.kind}: {resource_info.name})"
    else:
        display_name = f"the {resource_info.kind} *{resource_info.name}*"

    if is_new_subscription:
        title = (
            f"This channel has been subscribed to {display_name} on PostHog! 🎉\n"
            f"This subscription is {subscription.summary}. "
            f"The next one will be sent on {_next_delivery_date_display(subscription)}"
        )
    else:
        title = f"Your subscription to {display_name} is ready! 🎉"

    lines: list[str] = [title]
    if change_summary:
        summary_text = f"*AI summary:*\n{change_summary}"
        lines.append(summary_text[:2997] + "..." if len(summary_text) > 3000 else summary_text)
    elif summary_skipped_over_budget:
        billing_url = f"{absolute_uri('/organization/billing')}?{utm_tags}"
        lines.append(summary_skipped_over_budget_message(billing_url))

    file_uploads: list[dict[str, Any]] = []
    failed_names: list[str] = []
    for asset in assets:
        if _has_asset_failed(asset):
            name = (asset.insight.name or asset.insight.derived_name) if asset.insight else "Insight"
            failed_names.append(name or "Insight")
            continue
        content = _asset_image_bytes(asset)
        if content is None:
            failed_names.append((asset.insight and asset.insight.name) or "Insight")
            continue
        file_uploads.append(
            {
                "content": content,
                "filename": asset.filename,
                "title": (asset.insight and (asset.insight.name or asset.insight.derived_name)) or "Insight",
            }
        )

    if failed_names:
        lines.append("_Could not generate: " + ", ".join(failed_names) + "_")
    if total_asset_count > len(assets):
        lines.append(
            f"Showing {len(assets)} of {total_asset_count} Insights. "
            f"<{resource_info.url}?{utm_tags}|View the rest in PostHog>"
        )
    lines.append(
        f"<{resource_info.url}?{utm_tags}|View in PostHog> · <{subscription.url}?{utm_tags}|Manage subscription>"
    )

    return SlackGalleryData(channel=channel, initial_comment="\n\n".join(lines), file_uploads=file_uploads)


def _block_for_asset(asset: ExportedAsset, resource_url: str) -> dict:
    if _has_asset_failed(asset):
        insight_name = asset.insight.name or asset.insight.derived_name if asset.insight else "Unknown insight"

        # Slack text blocks have a 3000 character limit
        # Reserve space for the insight name, formatting, and support message
        max_error_length = 2000

        if asset.exception:
            exception_text = str(asset.exception)
            if len(exception_text) > max_error_length:
                exception_text = exception_text[:max_error_length] + "... (truncated)"
        else:
            exception_text = ASSET_GENERATION_FAILED_MESSAGE

        support_url = f"{resource_url}#panel=support:bug:analytics_platform:high:true"
        error_text = (
            f"*{insight_name}*\n"
            f"There was an error generating your asset: {exception_text}\n"
            f"_If this issue persists, please <{support_url}|contact support>._"
        )

        return {"type": "section", "text": {"type": "mrkdwn", "text": error_text}}

    # Normal image block for successful assets
    image_url = asset.get_subscription_delivery_content_url()
    alt_text = None
    if asset.insight:
        alt_text = asset.insight.name or asset.insight.derived_name

    if settings.DEBUG:
        # Locally the real asset URL points at localhost, which Slack's servers can't fetch,
        # so substitute a publicly reachable PostHog-branded placeholder image.
        image_url = "https://posthog.com/icons/icon-512x512.png"

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
    change_summary: str | None = None,
    summary_skipped_over_budget: bool = False,
    integration: Integration | None = None,
) -> SlackMessageData:
    """Prepare Slack message content. Pure function with no side effects."""
    utm_tags = f"{UTM_TAGS_BASE}&utm_medium=slack"

    resource_info = subscription.resource_info
    if not resource_info:
        raise NotImplementedError("This type of subscription resource is not supported")

    channel = subscription.target_value.split("|")[0]

    if subscription.title:
        display_name = f"*{subscription.title}* ({resource_info.kind}: {resource_info.name})"
    else:
        display_name = f"the {resource_info.kind} *{resource_info.name}*"

    if is_new_subscription:
        title = f"This channel has been subscribed to {display_name} on PostHog! 🎉"
        title += (
            f"\nThis subscription is {subscription.summary}. "
            f"The next one will be sent on {_next_delivery_date_display(subscription)}"
        )
    else:
        title = f"Your subscription to {display_name} is ready! 🎉"

    blocks: list[dict] = [
        {"type": "section", "text": {"type": "mrkdwn", "text": title}},
    ]

    if change_summary:
        summary_text = f"*AI summary:*\n{change_summary}"
        if len(summary_text) > 3000:
            summary_text = summary_text[:2997] + "..."
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": summary_text}})
    elif summary_skipped_over_budget:
        billing_url = f"{absolute_uri('/organization/billing')}?{utm_tags}"
        blocks.append(
            {
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": summary_skipped_over_budget_message(billing_url)}],
            }
        )

    overflow_block: dict | None = None
    if total_asset_count > len(assets):
        overflow_block = {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"Showing {len(assets)} of {total_asset_count} Insights. <{resource_info.url}?{utm_tags}|View the rest in PostHog>",
            },
        }

    # Only the first image goes into the main message; the rest are sent as thread replies.
    thread_messages: list[dict] = []
    first_asset, *other_assets = assets
    blocks.append(_block_for_asset(first_asset, resource_url=resource_info.url))
    if other_assets:
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "_See 🧵 for more Insights_"}})
        thread_messages = [{"blocks": [_block_for_asset(a, resource_url=resource_info.url)]} for a in other_assets]
    if overflow_block:
        thread_messages.append({"blocks": [overflow_block]})

    action_elements: list[dict] = [
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
    ]

    blocks.extend(
        [
            {"type": "divider"},
            {"type": "actions", "elements": action_elements},
        ]
    )
    ai_enabled = bool(integration and integration.team.organization.is_ai_data_processing_approved)
    if explore_hint := build_explore_hint(integration, utm_tags=utm_tags, ai_enabled=ai_enabled):
        blocks.append(explore_hint)

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
    message_data = _prepare_slack_message(
        subscription,
        assets,
        total_asset_count,
        is_new_subscription,
        integration=integration,
    )
    slack_integration = SlackIntegration(integration)

    # Send main message
    message_res = slack_integration.client.chat_postMessage(
        channel=message_data.channel,
        blocks=message_data.blocks,
        text=message_data.title,
        unfurl_links=message_data.unfurl,
        unfurl_media=message_data.unfurl,
    )

    thread_ts = message_res.get("ts")
    if thread_ts:
        # Send thread messages
        for thread_msg in message_data.thread_messages:
            slack_integration.client.chat_postMessage(
                channel=message_data.channel,
                thread_ts=thread_ts,
                unfurl_links=message_data.unfurl,
                unfurl_media=message_data.unfurl,
                **thread_msg,
            )


async def _send_slack_message_with_retry(client, max_retries: int = 3, **kwargs):
    for attempt in range(max_retries):
        try:
            return await client.chat_postMessage(**kwargs)
        except (TimeoutError, SlackApiError) as e:
            if isinstance(e, SlackApiError):
                slack_error = e.response.get("error", "")
                if slack_error == "invalid_blocks":
                    log_event = "_send_slack_message_with_retry.invalid_blocks_retrying"
                elif slack_error in _RETRYABLE_SLACK_ERRORS:
                    log_event = "_send_slack_message_with_retry.transient_error_retrying"
                else:
                    raise
            else:
                log_event = "_send_slack_message_with_retry.timeout_retrying"

            if attempt >= max_retries - 1:
                raise

            logger.warning(
                log_event,
                attempt=attempt + 1,
                max_retries=max_retries,
                channel=kwargs.get("channel"),
                is_thread=bool(kwargs.get("thread_ts")),
                exc_info=True,
            )

            wait_time = 2**attempt
            await asyncio.sleep(wait_time)


async def deliver_slack_message_data(
    integration: Integration,
    subscription: Subscription,
    message_data: SlackMessageData,
) -> SlackDeliveryResult:
    # shared send path: callers build the SlackMessageData; retry + partial-failure handling are shared
    slack_integration = SlackIntegration(integration)

    async with aiohttp.ClientSession(trust_env=True) as slack_session:
        async_client = slack_integration.async_client(session=slack_session)

        message_res = await _send_slack_message_with_retry(
            async_client,
            channel=message_data.channel,
            blocks=message_data.blocks,
            text=message_data.title,
            unfurl_links=message_data.unfurl,
            unfurl_media=message_data.unfurl,
        )
        logger.info("deliver_slack_message_data.main_message_sent", subscription_id=subscription.id)

        thread_ts = message_res.get("ts")
        failed_thread_messages = []

        if thread_ts:
            for idx, thread_msg in enumerate(message_data.thread_messages):
                try:
                    await _send_slack_message_with_retry(
                        async_client,
                        channel=message_data.channel,
                        thread_ts=thread_ts,
                        unfurl_links=message_data.unfurl,
                        unfurl_media=message_data.unfurl,
                        **thread_msg,
                    )
                except Exception as e:
                    # Thread message failed, continue with others
                    logger.error(
                        "deliver_slack_message_data.slack_thread_message_failed_after_retries",
                        subscription_id=subscription.id,
                        channel=message_data.channel,
                        thread_index=idx,
                        total_thread_messages=len(message_data.thread_messages),
                        thread_ts=thread_ts,
                        error=str(e),
                        exc_info=True,
                    )
                    failed_thread_messages.append(idx)

    return SlackDeliveryResult(
        main_message_sent=True,
        total_thread_messages=len(message_data.thread_messages),
        failed_thread_message_indices=failed_thread_messages,
    )


async def deliver_slack_gallery(
    integration: Integration, subscription: Subscription, gallery: SlackGalleryData
) -> SlackDeliveryResult:
    slack_integration = SlackIntegration(integration)
    async with aiohttp.ClientSession(trust_env=True) as slack_session:
        async_client = slack_integration.async_client(session=slack_session)
        if not gallery.file_uploads:
            # All assets failed — no files to attach; send the comment as a plain message.
            await _send_slack_message_with_retry(
                async_client,
                channel=gallery.channel,
                text=gallery.initial_comment,
                blocks=[{"type": "section", "text": {"type": "mrkdwn", "text": gallery.initial_comment}}],
                unfurl_links=False,
                unfurl_media=False,
            )
            return SlackDeliveryResult(
                main_message_sent=True, total_thread_messages=0, failed_thread_message_indices=[]
            )
        for attempt in range(3):
            try:
                await async_client.files_upload_v2(
                    channel=gallery.channel,
                    initial_comment=gallery.initial_comment,
                    file_uploads=gallery.file_uploads,
                )
                break
            except SlackApiError as e:
                slack_error = e.response.get("error", "")
                if slack_error not in _RETRYABLE_SLACK_ERRORS or attempt >= 2:
                    raise
                await asyncio.sleep(2**attempt)
    logger.info(
        "deliver_slack_gallery.uploaded",
        subscription_id=subscription.id,
        file_count=len(gallery.file_uploads),
    )
    return SlackDeliveryResult(main_message_sent=True, total_thread_messages=0, failed_thread_message_indices=[])


async def send_slack_message_with_integration_async(
    integration: Integration,
    subscription: Subscription,
    assets: list[ExportedAsset],
    total_asset_count: int,
    is_new_subscription: bool = False,
    change_summary: str | None = None,
    summary_skipped_over_budget: bool = False,
) -> SlackDeliveryResult:
    if subscription.delivery_config.get("post_all_insights_in_main_message"):
        gallery = await database_sync_to_async(_prepare_slack_gallery, thread_sensitive=False)(
            subscription,
            assets,
            total_asset_count,
            is_new_subscription,
            change_summary=change_summary,
            summary_skipped_over_budget=summary_skipped_over_budget,
            integration=integration,
        )
        return await deliver_slack_gallery(integration, subscription, gallery)
    # `_prepare_slack_message` reads lazily-loaded ORM relations (e.g. `integration.team.organization`),
    # which Django forbids on the event loop. Build it in a thread before the async Slack send.
    message_data = await database_sync_to_async(_prepare_slack_message, thread_sensitive=False)(
        subscription,
        assets,
        total_asset_count,
        is_new_subscription,
        change_summary=change_summary,
        summary_skipped_over_budget=summary_skipped_over_budget,
        integration=integration,
    )
    return await deliver_slack_message_data(integration, subscription, message_data)
