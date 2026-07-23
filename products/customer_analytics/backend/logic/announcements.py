from __future__ import annotations

from typing import TYPE_CHECKING

from django.db import models, transaction
from django.utils import timezone

import structlog

from products.conversations.backend.facade.api import (
    SupportMessageSendError,
    SupportSlackChannelsUnavailable,
    SupportSlackNotConfigured,
    list_support_bot_channels,
    post_support_message,
)
from products.customer_analytics.backend.constants import (
    DELIVERY_IN_FLIGHT_ERROR,
    DELIVERY_INTERRUPTED_ERROR,
    DELIVERY_RATE_LIMIT_DEFERRED_ERROR,
)
from products.customer_analytics.backend.facade.contracts import AnnouncementChannelView, AnnouncementValidationError
from products.customer_analytics.backend.models import Account, Announcement, AnnouncementDelivery

if TYPE_CHECKING:
    from posthog.models.team import Team
    from posthog.models.user import User

logger = structlog.get_logger(__name__)


class AnnouncementRateLimited(Exception):
    pass


def create_announcement(team: Team, created_by: User, message: str, channel_ids: list[str]) -> Announcement:
    try:
        allowed = {c.id: c for c in list_support_bot_channels(team.pk, members_only=True)}
    except SupportSlackNotConfigured:
        raise AnnouncementValidationError("The SupportHog Slack bot is not connected.")
    except SupportSlackChannelsUnavailable:
        raise AnnouncementValidationError("Could not verify Slack channels right now. Please try again.")

    # Only member channels get a pending row (the only state the send task posts), so a
    # crafted channel ID can never make the bot post to an arbitrary Slack destination;
    # non-member channels are born failed, same as a channel lost between create and send.
    with transaction.atomic():
        announcement = Announcement.objects.create(
            team=team,
            message=message,
            created_by=created_by,
            total_channels=len(channel_ids),
            status=Announcement.Status.PENDING,
        )
        AnnouncementDelivery.objects.bulk_create(
            [
                AnnouncementDelivery(
                    team=team,
                    announcement=announcement,
                    slack_channel_id=cid,
                    slack_channel_name=allowed[cid].name if cid in allowed else "",
                    status=(
                        AnnouncementDelivery.Status.PENDING if cid in allowed else AnnouncementDelivery.Status.FAILED
                    ),
                    error="" if cid in allowed else "not_in_channel",
                )
                for cid in channel_ids
            ]
        )
    return announcement


def list_channels(team_id: int) -> list[AnnouncementChannelView]:
    member_channels = list_support_bot_channels(team_id, members_only=True)
    name_by_channel = _customer_names_by_channel(team_id)
    enriched = [
        AnnouncementChannelView(
            id=c.id,
            name=c.name,
            is_member=c.is_member,
            customer_name=name_by_channel.get(c.id),
        )
        for c in member_channels
    ]
    enriched.sort(key=lambda c: (c.customer_name is None, (c.customer_name or c.name).lower()))
    return enriched


def _customer_names_by_channel(team_id: int) -> dict[str, str]:
    result: dict[str, str] = {}
    rows = Account.objects.for_team(team_id).filter(_properties__has_key="slack_channel_id")
    for channel_id, name in rows.values_list("_properties__slack_channel_id", "name"):
        if channel_id:
            result.setdefault(channel_id, name)
    return result


def send_pending_deliveries(announcement_id: str, team_id: int) -> None:
    announcement = Announcement.objects.for_team(team_id).filter(id=announcement_id).first()
    if not announcement:
        logger.warning("announcement_not_found", announcement_id=announcement_id, team_id=team_id)
        return

    pending = list(
        AnnouncementDelivery.objects.filter(announcement_id=announcement.id, status=AnnouncementDelivery.Status.PENDING)
    )
    if not pending:
        _recompute_announcement_status(announcement)
        return

    # A pending row still claimed in-flight means a previous run crashed mid-post; the message
    # may already be in Slack, so never re-post it.
    interrupted_ids = {delivery.id for delivery in pending if delivery.error == DELIVERY_IN_FLIGHT_ERROR}
    if interrupted_ids:
        AnnouncementDelivery.objects.for_team(team_id).filter(id__in=interrupted_ids).update(
            status=AnnouncementDelivery.Status.FAILED,
            error=DELIVERY_INTERRUPTED_ERROR,
            updated_at=timezone.now(),
        )
        pending = [delivery for delivery in pending if delivery.id not in interrupted_ids]

    if announcement.status == Announcement.Status.PENDING:
        announcement.status = Announcement.Status.SENDING
        announcement.save(update_fields=["status", "updated_at"])

    deferred = 0
    for delivery in pending:
        try:
            if not _deliver_to_channel(team_id, delivery, announcement.message):
                deferred += 1
        except SupportSlackNotConfigured:
            logger.warning("announcement_no_slack_credentials", announcement_id=announcement_id, team_id=team_id)
            AnnouncementDelivery.objects.filter(
                announcement_id=announcement.id, status=AnnouncementDelivery.Status.PENDING
            ).update(
                status=AnnouncementDelivery.Status.FAILED,
                error="SupportHog Slack is not connected",
                updated_at=timezone.now(),
            )
            deferred = 0
            break

    _recompute_announcement_status(announcement)
    logger.info(
        "announcement_sent",
        announcement_id=announcement_id,
        team_id=team_id,
        sent=announcement.sent_count,
        failed=announcement.failed_count,
        deferred=deferred,
    )
    if deferred:
        # Ride the task's autoretry backoff instead of sleeping in the worker.
        raise AnnouncementRateLimited(f"{deferred} channel(s) rate limited")


def _deliver_to_channel(team_id: int, delivery: AnnouncementDelivery, message: str) -> bool:
    was_rate_limit_deferred = delivery.error == DELIVERY_RATE_LIMIT_DEFERRED_ERROR
    # Claim the row before posting so a crash between the Slack post and the outcome save
    # can never lead to a double post on retry.
    delivery.error = DELIVERY_IN_FLIGHT_ERROR
    delivery.save(update_fields=["error", "updated_at"])
    try:
        delivery.slack_message_ts = post_support_message(team_id, delivery.slack_channel_id, message)
        delivery.status = AnnouncementDelivery.Status.SENT
        delivery.sent_at = timezone.now()
        delivery.error = ""
    except SupportMessageSendError as e:
        if e.code == "ratelimited" and not was_rate_limit_deferred:
            # Leave the row pending for the task's autoretry; one deferral per row.
            delivery.error = DELIVERY_RATE_LIMIT_DEFERRED_ERROR
            delivery.save(update_fields=["error", "updated_at"])
            return False
        delivery.status = AnnouncementDelivery.Status.FAILED
        delivery.error = e.code[:2000]
    except SupportSlackNotConfigured:
        raise
    except Exception as e:
        delivery.status = AnnouncementDelivery.Status.FAILED
        delivery.error = str(e)[:2000]
    delivery.save(update_fields=["status", "slack_message_ts", "sent_at", "error", "updated_at"])
    logger.info(
        "announcement_channel_delivery",
        announcement_id=str(delivery.announcement_id),
        team_id=team_id,
        channel=delivery.slack_channel_id,
        status=delivery.status,
        slack_message_ts=delivery.slack_message_ts,
        error=delivery.error or None,
    )
    return True


def _recompute_announcement_status(announcement: Announcement) -> None:
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
