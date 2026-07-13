"""Celery task that delivers an announcement to its Slack channels via the SupportHog bot.

Idempotent: only ``pending`` delivery rows are processed, so a retry (or a duplicate
dispatch) never re-posts to a channel that already received the message. Per-channel
failures are isolated to their row and never abort the batch; only genuinely unexpected
errors bubble up to trigger Celery's autoretry.
"""

from __future__ import annotations

import time
from typing import Any

from django.db import models
from django.utils import timezone

import structlog
from celery import shared_task
from slack_sdk.errors import SlackApiError

from posthog.models.scoping import with_team_scope
from posthog.models.team import Team

from products.conversations.backend.slack import get_slack_client
from products.customer_analytics.backend.models import Announcement, AnnouncementDelivery

logger = structlog.get_logger(__name__)

# Bound the courtesy wait we honor on a Slack 429 so a rate-limited channel can't stall the
# worker for long. One inline retry per channel, then the row fails.
RATE_LIMIT_MAX_WAIT_SECONDS = 5


def _recompute_announcement_status(announcement: Announcement) -> None:
    """Roll up per-channel delivery rows into the announcement's aggregate counts + status."""
    counts = AnnouncementDelivery.objects.filter(announcement_id=announcement.id).aggregate(
        sent=models.Count("id", filter=models.Q(status=AnnouncementDelivery.Status.SENT)),
        failed=models.Count("id", filter=models.Q(status=AnnouncementDelivery.Status.FAILED)),
        pending=models.Count("id", filter=models.Q(status=AnnouncementDelivery.Status.PENDING)),
    )
    sent, failed, pending = counts["sent"], counts["failed"], counts["pending"]

    if pending:
        status = Announcement.Status.SENDING
    elif failed and sent:
        status = Announcement.Status.PARTIALLY_FAILED
    elif failed:
        status = Announcement.Status.FAILED
    else:
        status = Announcement.Status.SENT

    announcement.sent_count = sent
    announcement.failed_count = failed
    announcement.status = status
    update_fields = ["sent_count", "failed_count", "status", "updated_at"]
    if not pending and announcement.sent_at is None:
        announcement.sent_at = timezone.now()
        update_fields.append("sent_at")
    announcement.save(update_fields=update_fields)


def _post_to_channel(client: Any, delivery: AnnouncementDelivery, message: str, message_kwargs: dict) -> None:
    """Post one announcement message to one channel, recording the outcome on the row.

    Never raises — a failure on one channel is isolated to its row so the batch continues.
    Honors a single bounded courtesy retry on a Slack 429.
    """
    attempted_rate_limit_retry = False
    while True:
        try:
            response = client.chat_postMessage(channel=delivery.slack_channel_id, text=message, **message_kwargs)
            delivery.status = AnnouncementDelivery.Status.SENT
            delivery.slack_message_ts = str(response.get("ts") or "")
            delivery.sent_at = timezone.now()
            delivery.error = ""
            break
        except SlackApiError as e:
            error_code = (getattr(e, "response", None) or {}).get("error", "unknown")
            if error_code == "rate_limited" and not attempted_rate_limit_retry:
                attempted_rate_limit_retry = True
                retry_after = (getattr(e, "response", None) or {}).get("headers", {}).get("Retry-After")
                try:
                    wait = min(float(retry_after), RATE_LIMIT_MAX_WAIT_SECONDS) if retry_after else 1.0
                except (TypeError, ValueError):
                    wait = 1.0
                time.sleep(wait)
                continue
            delivery.status = AnnouncementDelivery.Status.FAILED
            delivery.error = str(error_code)[:2000]
            break
        except Exception as e:
            delivery.status = AnnouncementDelivery.Status.FAILED
            delivery.error = str(e)[:2000]
            break
    delivery.save(update_fields=["status", "slack_message_ts", "sent_at", "error", "updated_at"])


@shared_task(
    name="customer_analytics.send_announcement",
    ignore_result=True,
    autoretry_for=(Exception,),
    max_retries=3,
    retry_backoff=True,
    retry_jitter=True,
)
@with_team_scope()
def send_announcement(announcement_id: str, team_id: int) -> None:
    announcement = Announcement.objects.filter(id=announcement_id).first()
    if not announcement:
        logger.warning("announcement_not_found", announcement_id=announcement_id, team_id=team_id)
        return

    pending = list(
        AnnouncementDelivery.objects.filter(announcement_id=announcement.id, status=AnnouncementDelivery.Status.PENDING)
    )
    if not pending:
        _recompute_announcement_status(announcement)
        return

    try:
        team = Team.objects.get(id=team_id)
        client = get_slack_client(team)
    except (Team.DoesNotExist, ValueError):
        # Missing credentials won't be fixed by retrying — mark the batch failed and stop.
        logger.warning("announcement_no_slack_credentials", announcement_id=announcement_id, team_id=team_id)
        AnnouncementDelivery.objects.filter(
            announcement_id=announcement.id, status=AnnouncementDelivery.Status.PENDING
        ).update(
            status=AnnouncementDelivery.Status.FAILED,
            error="SupportHog Slack is not connected",
            updated_at=timezone.now(),
        )
        _recompute_announcement_status(announcement)
        return

    if announcement.status == Announcement.Status.PENDING:
        announcement.status = Announcement.Status.SENDING
        announcement.save(update_fields=["status", "updated_at"])

    support_settings = team.conversations_settings or {}
    message_kwargs: dict = {}
    if bot_display_name := support_settings.get("slack_bot_display_name"):
        message_kwargs["username"] = bot_display_name
    if bot_icon_url := support_settings.get("slack_bot_icon_url"):
        message_kwargs["icon_url"] = bot_icon_url

    for delivery in pending:
        _post_to_channel(client, delivery, announcement.message, message_kwargs)

    _recompute_announcement_status(announcement)
    logger.info(
        "announcement_sent",
        announcement_id=announcement_id,
        team_id=team_id,
        sent=announcement.sent_count,
        failed=announcement.failed_count,
    )
