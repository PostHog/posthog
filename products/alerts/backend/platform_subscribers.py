"""An insight alert's subscribers, kept on its platform copy as one email and one in-app destination.

`AlertSubscription` stays the record the insight stack sends from until rollback ends, so every
writer that changes it calls `sync_subscriber_destinations` too. The platform delivers from the
destinations, which resolve each user's address and insight access at send time.
"""

from collections.abc import Collection
from typing import Final
from uuid import UUID

from django.db import transaction

from posthog.dataclasses import frozen

from products.alerts.backend.activity_logging import log_native_subscriber_changes
from products.alerts.backend.models.alert import AlertConfiguration, AlertSubscription
from products.alerts.backend.tasks.tasks import remove_departed_subscriber
from products.alerts_platform.backend.facade.api import set_subscriber_destinations, subscriber_user_ids_by_public_id
from products.alerts_platform.backend.facade.contracts import AlertEventKind

# What a subscriber hears today: a firing and a failed check. An insight alert sends no resolve.
SUBSCRIBER_EVENT_KINDS: Final = (AlertEventKind.FIRING, AlertEventKind.ERRORED)


def sync_subscriber_destinations(alert: AlertConfiguration) -> bool:
    """Writes the alert's subscribers onto its platform copy. False, writing nothing, for an alert with no copy.

    The subscriptions are read under the alert's row lock, which the insight API holds while it edits
    them, so a backfill cannot write back a list an edit just replaced. The alert is locked before
    its copy, in the order an edit through the insight API takes them.
    """
    with transaction.atomic():
        AlertConfiguration.objects.select_for_update(no_key=True, of=("self",)).filter(
            team_id=alert.team_id, id=alert.id
        ).first()
        return set_subscriber_destinations(
            team_id=alert.team_id,
            public_id=alert.id,
            user_ids=list(
                AlertSubscription.objects.filter(alert_configuration=alert).values_list("user_id", flat=True)
            ),
            event_kinds=SUBSCRIBER_EVENT_KINDS,
            in_app_resource_type="insight",
            in_app_resource_id=alert.insight.short_id,
        )


def set_native_subscribers(*, alert: AlertConfiguration, user_ids: Collection[int]) -> bool:
    """Writes the subscribers of an insight alert with no insight row, which keeps them only as
    destinations, and logs each user added or removed. Call it with the alert locked. False when the
    alert is gone."""
    before = set(platform_subscriber_ids(team_id=alert.team_id, alert_ids=[alert.id]).get(alert.id, ()))
    after = set(user_ids)
    written = set_subscriber_destinations(
        team_id=alert.team_id,
        public_id=alert.id,
        user_ids=user_ids,
        event_kinds=SUBSCRIBER_EVENT_KINDS,
        in_app_resource_type="insight",
        in_app_resource_id=alert.insight.short_id,
    )
    if written:
        log_native_subscriber_changes(alert, added=after - before, removed=before - after)
    return written


def sync_alert_subscriber_destinations(*, team_id: int, alert_id: UUID) -> bool:
    """`sync_subscriber_destinations` for an alert named by id. False when the alert or its copy is gone."""
    alert = AlertConfiguration.objects.select_related("insight").filter(team_id=team_id, id=alert_id).first()
    return alert is not None and sync_subscriber_destinations(alert)


def remove_member_subscriptions(*, user_id: int, organization_id: UUID) -> int:
    """Unsubscribes a user who left an organization from its alerts, and returns how many they had."""
    subscriptions = AlertSubscription.objects.filter(
        user_id=user_id, alert_configuration__team__organization_id=organization_id
    )
    alert_ids = [str(alert_id) for alert_id in subscriptions.values_list("alert_configuration_id", flat=True)]
    deleted, _ = subscriptions.delete()
    # A background task with retries, after the removal commits: the scan reads every subscriber
    # destination of the organization's alerts, including alerts with no insight row, which have no
    # subscription to delete here.
    transaction.on_commit(
        lambda: remove_departed_subscriber.delay(
            organization_id=str(organization_id), user_id=user_id, alert_ids=alert_ids
        )
    )
    return deleted


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


def platform_subscriber_ids(*, team_id: int, alert_ids: Collection[UUID]) -> dict[UUID, tuple[int, ...]]:
    """The users each alert's platform copy names as subscribers, by public id. An alert whose copy has
    no subscriber destination is left out, and its subscriptions hold the same users until the backfill
    reaches it."""
    return subscriber_user_ids_by_public_id(team_id=team_id, public_ids=alert_ids)


def first_subscriber_id(*, team_id: int, alert_id: UUID) -> int | None:
    """One subscriber, from the platform copy's destinations when it has any. None when nobody subscribes."""
    copied = platform_subscriber_ids(team_id=team_id, alert_ids=[alert_id]).get(alert_id)
    if copied is not None:
        return min(copied, default=None)
    return (
        AlertSubscription.objects.filter(alert_configuration_id=alert_id, alert_configuration__team_id=team_id)
        .order_by("user_id")
        .values_list("user_id", flat=True)
        .first()
    )
