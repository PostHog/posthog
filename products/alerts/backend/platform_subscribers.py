"""An insight alert's subscribers, kept on its platform copy as one email and one in-app destination.

`AlertSubscription` stays the record the insight stack sends from until rollback ends, so every
writer that changes it calls `sync_subscriber_destinations` too. The platform delivers from the
destinations, which resolve each user's address and insight access at send time.
"""

from collections.abc import Collection, Sequence
from typing import Final
from uuid import UUID

from posthog.dataclasses import frozen
from posthog.models.user import User

from products.alerts.backend.models.alert import AlertConfiguration, AlertSubscription
from products.alerts_platform.backend.facade.api import set_subscriber_destinations, subscriber_user_ids_by_public_id
from products.alerts_platform.backend.facade.contracts import AlertEventKind

# What a subscriber hears today: a firing and a failed check. An insight alert sends no resolve.
SUBSCRIBER_EVENT_KINDS: Final = (AlertEventKind.FIRING, AlertEventKind.ERRORED)


def sync_subscriber_destinations(alert: AlertConfiguration) -> bool:
    """Writes the alert's subscribers onto its platform copy. False, writing nothing, for an alert with no copy."""
    return set_subscriber_destinations(
        team_id=alert.team_id,
        public_id=alert.id,
        user_ids=list(AlertSubscription.objects.filter(alert_configuration=alert).values_list("user_id", flat=True)),
        event_kinds=SUBSCRIBER_EVENT_KINDS,
        in_app_resource_type="insight",
        in_app_resource_id=alert.insight.short_id,
    )


def remove_member_subscriptions(*, user_id: int, organization_id: UUID) -> int:
    """Unsubscribes a user who left an organization from its alerts, and returns how many they had."""
    subscriptions = AlertSubscription.objects.filter(
        user_id=user_id, alert_configuration__team__organization_id=organization_id
    )
    alert_ids = set(subscriptions.values_list("alert_configuration_id", flat=True))
    deleted, _ = subscriptions.delete()
    _sync_alerts(alert_ids)
    return deleted


def _sync_alerts(alert_ids: Collection[UUID]) -> None:
    for alert in AlertConfiguration.objects.select_related("insight").filter(id__in=alert_ids):
        sync_subscriber_destinations(alert)


@frozen
class SubscriberBackfillCounts:
    written: int
    without_copy: int


def backfill_subscriber_destinations(*, team_id: int | None = None) -> SubscriberBackfillCounts:
    """Writes every insight alert's subscribers onto its platform copy, or one team's. Safe to run
    again, because each write replaces."""
    alerts = AlertConfiguration.objects.select_related("insight")
    if team_id is not None:
        alerts = alerts.filter(team_id=team_id)
    written = 0
    without_copy = 0
    for alert in alerts.iterator():
        if sync_subscriber_destinations(alert):
            written += 1
        else:
            without_copy += 1
    return SubscriberBackfillCounts(written=written, without_copy=without_copy)


def show_platform_subscribers(alerts: Sequence[AlertConfiguration]) -> None:
    """Shows each alert's subscribers as its platform copy's destinations name them, in place.

    An alert whose copy has no subscriber destination keeps its subscriptions, which hold the same
    users until the backfill reaches it.
    """
    by_team: dict[int, list[AlertConfiguration]] = {}
    for alert in alerts:
        by_team.setdefault(alert.team_id, []).append(alert)
    for team_id, team_alerts in by_team.items():
        user_ids = subscriber_user_ids_by_public_id(team_id=team_id, public_ids=[alert.id for alert in team_alerts])
        users = User.objects.in_bulk({user_id for ids in user_ids.values() for user_id in ids})
        for alert in team_alerts:
            if alert.id in user_ids:
                alert.platform_subscribers = [users[user_id] for user_id in user_ids[alert.id] if user_id in users]  # type: ignore[attr-defined]


def subscribers_of(alert: AlertConfiguration) -> list[User]:
    """The alert's subscribers: as `show_platform_subscribers` left them, or its subscriptions."""
    shown = getattr(alert, "platform_subscribers", None)
    return list(shown) if shown is not None else list(alert.subscribed_users.all())


def first_subscriber(alert: AlertConfiguration) -> User | None:
    """One subscriber, from the platform copy's destinations when it has any. None when nobody subscribes."""
    show_platform_subscribers([alert])
    subscribers = subscribers_of(alert)
    return subscribers[0] if subscribers else None
