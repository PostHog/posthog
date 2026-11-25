"""Hands a new insight alert to the alerts platform, and maps the platform's state back to insight's."""

from __future__ import annotations

from datetime import datetime
from typing import Final
from uuid import UUID

from django.db import transaction

from posthog.schema_enums import AlertState

from products.alerts.backend.facade.destinations import choose_delivery_path
from products.alerts.backend.models.alert import AlertConfiguration
from products.alerts.backend.platform_source_cycle import DELIVERY_EVENT_IDS, platform_upsert_of
from products.alerts.backend.platform_subscribers import sync_subscriber_destinations
from products.alerts_platform.backend.facade.api import take_ownership, upsert_configuration
from products.alerts_platform.backend.facade.contracts import DeliveryPath, PlatformOwnershipHandover, SourceKind
from products.alerts_platform.backend.facade.delivery import has_legacy_event_emitter
from products.alerts_platform.backend.facade.enums import PlatformAlertOwner, PlatformAlertState

PLATFORM_HANDOVER_STATE: Final[dict[str, PlatformAlertState]] = {
    # The platform carries the firing with its start unknown. An insight alert notifies on every
    # firing check, so the platform's next check sends what the insight stack would have sent.
    AlertState.FIRING: PlatformAlertState.FIRING,
    AlertState.NOT_FIRING: PlatformAlertState.NOT_FIRING,
    # The platform keeps a snooze on the copy's `snooze_until`, which the copy takes from this alert.
    AlertState.SNOOZED: PlatformAlertState.NOT_FIRING,
    AlertState.ERRORED: PlatformAlertState.ERRORED,
}
# Insight has no broken state. A configuration the platform found broken is one the insight stack
# reports as errored and disables.
_INSIGHT_STATE_OF_PLATFORM: Final[dict[PlatformAlertState, AlertState]] = {
    # Only a read sees a firing, because the platform keeps a firing alert until it resolves.
    PlatformAlertState.FIRING: AlertState.FIRING,
    PlatformAlertState.NOT_FIRING: AlertState.NOT_FIRING,
    PlatformAlertState.SNOOZED: AlertState.NOT_FIRING,
    PlatformAlertState.ERRORED: AlertState.ERRORED,
    PlatformAlertState.BROKEN: AlertState.ERRORED,
}


def insight_state_of_platform(
    platform_state: PlatformAlertState, *, snoozed_until: datetime | None, at: datetime
) -> AlertState:
    """The insight state for a platform state, for the API's read of a moved alert.

    An active snooze stays its state.
    """
    if snoozed_until is not None and snoozed_until > at:
        return AlertState.SNOOZED
    return _INSIGHT_STATE_OF_PLATFORM[platform_state]


def delivers_as_it_does_today(alert: AlertConfiguration) -> bool:
    """Whether the platform can deliver the alert the way its destinations expect: natively, or
    through its HogFunctions when the insight events those listen on are emitted."""
    if has_legacy_event_emitter(SourceKind.INSIGHT):
        return True
    path = choose_delivery_path(
        source=SourceKind.INSIGHT,
        team_id=alert.team_id,
        alert_id=str(alert.id),
        allowed_event_ids=DELIVERY_EVENT_IDS,
    )
    return path == DeliveryPath.NATIVE


def in_an_environment(alert: AlertConfiguration) -> bool:
    """Whether the alert belongs to a child environment, whose copy would live on its project."""
    return alert.team.parent_team_id is not None


def can_move(alert: AlertConfiguration) -> bool:
    """Whether the platform can own the alert: one it evaluates, with a threshold or a detector, and
    with or without the investigation agent."""
    return platform_upsert_of(alert) is not None


def takes_new_alert(team_id: int, *, new_alert_id: UUID) -> bool:
    """Whether the platform owns a team's new insight alert: when it owns another of the team's alerts,
    or when the team has no other. Every team's alerts are the platform's since the insight cutover,
    so only a team whose alerts all stay with insight, which tests set up, keeps new ones on insight."""
    owners = set(
        AlertConfiguration.objects.filter(team_id=team_id)
        .exclude(id=new_alert_id)
        .values_list("owner", flat=True)
        .distinct()
    )
    return not owners or PlatformAlertOwner.PLATFORM in owners


def hand_over(alert: AlertConfiguration, at: datetime) -> bool:
    """Copies an insight alert locked by the caller onto the platform and makes the platform its owner,
    on both rows. False, changing nothing, when the platform copy is inside a firing of its own.

    The caller checks `can_move` first.
    """
    upsert = platform_upsert_of(alert)
    assert upsert is not None
    savepoint = transaction.savepoint_create()
    upsert_configuration(upsert)
    sync_subscriber_destinations(alert)
    taken = take_ownership(
        PlatformOwnershipHandover(
            legacy_configuration_id=alert.id,
            team_id=alert.team_id,
            state=PLATFORM_HANDOVER_STATE[alert.state],
            last_notified_at=alert.last_notified_at,
            consecutive_failures=0,
            next_check_at=alert.next_check_at or at,
            at=at,
        )
    )
    if not taken:
        # The copy stays as live delivery left it. A copy disabled here would drop out of
        # discovery and never resolve the firing it is inside.
        transaction.savepoint_rollback(savepoint)
        return False
    transaction.savepoint_commit(savepoint)
    # `update()` rather than `save()`: a handover is not a user's edit, and `save()` would log one.
    AlertConfiguration.objects.filter(team_id=alert.team_id, id=alert.id).update(
        owner=PlatformAlertOwner.PLATFORM, owner_changed_at=at
    )
    alert.owner = PlatformAlertOwner.PLATFORM
    alert.owner_changed_at = at
    return True
