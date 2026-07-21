"""Business logic for customer-analytics announcements.

An announcement is one plain-text (Slack mrkdwn) message a CSM sends to many customer
Slack channels via the SupportHog bot. Channel access is validated server-side against
the bot's member channels (via the conversations facade) so a caller can never make the
bot post to arbitrary Slack destinations.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.db import transaction

from products.conversations.backend.facade.api import (
    SupportSlackChannelsUnavailable,
    SupportSlackNotConfigured,
    list_support_bot_channels,
)
from products.customer_analytics.backend.facade.contracts import AnnouncementChannelView, AnnouncementValidationError
from products.customer_analytics.backend.models import Account, Announcement, AnnouncementDelivery

if TYPE_CHECKING:
    from posthog.models.team import Team
    from posthog.models.user import User


def create_announcement(team: Team, created_by: User, message: str, channel_ids: list[str]) -> Announcement:
    """Persist the announcement with one delivery row per channel, validated against the
    bot's member channels.

    Security boundary: only channels in the bot's member list get a ``pending`` row (the
    send task posts pending rows exclusively), so a crafted channel ID can never make the
    bot post to an arbitrary Slack destination. Rather than rejecting the whole request,
    a non-member channel is born ``failed`` with ``not_in_channel`` — the same outcome as
    losing the channel between create and delivery, so history and rollup handle both
    identically and valid channels still deliver.

    Raises :class:`AnnouncementValidationError` only when the member list itself can't be
    resolved (bot not connected, Slack unavailable) — persisting zero rows in that case.
    """
    try:
        allowed = {c.id: c for c in list_support_bot_channels(team.pk, members_only=True)}
    except SupportSlackNotConfigured:
        raise AnnouncementValidationError("The SupportHog Slack bot is not connected.")
    except SupportSlackChannelsUnavailable:
        raise AnnouncementValidationError("Could not verify Slack channels right now. Please try again.")

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
    """The bot's member channels labeled by customer account, for the composer picker.

    Channels mapped to a customer sort first (by customer name); unmapped ones fall
    below, sorted by channel name. Raises the conversations facade errors unchanged.
    """
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
