"""Keeps both rows of an insight alert the platform owns in step.

An insight alert the platform owns keeps its insight row: the insight alert pages read it, the shadow
evaluation runs it, and a rollback hands it back. So every write to either row reaches the other in
the same transaction, and every writer locks the insight row before the platform's copy.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import datetime
from uuid import UUID

from products.alerts.backend.insight_alert_state_machine import apply_disable, apply_enable, apply_threshold_change
from products.alerts.backend.models.alert import AlertConfiguration, Threshold
from products.alerts.backend.platform_cutover import can_move, hand_over, has_begun_cutover, in_an_environment
from products.alerts.backend.platform_source_cycle import platform_upsert_of
from products.alerts_platform.backend.facade.api import close_owned_firings_now, delete_owned_copy, update_owned_copy
from products.alerts_platform.backend.facade.contracts import (
    SOURCE_CONDITION_KEY,
    InvalidPlatformAlertEdit,
    PlatformAlertConfigurationEdit,
    PlatformAlertNotEditable,
)

# What an edit through either API can change on both rows. The cadence is a schedule, which the
# platform's edit leaves out, so the check carries it onto the copy instead.
_EDITED_FIELDS = ("name", "source_config", "schedule_restriction")


class PlatformCannotOwn(ValueError):
    """An edit that would leave an alert the platform owns in a shape the platform cannot evaluate."""


def on_created(alert: AlertConfiguration, at: datetime) -> bool:
    """Hands a new alert, locked by the caller, to the platform when its team has begun the cutover,
    so the team never has to be cut over again for it. False when the alert stays with insight."""
    return (
        not in_an_environment(alert) and can_move(alert) and has_begun_cutover(alert.team_id) and hand_over(alert, at)
    )


def on_updated(alert: AlertConfiguration, *, snooze_changed: bool) -> None:
    """Writes an edit the insight API saved onto the platform's copy.

    Raises `PlatformCannotOwn` for an edit the platform cannot evaluate, such as a detector, and
    `InvalidPlatformAlertEdit` for one the platform's schema rejects.
    """
    if not can_move(alert):
        raise PlatformCannotOwn(
            "The alerts platform runs this alert, and it cannot run detectors, real-time checks or the "
            "investigation agent yet."
        )
    update_owned_copy(
        team_id=alert.team_id,
        legacy_configuration_id=alert.id,
        change=_platform_change_of(alert),
        snooze_until=alert.snoozed_until,
        snooze_changed=snooze_changed,
    )


def before_delete(alert: AlertConfiguration) -> None:
    """Ends a moved alert's firings while its destinations still exist.

    Outside the delete's transaction, because the resolve it sends reads the history this commits.
    """
    if alert.platform_owned:
        close_owned_firings_now(team_id=alert.team_id, legacy_configuration_id=alert.id)


def on_deleted(alert: AlertConfiguration) -> None:
    """Deletes a moved alert's copy, inside the transaction that deletes the alert.

    A copy whose alert is deleted another way, such as with its insight, switches itself off at its
    next check.
    """
    if not alert.platform_owned:
        return
    locked = AlertConfiguration.objects.select_for_update(no_key=True, of=("self",)).filter(id=alert.id).first()
    if locked is not None and locked.platform_owned:
        delete_owned_copy(team_id=alert.team_id, legacy_configuration_id=alert.id)


def _platform_change_of(
    alert: AlertConfiguration,
) -> Callable[[PlatformAlertConfigurationEdit], PlatformAlertConfigurationEdit]:
    # Only the settings an insight alert has. The platform's own, such as grouping, keep what the
    # copy stores, so an edit through the insight API never resets them.
    upsert = platform_upsert_of(alert)
    assert upsert is not None
    shared = {field: getattr(upsert, field) for field in _EDITED_FIELDS}
    return lambda stored: replace(stored, enabled=upsert.enabled, **shared)


def mirror_platform_edit(
    *, team_id: int, legacy_configuration_id: UUID
) -> Callable[[PlatformAlertConfigurationEdit], None] | None:
    """Locks the insight row of an alert edited through the platform API, and returns its writer."""
    alert = (
        AlertConfiguration.objects.select_for_update(no_key=True, of=("self",))
        .select_related("threshold")
        .filter(id=legacy_configuration_id)
        .first()
    )
    if alert is None:
        return None
    if alert.team_id != team_id:
        # A copy lives on the project, and an insight alert in an environment is never handed over.
        raise PlatformAlertNotEditable("This alert belongs to one of this project's environments.")
    return lambda edit: _write_insight_row(alert, edit)


def _write_insight_row(alert: AlertConfiguration, edit: PlatformAlertConfigurationEdit) -> None:
    # The inverse of `platform_upsert_of`.
    if edit.source_config["insight_id"] != alert.insight_id:
        raise InvalidPlatformAlertEdit("source_config", "An insight alert cannot move to another insight.")
    condition = edit.source_config[SOURCE_CONDITION_KEY]
    update_fields = ["name", "condition", "schedule_restriction"]
    if edit.enabled != alert.enabled:
        # The shadow evaluation still runs this row, so an on or off moves its state the way the insight API does.
        update_fields.extend(apply_enable(alert) if edit.enabled else apply_disable(alert))
    if condition["comparison"] != alert.condition or condition["threshold"] != _threshold_of(alert):
        update_fields.extend(apply_threshold_change(alert))
        _write_threshold(alert, condition["threshold"])
        update_fields.append("threshold")
    alert.name = edit.name
    alert.condition = condition["comparison"]
    alert.schedule_restriction = edit.schedule_restriction
    alert.save(update_fields=list(dict.fromkeys(update_fields)))


def _threshold_of(alert: AlertConfiguration) -> dict | None:
    return alert.threshold.configuration if alert.threshold else None


def _write_threshold(alert: AlertConfiguration, configuration: dict | None) -> None:
    if configuration is None:
        alert.threshold = None
    elif alert.threshold is not None:
        alert.threshold.configuration = configuration
        alert.threshold.save(update_fields=["configuration"])
    else:
        alert.threshold = Threshold.objects.create(
            team_id=alert.team_id, insight_id=alert.insight_id, configuration=configuration
        )
