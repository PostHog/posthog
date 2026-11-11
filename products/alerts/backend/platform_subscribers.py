"""An insight alert's subscribers, kept on its platform copy as one email and one in-app destination.

`AlertSubscription` stays the record the insight stack sends from until rollback ends, so every
writer that changes it calls `sync_subscriber_destinations` too. The platform delivers from the
destinations, which resolve each user's address and insight access at send time.
"""

from typing import Final
from uuid import UUID

from django.db import transaction

from posthog.dataclasses import frozen
from posthog.models.team import Team

from products.alerts.backend.models.alert import AlertConfiguration, AlertSubscription
from products.alerts_platform.backend.facade.api import remove_subscriber, set_subscriber_destinations
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


def sync_alert_subscriber_destinations(*, team_id: int, alert_id: UUID) -> bool:
    """`sync_subscriber_destinations` for an alert named by id. False when the alert or its copy is gone."""
    alert = AlertConfiguration.objects.select_related("insight").filter(team_id=team_id, id=alert_id).first()
    return alert is not None and sync_subscriber_destinations(alert)


def remove_member_subscriptions(*, user_id: int, organization_id: UUID) -> int:
    """Unsubscribes a user who left an organization from its alerts, and returns how many they had."""
    subscriptions = AlertSubscription.objects.filter(
        user_id=user_id, alert_configuration__team__organization_id=organization_id
    )
    deleted, _ = subscriptions.delete()
    team_ids = list(Team.objects.filter(organization_id=organization_id).values_list("id", flat=True))
    # After the removal commits, so its copies are locked one at a time rather than all at once
    # inside the membership delete. That covers alerts with no insight row, which have no subscription.
    transaction.on_commit(lambda: remove_subscriber(team_ids=team_ids, user_id=user_id), robust=True)
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
