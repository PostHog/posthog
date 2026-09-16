import asyncio
from dataclasses import dataclass, field
from typing import Any

from django.conf import settings

import aiohttp
import structlog
from slack_sdk.errors import SlackApiError

from posthog.dataclasses import frozen
from posthog.helpers.slack_subscription_explore import build_explore_hint, build_explore_hint_text
from posthog.models.integration import Integration, SlackIntegration
from posthog.storage import object_storage
from posthog.sync import database_sync_to_async
from posthog.utils import absolute_uri

from products.exports.backend.models.exported_asset import ExportedAsset
from products.exports.backend.models.subscription import Subscription, SubscriptionResource

from ee.tasks.subscriptions.subscription_utils import (
    DEBUG_PLACEHOLDER_IMAGE_URL,
    UTM_TAGS_BASE,
    _has_asset_failed,
    failed_asset_details,
    next_delivery_date_display,
    subscription_support_url,
    summary_skipped_over_budget_message,
)

logger = structlog.get_logger(__name__)


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

MAX_SLACK_UPLOAD_BYTES = 1 * 1024 * 1024


@dataclass
class SlackMessage:
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


@frozen
class SlackGallery:
    channel: str
    initial_comment: str
    file_uploads: list[dict[str, Any]] = field(default_factory=list)


def _asset_image_bytes(asset: ExportedAsset) -> bytes | None:
    if asset.content:
        return bytes(asset.content)
    if asset.content_location:
        return object_storage.read_bytes(asset.content_location, missing_ok=True)
    return None


def _insight_name(asset: ExportedAsset) -> str:
    return ((asset.insight.name or asset.insight.derived_name) if asset.insight else "Insight") or "Insight"


def _subscription_title(
    subscription: Subscription, resource_info: SubscriptionResource, is_new_subscription: bool
) -> str:
    if subscription.title:
        display_name = f"*{subscription.title}* ({resource_info.kind}: {resource_info.name})"
    else:
        display_name = f"the {resource_info.kind} *{resource_info.name}*"

    if is_new_subscription:
        return (
            f"This channel has been subscribed to {display_name} on PostHog! 🎉\n"
            f"This subscription is {subscription.summary}. "
            f"The next one will be sent on {next_delivery_date_display(subscription)}"
        )
    return f"Your subscription to {display_name} is ready! 🎉"


def _ai_summary_text(change_summary: str) -> str:
    summary_text = f"*AI summary:*\n{change_summary}"
    return summary_text[:2997] + "..." if len(summary_text) > 3000 else summary_text


def _overflow_text(shown_count: int, total_asset_count: int, resource_url: str, utm_tags: str) -> str:
    return (
        f"Showing {shown_count} of {total_asset_count} Insights. <{resource_url}?{utm_tags}|View the rest in PostHog>"
    )


def _prepare_slack_gallery(
    subscription: Subscription,
    assets: list[ExportedAsset],
    total_asset_count: int,
    is_new_subscription: bool = False,
    change_summary: str | None = None,
    summary_skipped_over_budget: bool = False,
    integration: Integration | None = None,
) -> SlackGallery:
    utm_tags = f"{UTM_TAGS_BASE}&utm_medium=slack"
    resource_info = subscription.resource_info
    if not resource_info:
        raise NotImplementedError("This type of subscription resource is not supported")

    lines = [_subscription_title(subscription, resource_info, is_new_subscription)]
    if change_summary:
        lines.append(_ai_summary_text(change_summary))
    elif summary_skipped_over_budget:
        billing_url = f"{absolute_uri('/organization/billing')}?{utm_tags}"
        lines.append(summary_skipped_over_budget_message(billing_url))

    file_uploads: list[dict[str, Any]] = []
    failed_names: list[str] = []
    for asset in assets:
        if _has_asset_failed(asset):
            failed_names.append(_insight_name(asset))
            continue
        content = _asset_image_bytes(asset)
        if content is None:
            failed_names.append(_insight_name(asset))
            continue
        if len(content) > MAX_SLACK_UPLOAD_BYTES:
            logger.warning(
                "deliver_slack_gallery.asset_too_large",
                subscription_id=subscription.id,
                filename=asset.filename,
                size_bytes=len(content),
            )
            failed_names.append(_insight_name(asset))
            continue
        file_uploads.append({"content": content, "filename": asset.filename, "title": _insight_name(asset)})

    if failed_names:
        lines.append("_Could not generate: " + ", ".join(failed_names) + "_")
    if total_asset_count > len(assets):
        lines.append(_overflow_text(len(assets), total_asset_count, resource_info.url, utm_tags))
    lines.append(
        f"<{resource_info.url}?{utm_tags}|View in PostHog> · <{subscription.url}?{utm_tags}|Manage subscription>"
    )

    ai_enabled = bool(integration and integration.team.organization.is_ai_data_processing_approved)
    if explore_hint := build_explore_hint_text(integration, utm_tags=utm_tags, ai_enabled=ai_enabled):
        lines.append(explore_hint)

    return SlackGallery(
        channel=subscription.target_value.split("|")[0],
        initial_comment="\n\n".join(lines),
        file_uploads=file_uploads,
    )


def _block_for_asset(asset: ExportedAsset, resource_url: str) -> dict:
    if _has_asset_failed(asset):
        details = failed_asset_details(asset)
        support_url = subscription_support_url(resource_url)
        error_text = (
            f"*{details.insight_name}*\n"
            f"There was an error generating your asset: {details.error_text}\n"
            f"_If this issue persists, please <{support_url}|contact support>._"
        )

        return {"type": "section", "text": {"type": "mrkdwn", "text": error_text}}

    # Normal image block for successful assets
    image_url = asset.get_subscription_delivery_content_url()
    alt_text = None
    if asset.insight:
        alt_text = asset.insight.name or asset.insight.derived_name

    if settings.DEBUG:
        image_url = DEBUG_PLACEHOLDER_IMAGE_URL

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
) -> SlackMessage:
    """Prepare Slack message content. Pure function with no side effects."""
    utm_tags = f"{UTM_TAGS_BASE}&utm_medium=slack"

    resource_info = subscription.resource_info
    if not resource_info:
        raise NotImplementedError("This type of subscription resource is not supported")

    channel = subscription.target_value.split("|")[0]
    first_asset, *other_assets = assets

    title = _subscription_title(subscription, resource_info, is_new_subscription)

    blocks: list[dict] = [
        {"type": "section", "text": {"type": "mrkdwn", "text": title}},
    ]

    if change_summary:
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": _ai_summary_text(change_summary)}})
    elif summary_skipped_over_budget:
        billing_url = f"{absolute_uri('/organization/billing')}?{utm_tags}"
        notice = summary_skipped_over_budget_message(f"<{billing_url}|Billing settings>")
        blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": f"_{notice}_"}]})

    blocks.append(_block_for_asset(first_asset, resource_url=resource_info.url))

    if other_assets:
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": "_See 🧵 for more Insights_"},
            }
        )

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

    # Prepare additional messages for thread
    thread_messages = []
    for asset in other_assets:
        thread_messages.append({"blocks": [_block_for_asset(asset, resource_url=resource_info.url)]})

    if total_asset_count > len(assets):
        thread_messages.append(
            {
                "blocks": [
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": _overflow_text(len(assets), total_asset_count, resource_info.url, utm_tags),
                        },
                    }
                ]
            }
        )

    # unfurl=False: the AI summary and explore hint carry links Slack would otherwise fetch,
    # burying the chart under preview cards and handing report content to Slack's link fetcher.
    return SlackMessage(
        channel=channel,
        blocks=blocks,
        title=title,
        thread_messages=thread_messages,
        unfurl=False,
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
    message_data: SlackMessage,
) -> SlackDeliveryResult:
    # shared send path: callers build the SlackMessage; retry + partial-failure handling are shared
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
    integration: Integration, subscription: Subscription, gallery: SlackGallery
) -> SlackDeliveryResult:
    slack_integration = SlackIntegration(integration)
    async with aiohttp.ClientSession(trust_env=True) as slack_session:
        async_client = slack_integration.async_client(session=slack_session)
        if not gallery.file_uploads:
            await _send_slack_message_with_retry(
                async_client,
                channel=gallery.channel,
                text=gallery.initial_comment,
                unfurl_links=False,
                unfurl_media=False,
            )
            return SlackDeliveryResult(
                main_message_sent=True,
                total_thread_messages=0,
                failed_thread_message_indices=[],
            )

        for attempt in range(3):
            try:
                await async_client.files_upload_v2(
                    channel=gallery.channel,
                    initial_comment=gallery.initial_comment,
                    file_uploads=gallery.file_uploads,
                )
                break
            except (TimeoutError, SlackApiError) as error:
                if isinstance(error, SlackApiError) and error.response.get("error", "") not in _RETRYABLE_SLACK_ERRORS:
                    raise
                if attempt >= 2:
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
