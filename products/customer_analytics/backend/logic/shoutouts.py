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
from products.customer_analytics.backend.facade.contracts import ShoutoutChannelView, ShoutoutValidationError
from products.customer_analytics.backend.models import Account, Shoutout, ShoutoutDelivery

if TYPE_CHECKING:
    from posthog.models.team import Team
    from posthog.models.user import User

logger = structlog.get_logger(__name__)


class ShoutoutRateLimited(Exception):
    pass


def create_shoutout(team: Team, created_by: User, message: str, channel_ids: list[str]) -> Shoutout:
    try:
        allowed = {c.id: c for c in list_support_bot_channels(team.pk, members_only=True)}
    except SupportSlackNotConfigured:
        raise ShoutoutValidationError("The SupportHog Slack bot is not connected.")
    except SupportSlackChannelsUnavailable:
        raise ShoutoutValidationError("Could not verify Slack channels right now. Please try again.")

    # Only member channels get a pending row (the only state the send task posts), so a
    # crafted channel ID can never make the bot post to an arbitrary Slack destination;
    # non-member channels are born failed, same as a channel lost between create and send.
    with transaction.atomic():
        shoutout = Shoutout.objects.create(
            team=team,
            message=message,
            created_by=created_by,
            total_channels=len(channel_ids),
            status=Shoutout.Status.PENDING,
        )
        ShoutoutDelivery.objects.bulk_create(
            [
                ShoutoutDelivery(
                    team=team,
                    shoutout=shoutout,
                    slack_channel_id=cid,
                    slack_channel_name=allowed[cid].name if cid in allowed else "",
                    status=(ShoutoutDelivery.Status.PENDING if cid in allowed else ShoutoutDelivery.Status.FAILED),
                    error="" if cid in allowed else "not_in_channel",
                )
                for cid in channel_ids
            ]
        )
    return shoutout


def list_channels(team_id: int) -> list[ShoutoutChannelView]:
    member_channels = list_support_bot_channels(team_id, members_only=True)
    name_by_channel = _customer_names_by_channel(team_id)
    enriched = [
        ShoutoutChannelView(
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


def send_pending_deliveries(shoutout_id: str, team_id: int) -> None:
    shoutout = Shoutout.objects.for_team(team_id).filter(id=shoutout_id).first()
    if not shoutout:
        logger.warning("shoutout_not_found", shoutout_id=shoutout_id, team_id=team_id)
        return

    pending = list(ShoutoutDelivery.objects.filter(shoutout_id=shoutout.id, status=ShoutoutDelivery.Status.PENDING))
    if not pending:
        _recompute_shoutout_status(shoutout)
        return

    # A pending row still claimed in-flight means a previous run crashed mid-post; the message
    # may already be in Slack, so never re-post it.
    interrupted_ids = {delivery.id for delivery in pending if delivery.error == DELIVERY_IN_FLIGHT_ERROR}
    if interrupted_ids:
        ShoutoutDelivery.objects.for_team(team_id).filter(id__in=interrupted_ids).update(
            status=ShoutoutDelivery.Status.FAILED,
            error=DELIVERY_INTERRUPTED_ERROR,
            updated_at=timezone.now(),
        )
        pending = [delivery for delivery in pending if delivery.id not in interrupted_ids]

    if shoutout.status == Shoutout.Status.PENDING:
        shoutout.status = Shoutout.Status.SENDING
        shoutout.save(update_fields=["status", "updated_at"])

    deferred = 0
    for delivery in pending:
        try:
            if not _deliver_to_channel(team_id, delivery, shoutout.message):
                deferred += 1
        except SupportSlackNotConfigured:
            logger.warning("shoutout_no_slack_credentials", shoutout_id=shoutout_id, team_id=team_id)
            ShoutoutDelivery.objects.filter(shoutout_id=shoutout.id, status=ShoutoutDelivery.Status.PENDING).update(
                status=ShoutoutDelivery.Status.FAILED,
                error="SupportHog Slack is not connected",
                updated_at=timezone.now(),
            )
            deferred = 0
            break

    _recompute_shoutout_status(shoutout)
    logger.info(
        "shoutout_sent",
        shoutout_id=shoutout_id,
        team_id=team_id,
        sent=shoutout.sent_count,
        failed=shoutout.failed_count,
        deferred=deferred,
    )
    if deferred:
        # Ride the task's autoretry backoff instead of sleeping in the worker.
        raise ShoutoutRateLimited(f"{deferred} channel(s) rate limited")


def _deliver_to_channel(team_id: int, delivery: ShoutoutDelivery, message: str) -> bool:
    was_rate_limit_deferred = delivery.error == DELIVERY_RATE_LIMIT_DEFERRED_ERROR
    # Claim the row before posting so a crash between the Slack post and the outcome save
    # can never lead to a double post on retry.
    delivery.error = DELIVERY_IN_FLIGHT_ERROR
    delivery.save(update_fields=["error", "updated_at"])
    try:
        delivery.slack_message_ts = post_support_message(team_id, delivery.slack_channel_id, message)
        delivery.status = ShoutoutDelivery.Status.SENT
        delivery.sent_at = timezone.now()
        delivery.error = ""
    except SupportMessageSendError as e:
        if e.code == "ratelimited" and not was_rate_limit_deferred:
            # Leave the row pending for the task's autoretry; one deferral per row.
            delivery.error = DELIVERY_RATE_LIMIT_DEFERRED_ERROR
            delivery.save(update_fields=["error", "updated_at"])
            return False
        delivery.status = ShoutoutDelivery.Status.FAILED
        delivery.error = e.code[:2000]
    except SupportSlackNotConfigured:
        raise
    except Exception as e:
        delivery.status = ShoutoutDelivery.Status.FAILED
        delivery.error = str(e)[:2000]
    delivery.save(update_fields=["status", "slack_message_ts", "sent_at", "error", "updated_at"])
    logger.info(
        "shoutout_channel_delivery",
        shoutout_id=str(delivery.shoutout_id),
        team_id=team_id,
        channel=delivery.slack_channel_id,
        status=delivery.status,
        slack_message_ts=delivery.slack_message_ts,
        error=delivery.error or None,
    )
    return True


def _recompute_shoutout_status(shoutout: Shoutout) -> None:
    counts = ShoutoutDelivery.objects.filter(shoutout_id=shoutout.id).aggregate(
        sent=models.Count("id", filter=models.Q(status=ShoutoutDelivery.Status.SENT)),
        failed=models.Count("id", filter=models.Q(status=ShoutoutDelivery.Status.FAILED)),
        pending=models.Count("id", filter=models.Q(status=ShoutoutDelivery.Status.PENDING)),
    )
    sent, failed, pending = counts["sent"], counts["failed"], counts["pending"]

    if pending:
        status = Shoutout.Status.SENDING
    elif failed and sent:
        status = Shoutout.Status.PARTIALLY_FAILED
    elif failed:
        status = Shoutout.Status.FAILED
    else:
        status = Shoutout.Status.SENT

    shoutout.sent_count = sent
    shoutout.failed_count = failed
    shoutout.status = status
    update_fields = ["sent_count", "failed_count", "status", "updated_at"]
    if not pending and shoutout.sent_at is None:
        shoutout.sent_at = timezone.now()
        update_fields.append("sent_at")
    shoutout.save(update_fields=update_fields)
