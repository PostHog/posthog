"""Hands a team's insight alerts to the alerts platform and back, one alert at a time.

Each alert moves in its own transaction, under its own row lock. An alert that cannot move now is
skipped with a reason, and a later run picks it up. The command is safe to run again.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Final
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from posthog.dataclasses import frozen
from posthog.schema_enums import AlertCalculationInterval, AlertState
from posthog.tasks.alerts.utils import due_insight_alerts_q

from products.alerts.backend.insight_alert_state_machine import apply_platform_state
from products.alerts.backend.models.alert import AlertConfiguration
from products.alerts.backend.platform_source_cycle import platform_upsert_of
from products.alerts_platform.backend.facade.api import give_back_ownership, take_ownership, upsert_configuration
from products.alerts_platform.backend.facade.contracts import HandbackRefusal, PlatformOwnershipHandover
from products.alerts_platform.backend.facade.enums import PlatformAlertOwner, PlatformAlertState

# A firing never moves, so only these states are carried over.
PLATFORM_HANDOVER_STATE: Final[dict[str, PlatformAlertState]] = {
    AlertState.NOT_FIRING: PlatformAlertState.NOT_FIRING,
    # The platform keeps a snooze on the copy's `snooze_until`, which the copy takes from this alert.
    AlertState.SNOOZED: PlatformAlertState.NOT_FIRING,
    AlertState.ERRORED: PlatformAlertState.ERRORED,
}
# Insight has no broken state. A configuration the platform found broken is one the insight stack
# reports as errored and disables.
_INSIGHT_STATE_OF_PLATFORM: Final[dict[PlatformAlertState, AlertState]] = {
    PlatformAlertState.NOT_FIRING: AlertState.NOT_FIRING,
    PlatformAlertState.SNOOZED: AlertState.NOT_FIRING,
    PlatformAlertState.ERRORED: AlertState.ERRORED,
    PlatformAlertState.BROKEN: AlertState.ERRORED,
}


class CutoverSkip(StrEnum):
    """Why an alert stays with the insight stack for now."""

    ALREADY_MOVED = "already_moved"
    # The platform does not evaluate it in parallel, such as a detector or a real-time alert.
    NOT_ON_PLATFORM = "not_on_platform"
    # The investigation agent reads and writes the insight stack's checks, which the platform does not keep.
    INVESTIGATION = "investigation"
    # The two stacks key a firing differently, so a firing moves only after it resolves.
    FIRING = "firing"
    # The insight scheduler owes this alert a check, which may already be running and could notify
    # after the move.
    CHECK_DUE = "check_due"
    # A team on live delivery can have the platform copy inside a firing of its own.
    PLATFORM_FIRING = "platform_firing"


@frozen
class AlertCutover:
    alert_id: UUID
    skipped: CutoverSkip | None


def _team_alert_ids(team_id: int) -> list[UUID]:
    return list(
        AlertConfiguration.objects.filter(team_id=team_id).order_by("created_at", "id").values_list("id", flat=True)
    )


def _insight_check_owed(team_id: int, alert_id: UUID, at: datetime) -> bool:
    # A check advances `next_check_at` when it saves, so an alert the scheduler does not owe a check
    # under the caller's lock has no check between reading it and notifying for it.
    return AlertConfiguration.objects.filter(team_id=team_id, id=alert_id).filter(due_insight_alerts_q(at)).exists()


def cut_over_team(team_id: int, *, now: datetime | None = None) -> tuple[AlertCutover, ...]:
    """Hands every insight alert of one team to the platform, or says why one stays.

    No destination holds an alert back: delivery sends a customized one through its HogFunction.
    """
    return tuple(
        AlertCutover(alert_id=alert_id, skipped=_cut_over_alert(team_id, alert_id, now))
        for alert_id in _team_alert_ids(team_id)
    )


def _is_threshold_alert(alert: AlertConfiguration) -> bool:
    """The platform evaluates detector and real-time alerts in parallel, but cannot own them yet."""
    return not alert.detector_config and alert.calculation_interval != AlertCalculationInterval.REAL_TIME


def _cut_over_alert(team_id: int, alert_id: UUID, now: datetime | None) -> CutoverSkip | None:
    with transaction.atomic():
        # `of` keeps the lock off the nullable threshold join, which PostgreSQL refuses to lock.
        alert = (
            AlertConfiguration.objects.select_for_update(no_key=True, of=("self",))
            .select_related("threshold")
            .get(team_id=team_id, id=alert_id)
        )
        # Read after the lock, so a check that became due while earlier alerts moved is seen as due.
        at = now or timezone.now()
        if alert.platform_owned:
            return CutoverSkip.ALREADY_MOVED
        upsert = platform_upsert_of(alert)
        if upsert is None or not _is_threshold_alert(alert):
            return CutoverSkip.NOT_ON_PLATFORM
        if alert.investigation_agent_enabled:
            return CutoverSkip.INVESTIGATION
        if alert.state == AlertState.FIRING:
            return CutoverSkip.FIRING
        if _insight_check_owed(team_id, alert.id, at):
            return CutoverSkip.CHECK_DUE

        savepoint = transaction.savepoint()
        upsert_configuration(upsert)
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
            return CutoverSkip.PLATFORM_FIRING
        transaction.savepoint_commit(savepoint)
        AlertConfiguration.objects.filter(team_id=alert.team_id, id=alert.id).update(
            owner=PlatformAlertOwner.PLATFORM, owner_changed_at=at
        )
    return None


class RollbackSkip(StrEnum):
    """Why an alert stays with the platform for now."""

    NOT_MOVED = "not_moved"
    # During the shadow the insight stack still checks the alert, and a check it started would save
    # over the state carried back.
    INSIGHT_CHECK_DUE = "insight_check_due"
    PLATFORM_FIRING = "platform_firing"
    PLATFORM_CHECK_DUE = "platform_check_due"
    NOT_PORTABLE = "not_portable"


_ROLLBACK_SKIP: Final[dict[HandbackRefusal, RollbackSkip]] = {
    HandbackRefusal.FIRING: RollbackSkip.PLATFORM_FIRING,
    HandbackRefusal.CHECK_DUE: RollbackSkip.PLATFORM_CHECK_DUE,
    HandbackRefusal.NOT_PORTABLE: RollbackSkip.NOT_PORTABLE,
}


@frozen
class AlertRollback:
    alert_id: UUID
    skipped: RollbackSkip | None


def roll_back_team(team_id: int, *, now: datetime | None = None) -> tuple[AlertRollback, ...]:
    """Hands every insight alert of one team back from the platform, or says why one stays."""
    return tuple(
        AlertRollback(alert_id=alert_id, skipped=_roll_back_alert(team_id, alert_id, now))
        for alert_id in _team_alert_ids(team_id)
    )


def _roll_back_alert(team_id: int, alert_id: UUID, now: datetime | None) -> RollbackSkip | None:
    with transaction.atomic():
        alert = AlertConfiguration.objects.select_for_update(no_key=True).get(team_id=team_id, id=alert_id)
        # Read after the lock, for the same reason as the cutover.
        at = now or timezone.now()
        if not alert.platform_owned:
            return RollbackSkip.NOT_MOVED
        if _insight_check_owed(team_id, alert.id, at):
            return RollbackSkip.INSIGHT_CHECK_DUE

        handback = give_back_ownership(
            team_id=alert.team_id, legacy_configuration_id=alert.id, at=at, source_runs_calendar_schedules=True
        )
        if isinstance(handback, HandbackRefusal):
            return _ROLLBACK_SKIP[handback]

        # A snooze lives on this alert, so an active one stays its state.
        snoozed = alert.snoozed_until is not None and alert.snoozed_until > at
        update_fields = apply_platform_state(
            alert, AlertState.SNOOZED if snoozed else _INSIGHT_STATE_OF_PLATFORM[handback.state]
        )
        alert.owner = PlatformAlertOwner.SOURCE
        alert.owner_changed_at = at
        alert.last_notified_at = handback.last_notified_at
        alert.next_check_at = handback.next_check_at
        alert.save(update_fields=[*update_fields, "owner", "owner_changed_at", "last_notified_at", "next_check_at"])
    return None
