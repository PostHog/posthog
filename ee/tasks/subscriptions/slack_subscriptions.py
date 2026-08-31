import uuid
import asyncio
from dataclasses import dataclass, field
from typing import Any

from django.conf import settings
from django.db.models.functions import Length
from django.utils import timezone as tz

import aiohttp
import structlog
from slack_sdk.errors import SlackApiError
from slack_sdk.web.async_client import AsyncWebClient

from posthog.dataclasses import frozen
from posthog.helpers.slack_subscription_explore import build_explore_hint, build_explore_hint_text
from posthog.models.integration import Integration, SlackIntegration
from posthog.storage import object_storage
from posthog.sync import database_sync_to_async
from posthog.utils import absolute_uri

from products.exports.backend.models.exported_asset import ExportedAsset
from products.exports.backend.models.subscription import Subscription, SubscriptionDelivery, SubscriptionResource

from ee.tasks.subscriptions import SLACK_GALLERY_CONFIG_ERRORS, SLACK_USER_CONFIG_ERRORS
from ee.tasks.subscriptions.subscription_utils import (
    ASSET_GENERATION_FAILED_MESSAGE,
    UTM_TAGS_BASE,
    _has_asset_failed,
    subscription_asset_error_message,
)

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

MAX_SLACK_UPLOAD_BYTES = 1 * 1024 * 1024


def _next_delivery_date_display(subscription: Subscription) -> str:
    next_delivery_date = subscription.next_delivery_date
    return next_delivery_date.strftime("%A %B %d, %Y") if next_delivery_date is not None else "an upcoming date"


@dataclass
class SlackMessage:
    channel: str
    blocks: list[dict[str, Any]]
    title: str
    thread_messages: list[dict[str, Any]] = field(default_factory=list)
    # When False, Slack won't auto-unfurl links in the message — set by callers delivering
    # untrusted (e.g. LLM-generated) content to close the server-side link-fetch exfil channel.
    unfurl: bool = True


@frozen
class SlackDeliveryResult:
    main_message_sent: bool
    total_thread_messages: int
    failed_thread_message_indices: list[int]
    omitted_attachment_count: int = 0
    failure_message: str | None = None
    failure_type: str | None = None

    @property
    def is_partial_failure(self) -> bool:
        return self.main_message_sent and (
            len(self.failed_thread_message_indices) > 0 or self.omitted_attachment_count > 0
        )

    @property
    def is_complete_success(self) -> bool:
        return (
            self.main_message_sent
            and len(self.failed_thread_message_indices) == 0
            and self.omitted_attachment_count == 0
        )

    @property
    def is_complete_failure(self) -> bool:
        return not self.main_message_sent


@frozen
class SlackGallery:
    channel: str
    initial_comment: str
    file_uploads: list[dict[str, Any]] = field(default_factory=list)
    omitted_attachment_count: int = 0


def _asset_image_bytes(asset: ExportedAsset) -> bytes | None:
    if asset.content:
        return bytes(asset.content)
    if asset.content_location:
        return object_storage.read_bytes(asset.content_location, missing_ok=True)
    return None


def _asset_image_size(asset: ExportedAsset) -> int | None:
    if "content" not in asset.get_deferred_fields():
        content = asset.__dict__.get("content")
        if content:
            return len(content)
    elif asset.pk is not None:
        content_length = (
            ExportedAsset.objects.filter(pk=asset.pk)
            .annotate(content_length=Length("content"))
            .values_list("content_length", flat=True)
            .get()
        )
        if content_length:
            return content_length
    if asset.content_location:
        metadata = object_storage.head_object(asset.content_location)
        content_length = metadata.get("ContentLength") if metadata else None
        return content_length if isinstance(content_length, int) else None
    return None


def _claim_slack_gallery_delivery(delivery_id: uuid.UUID) -> bool:
    return (
        SubscriptionDelivery.objects.filter(
            id=delivery_id,
            slack_gallery_delivery_started_at__isnull=True,
        ).update(slack_gallery_delivery_started_at=tz.now())
        == 1
    )


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
            f"The next one will be sent on {_next_delivery_date_display(subscription)}"
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
    generation_failed_names: list[str] = []
    attachment_failed_names: list[str] = []
    for asset in assets:
        if asset.exception is not None:
            generation_failed_names.append(_insight_name(asset))
            continue
        content_size = _asset_image_size(asset)
        if content_size is None:
            (attachment_failed_names if asset.content_location else generation_failed_names).append(
                _insight_name(asset)
            )
            continue
        if content_size > MAX_SLACK_UPLOAD_BYTES:
            logger.warning(
                "deliver_slack_gallery.asset_too_large",
                subscription_id=subscription.id,
                filename=asset.filename,
                size_bytes=content_size,
            )
            attachment_failed_names.append(_insight_name(asset))
            continue
        content = _asset_image_bytes(asset)
        if content is None:
            attachment_failed_names.append(_insight_name(asset))
            continue
        # The object may have changed between HEAD and GET. Keep a final bound on
        # what is handed to Slack even though the common path rejects before reading.
        if len(content) > MAX_SLACK_UPLOAD_BYTES:
            logger.warning(
                "deliver_slack_gallery.asset_grew_after_size_check",
                subscription_id=subscription.id,
                filename=asset.filename,
                size_bytes=len(content),
            )
            attachment_failed_names.append(_insight_name(asset))
            continue
        file_uploads.append({"content": content, "filename": asset.filename, "title": _insight_name(asset)})

    if generation_failed_names:
        lines.append("_Could not generate: " + ", ".join(generation_failed_names) + "_")
    if attachment_failed_names:
        lines.append("_Could not attach: " + ", ".join(attachment_failed_names) + "_")
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
        omitted_attachment_count=len(generation_failed_names) + len(attachment_failed_names),
    )


def _block_for_asset(asset: ExportedAsset, resource_url: str) -> dict:
    if _has_asset_failed(asset):
        insight_name = asset.insight.name or asset.insight.derived_name if asset.insight else "Unknown insight"

        # Slack text blocks have a 3000 character limit
        # Reserve space for the insight name, formatting, and support message
        max_error_length = 2000

        if asset.exception:
            exception_text = subscription_asset_error_message(asset)
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
        blocks.append(
            {
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": summary_skipped_over_budget_message(billing_url)}],
            }
        )

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

    return SlackMessage(
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
                omitted_attachment_count=gallery.omitted_attachment_count,
            )

        try:
            await _upload_slack_gallery_with_retry(async_client, subscription, gallery)
        except SlackApiError as error:
            slack_error_code = error.response.get("error", "")
            if slack_error_code in SLACK_USER_CONFIG_ERRORS or slack_error_code in SLACK_GALLERY_CONFIG_ERRORS:
                raise
            logger.error(
                "deliver_slack_gallery.delivery_unconfirmed",
                subscription_id=subscription.id,
                channel=gallery.channel,
                slack_error=slack_error_code,
                exc_info=True,
            )
            return SlackDeliveryResult(
                main_message_sent=False,
                total_thread_messages=0,
                failed_thread_message_indices=[],
                failure_message="Slack could not deliver the gallery. Check the channel before retrying.",
                failure_type="slack_delivery_failed",
            )
        except (TimeoutError, aiohttp.ClientError):
            logger.error(
                "deliver_slack_gallery.delivery_unconfirmed",
                subscription_id=subscription.id,
                channel=gallery.channel,
                exc_info=True,
            )
            return SlackDeliveryResult(
                main_message_sent=False,
                total_thread_messages=0,
                failed_thread_message_indices=[],
                failure_message="Slack could not confirm whether the gallery was delivered. Check the channel before retrying.",
                failure_type="slack_delivery_unconfirmed",
            )

    logger.info(
        "deliver_slack_gallery.uploaded",
        subscription_id=subscription.id,
        file_count=len(gallery.file_uploads),
    )
    return SlackDeliveryResult(
        main_message_sent=True,
        total_thread_messages=0,
        failed_thread_message_indices=[],
        omitted_attachment_count=gallery.omitted_attachment_count,
    )


async def _upload_slack_gallery_with_retry(
    async_client: AsyncWebClient,
    subscription: Subscription,
    gallery: SlackGallery,
    max_retries: int = 3,
) -> None:
    for attempt in range(max_retries):
        try:
            await async_client.files_upload_v2(
                channel=gallery.channel,
                initial_comment=gallery.initial_comment,
                file_uploads=gallery.file_uploads,
            )
            return
        except SlackApiError as error:
            slack_error_code = error.response.get("error", "")
            is_retryable_pre_upload_error = (
                slack_error_code in _RETRYABLE_SLACK_ERRORS
                and error.response.api_url.endswith("/files.getUploadURLExternal")
            )
            if not is_retryable_pre_upload_error or attempt >= max_retries - 1:
                raise
            logger.warning(
                "deliver_slack_gallery.pre_upload_error_retrying",
                subscription_id=subscription.id,
                channel=gallery.channel,
                slack_error=slack_error_code,
                attempt=attempt + 1,
                max_retries=max_retries,
            )
            retry_after = error.response.headers.get("Retry-After") or error.response.headers.get("retry-after")
            if slack_error_code in {"ratelimited", "rate_limited"} and retry_after is not None:
                try:
                    wait_seconds = min(max(float(retry_after), 0.0), 60.0)
                except (TypeError, ValueError):
                    wait_seconds = float(2**attempt)
            else:
                wait_seconds = float(2**attempt)
            await asyncio.sleep(wait_seconds)


async def send_slack_message_with_integration_async(
    integration: Integration,
    subscription: Subscription,
    assets: list[ExportedAsset],
    total_asset_count: int,
    is_new_subscription: bool = False,
    change_summary: str | None = None,
    summary_skipped_over_budget: bool = False,
    delivery_id: uuid.UUID | None = None,
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
        if delivery_id is not None:
            claimed = await database_sync_to_async(
                _claim_slack_gallery_delivery,
                thread_sensitive=False,
            )(delivery_id)
            if not claimed:
                logger.warning(
                    "deliver_slack_gallery.retry_blocked_after_delivery_started",
                    subscription_id=subscription.id,
                    delivery_id=str(delivery_id),
                )
                return SlackDeliveryResult(
                    main_message_sent=False,
                    total_thread_messages=0,
                    failed_thread_message_indices=[],
                    failure_message=(
                        "Slack gallery delivery was already attempted. Check the channel before retrying."
                    ),
                    failure_type="slack_delivery_unconfirmed",
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
