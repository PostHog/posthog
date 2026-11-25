"""An insight alert's subscribers, kept on its platform copy as one email and one in-app destination.

Once the platform owns an alert, its destinations are the only record of who subscribes, and its
`AlertSubscription` rows are no longer read or written. The platform delivers from the destinations,
which resolve each user's address and insight access at send time.
"""

from collections.abc import Collection
from typing import Final
from uuid import UUID

from django.db import transaction

from posthog.models.user import User

from products.alerts.backend.activity_logging import log_native_subscriber_changes
from products.alerts.backend.models.alert import AlertConfiguration, AlertSubscription
from products.alerts.backend.platform_insight_alert import native_insight_alert_view
from products.alerts.backend.tasks.tasks import remove_departed_subscriber
from products.alerts_platform.backend.facade.api import set_subscriber_destinations, subscriber_user_ids_by_public_id
from products.alerts_platform.backend.facade.contracts import AlertEventKind
from products.alerts_platform.backend.facade.enums import PlatformAlertOwner

# What a subscriber hears today: a firing and a failed check. An insight alert sends no resolve.
SUBSCRIBER_EVENT_KINDS: Final = (AlertEventKind.FIRING, AlertEventKind.ERRORED)


def sync_subscriber_destinations(alert: AlertConfiguration) -> bool:
    """Writes the subscriptions of an alert the insight stack owns onto its platform copy. False, writing
    nothing, for an alert with no copy, or one the platform owns, whose subscriptions are stale.

    The subscriptions are read under the alert's row lock, which the insight API holds while it edits
    them, so a backfill cannot write back a list an edit just replaced. The alert is locked before
    its copy, in the order an edit through the insight API takes them.
    """
    with transaction.atomic():
        owner = (
            AlertConfiguration.objects.select_for_update(no_key=True, of=("self",))
            .filter(team_id=alert.team_id, id=alert.id)
            .values_list("owner", flat=True)
            .first()
        )
        if owner is None or owner == PlatformAlertOwner.PLATFORM:
            return False
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


def set_native_subscribers(
    *, team_id: int, alert_id: UUID, user_ids: Collection[int], actor_id: int | None, was_impersonated: bool
) -> bool:
    """Writes the subscribers of an insight alert with no insight row, which keeps them only as
    destinations, and logs each user added or removed as the change of the user `actor_id` names. Call it
    with the alert locked. False when the alert is gone."""
    view = native_insight_alert_view(team_id, alert_id)
    alert = AlertConfiguration.from_platform_view(view, team_id=team_id) if view is not None else None
    if alert is None:
        return False
    return _set_platform_subscribers(alert, user_ids=user_ids, actor_id=actor_id, was_impersonated=was_impersonated)


def _set_platform_subscribers(
    alert: AlertConfiguration, *, user_ids: Collection[int], actor_id: int | None, was_impersonated: bool
) -> bool:
    """Writes the subscribers of an insight alert the platform owns onto its destinations, with the insight
    `alert` names as the in-app resource, and logs each user added or removed as the change of the user
    `actor_id` names. Call it with the alert locked. False when the platform has no copy."""
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
        log_native_subscriber_changes(
            alert,
            actor=User.objects.filter(id=actor_id).first() if actor_id is not None else None,
            was_impersonated=was_impersonated,
            added=after - before,
            removed=before - after,
        )
    return written


def set_moved_alert_subscribers(
    *, team_id: int, alert_id: UUID, user_ids: Collection[int] | None, actor_id: int, was_impersonated: bool
) -> bool:
    """`_set_platform_subscribers` for an alert the platform owns that keeps an insight row. With no
    `user_ids`, rewrites the subscribers the copy already names, against the row's insight. Call it with
    the alert locked. False when the row or its copy is gone."""
    alert = (
        AlertConfiguration.objects.select_related("team", "insight")
        .filter(team_id=team_id, id=alert_id, owner=PlatformAlertOwner.PLATFORM)
        .first()
    )
    if alert is None:
        return False
    if user_ids is None:
        user_ids = platform_subscriber_ids(team_id=team_id, alert_ids=[alert_id]).get(alert_id, ())
    return _set_platform_subscribers(alert, user_ids=user_ids, actor_id=actor_id, was_impersonated=was_impersonated)


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


def platform_subscriber_ids(*, team_id: int, alert_ids: Collection[UUID]) -> dict[UUID, tuple[int, ...]]:
    """The users each alert's platform copy names as subscribers, by public id. An alert whose copy has
    no subscriber destination is left out."""
    return subscriber_user_ids_by_public_id(team_id=team_id, public_ids=alert_ids)


def first_subscriber_id(*, team_id: int, alert_id: UUID) -> int | None:
    """One subscriber, from the platform copy's destinations. None when nobody subscribes."""
    return min(platform_subscriber_ids(team_id=team_id, alert_ids=[alert_id]).get(alert_id, ()), default=None)
