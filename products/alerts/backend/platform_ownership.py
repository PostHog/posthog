"""Writes to insight alerts the platform owns.

An insight alert handed to the platform keeps its insight row for its id, its insight and its
subscriptions, but its settings live on the platform's copy alone. An edit starts from the copy's
settings and writes only the copy. Every writer locks the insight row before the copy.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import replace
from datetime import datetime
from typing import Any, Final
from uuid import UUID

from django.db import transaction

import posthoganalytics

from posthog.models.team.team import Team
from posthog.tasks.alerts.utils import next_check_at_after_schedule_restriction_change

from products.alerts.backend.evaluation.validation import validate_alert_config
from products.alerts.backend.facade.contracts import PlatformCannotOwn
from products.alerts.backend.llm_detector_limits import is_llm_detector_config
from products.alerts.backend.logic.destinations import retire_alert_hog_functions
from products.alerts.backend.models.alert import AlertConfiguration, Threshold
from products.alerts.backend.platform_cutover import (
    can_move,
    delivers_as_it_does_today,
    hand_over,
    in_an_environment,
    takes_new_alert,
)
from products.alerts.backend.platform_insight_alert import (
    alert_from_platform,
    insight_of,
    insight_row_settings,
    interval_of,
    native_insight_alert_view,
    show_copy_settings,
)
from products.alerts.backend.platform_source_cycle import platform_upsert_of
from products.alerts_platform.backend.facade.api import (
    close_owned_firings_now,
    create_configuration,
    delete_copy,
    lock_source_configuration,
    update_configuration,
    update_owned_copy,
)
from products.alerts_platform.backend.facade.contracts import (
    SOURCE_CONDITION_KEY,
    Grouping,
    InvalidPlatformAlertEdit,
    PlatformAlertConfigurationEdit,
    PlatformAlertConfigurationView,
    PlatformAlertCreateRefused,
    PlatformAlertUpsert,
    SourceKind,
)
from products.alerts_platform.backend.facade.enums import PlatformAlertOwner

# What an insight edit changes through the platform's edit. The cadence is a schedule, which the
# platform's edit leaves out, so it is written separately.
_EDITED_FIELDS = ("name", "source_config", "schedule_restriction")


# Turns on, per team, insight alert creates that make no insight row.
NATIVE_CREATE_FLAG: Final = "insight-alerts-native-create"


def creates_native_alert(team_id: int) -> bool:
    """Whether a new insight alert of the team gets no insight row. An environment keeps the row,
    because the platform keeps its alerts on the project's team."""
    team = Team.objects.only("id", "uuid", "organization_id", "parent_team_id").get(id=team_id)
    if team.parent_team_id is not None:
        return False
    return bool(
        posthoganalytics.feature_enabled(
            NATIVE_CREATE_FLAG,
            str(team.uuid),
            groups={"organization": str(team.organization_id), "project": str(team.id)},
            group_properties={
                "organization": {"id": str(team.organization_id)},
                # Both regions read flags from one PostHog project, and project ids repeat across regions.
                "project": {"id": str(team.id), "uuid": str(team.uuid)},
            },
            send_feature_flag_events=False,
        )
    )


def create_native_alert(
    *, team_id: int, insight_id: int, created_by_id: int | None, fields: Mapping[str, Any]
) -> PlatformAlertConfigurationView:
    """Creates an insight alert with no insight row from a create the insight API or the Max tool
    checked, in the caller's transaction, after its limit checks. `fields` holds the alert's other
    fields by name, with `threshold` as the threshold's configuration and `snoozed_until` parsed.
    Its subscribers are the caller's to write.

    Raises `PlatformCannotOwn` for an alert the platform cannot evaluate, and like `create_configuration`.
    """
    threshold_configuration = fields.get("threshold")
    alert = AlertConfiguration(
        team_id=team_id,
        insight_id=insight_id,
        created_by_id=created_by_id,
        **{field: value for field, value in fields.items() if field != "threshold"},
    )
    if threshold_configuration is not None:
        alert.threshold = Threshold(team_id=team_id, insight_id=insight_id, configuration=threshold_configuration)
    if alert.schedule_start_time is not None:
        alert.next_check_at = next_check_at_after_schedule_restriction_change(alert)
    upsert = platform_upsert_of(alert)
    if upsert is None:
        raise PlatformCannotOwn("The alerts platform can't run checks at this frequency.")
    view = create_configuration(
        team_id=alert.team_id,
        source_kind=SourceKind.INSIGHT,
        edit=PlatformAlertConfigurationEdit(
            name=upsert.name,
            enabled=upsert.enabled,
            source_config=upsert.source_config,
            grouping=Grouping(),
            schedule_restriction=upsert.schedule_restriction,
            evaluation_periods=upsert.evaluation_periods,
            datapoints_to_alarm=upsert.datapoints_to_alarm,
            cooldown_minutes=upsert.cooldown_minutes,
            check_interval_minutes=upsert.check_interval_minutes,
        ),
        created_by_id=alert.created_by_id,
        natively=True,
    )
    anchored = upsert.anchor_time is not None
    if not anchored and alert.snoozed_until is None:
        return view
    # A create stores the kind's schedule and no mute, so a start time and a snooze take the writes
    # an edit uses.
    written = update_configuration(
        team_id=team_id,
        source_kinds=[SourceKind.INSIGHT.value],
        configuration_id=view.id,
        change=lambda stored: stored,
        snooze_until=alert.snoozed_until,
        snooze_changed=alert.snoozed_until is not None,
        cadence=upsert if anchored else None,
        rescheduled=anchored,
        source_checked=True,
    )
    assert written is not None
    return written


def on_created(alert: AlertConfiguration, at: datetime) -> bool:
    """Hands a new alert, locked by the caller, to the platform unless its team keeps its alerts on
    insight. False when the alert stays with insight."""
    if not (platform_takes_new_alert(alert) and delivers_as_it_does_today(alert)):
        return False
    return hand_over(alert, at)


def platform_takes_new_alert(alert: AlertConfiguration) -> bool:
    """Whether `on_created` hands an alert like this one to the platform. The alert may be unsaved.

    A new alert has no destinations yet, so it always delivers as it does today.
    """
    return not in_an_environment(alert) and can_move(alert) and takes_new_alert(alert.team_id, new_alert_id=alert.id)


def platform_takes_new_alert_with(
    *, team_id: int, calculation_interval: str, investigation_agent_enabled: bool
) -> bool:
    """Whether `on_created` hands a new alert with these settings to the platform."""
    return platform_takes_new_alert(
        AlertConfiguration(
            team_id=team_id,
            calculation_interval=calculation_interval,
            investigation_agent_enabled=investigation_agent_enabled,
        )
    )


def show_locked_copy(alert: AlertConfiguration) -> bool:
    """Locks the copy of a moved alert whose row the caller locked, and puts the copy's settings on the
    row in place, for an edit to start from. False when the copy is gone."""
    lock_source_configuration(team_id=alert.team_id, public_id=alert.id)
    return alert.id in show_copy_settings([alert])


def on_updated(alert: AlertConfiguration, *, snooze_changed: bool, rescheduled: bool = False) -> None:
    """Writes an edit to a moved alert, made in memory on its row after `show_locked_copy`, onto the
    platform's copy. The row itself is not written. `rescheduled` says the edit moved the alert's due
    time, which the copy then follows.

    Raises `PlatformCannotOwn` for an edit the platform cannot evaluate, such as a frequency it does not run, and
    `InvalidPlatformAlertEdit` for one the platform's schema rejects.
    """
    if not can_move(alert):
        raise PlatformCannotOwn("The alerts platform runs this alert, and it can't run checks at this frequency.")
    upsert = platform_upsert_of(alert)
    assert upsert is not None
    update_owned_copy(
        team_id=alert.team_id,
        legacy_configuration_id=alert.id,
        change=_platform_change_of(upsert),
        snooze_until=alert.snoozed_until,
        snooze_changed=snooze_changed,
        cadence=upsert,
        rescheduled=rescheduled,
        created_by_id=alert.created_by_id,
    )


def hand_over_new_alert(*, team_id: int, alert_id: UUID, at: datetime) -> bool:
    """Hands an alert created in the caller's transaction to the platform unless its team keeps its
    alerts on insight. False when the alert stays with insight."""
    alert = _locked(team_id, alert_id)
    return alert is not None and on_created(alert, at)


def close_moved_alert_firings(*, team_id: int, alert_id: UUID) -> None:
    """Ends a moved alert's firings while its destinations still exist.

    Call it outside the delete's transaction, because the resolve it sends reads the history this
    commits.
    """
    if AlertConfiguration.objects.filter(team_id=team_id, id=alert_id, owner=PlatformAlertOwner.PLATFORM).exists():
        close_owned_firings_now(team_id=team_id, legacy_configuration_id=alert_id)


def delete_alert_destinations_and_copy(*, team_id: int, alert_id: UUID) -> None:
    """Removes an alert's HogFunction destinations, and a moved alert's copy, inside the transaction
    that deletes the alert.

    A moved alert's destinations go with its copy, through the platform's delete. An alert insight
    owns removes them here, and its copy goes after the commit (`delete_shadow_alert_copy`).
    """
    alert = _locked(team_id, alert_id)
    if alert is None:
        return
    if alert.platform_owned and delete_copy(team_id=team_id, legacy_configuration_id=alert_id):
        return
    retire_alert_hog_functions(team_id=team_id, alert_id=str(alert_id))


def delete_shadow_alert_copy(*, team_id: int, alert_id: UUID) -> None:
    """Deletes the copy of an alert insight owns once the alert's delete commits, by any route: the
    API, an insight sweep, or a cascade.

    After the commit, so each copy is locked in a transaction of its own. A sweep or a cascade
    deletes several alerts in one transaction, and locking their copies there in deletion order can
    deadlock with `record_outcomes`, which locks them in id order. A copy whose delete fails is left
    for `delete_orphaned_platform_insight_alert_copies`.
    """
    transaction.on_commit(
        lambda: delete_copy(team_id=team_id, legacy_configuration_id=alert_id, owner=PlatformAlertOwner.SOURCE),
        robust=True,
    )


def _locked(team_id: int, alert_id: UUID) -> AlertConfiguration | None:
    # Only the alert's own row is locked. Locking the team row would make a hot parent a mutex.
    return (
        AlertConfiguration.objects.select_for_update(no_key=True, of=("self",))
        .select_related("team", "threshold")
        .filter(team_id=team_id, id=alert_id)
        .first()
    )


def _platform_change_of(
    upsert: PlatformAlertUpsert,
) -> Callable[[PlatformAlertConfigurationEdit], PlatformAlertConfigurationEdit]:
    # Only the settings an insight alert has. The platform's own, such as grouping, keep what the
    # copy stores, so an edit through the insight API never resets them.
    shared = {field: getattr(upsert, field) for field in _EDITED_FIELDS}
    return lambda stored: replace(stored, enabled=upsert.enabled, **shared)


def guard_native_insight_edit(
    *,
    team_id: int,
    current: PlatformAlertConfigurationEdit,
    edit: PlatformAlertConfigurationEdit,
    check_interval_minutes: int,
) -> None:
    """Refuses a platform edit to an insight alert with no insight row that only the insight API may make."""
    insight = insight_of(team_id, current.source_config)
    if insight is None:
        raise InvalidPlatformAlertEdit("source_config", "The alert's insight no longer exists.")
    stored = current.source_config
    condition = stored.get(SOURCE_CONDITION_KEY) or {}
    threshold = condition.get("threshold")
    alert = AlertConfiguration(
        team_id=team_id,
        insight=insight,
        enabled=current.enabled,
        config=stored.get("config") or {},
        detector_config=condition.get("detector"),
        threshold=Threshold(configuration=threshold) if threshold else None,
        calculation_interval=interval_of(check_interval_minutes),
        skip_weekend=stored.get("skip_weekend", False),
        evaluation_delay_intervals=stored.get("evaluation_delay_intervals", 0),
        investigation_agent_enabled=stored.get("investigation_agent_enabled", False),
        investigation_gates_notifications=stored.get("investigation_gates_notifications", False),
        investigation_inconclusive_action=stored.get("investigation_inconclusive_action", "notify"),
    )
    _refuse_what_only_the_insight_api_checks(alert, edit)


def _refuse_what_only_the_insight_api_checks(alert: AlertConfiguration, edit: PlatformAlertConfigurationEdit) -> None:
    if edit.source_config["insight_id"] != alert.insight_id:
        raise InvalidPlatformAlertEdit("source_config", "An insight alert cannot move to another insight.")
    if edit.enabled and not alert.enabled and is_llm_detector_config(alert.detector_config):
        # Turning an AI alert back on adds to its project's capped model spend, which only the
        # insight API's write admission checks.
        raise InvalidPlatformAlertEdit(
            "enabled",
            "An AI detector alert can't be turned back on through this API. Turn it on in the insight's alert settings.",
        )
    for key, stored in insight_row_settings(alert).items():
        # Insight checks these against the insight's query or its model spend, so only the insight API may change them.
        if key in edit.source_config and edit.source_config[key] != stored:
            raise InvalidPlatformAlertEdit(
                "source_config", f"{key} can't change through this API. Change it in the insight's alert settings."
            )
    condition = edit.source_config[SOURCE_CONDITION_KEY]
    if condition.get("detector") != alert.detector_config:
        # A detector config is checked against its insight and its access rules in the insight API only.
        raise InvalidPlatformAlertEdit(
            "source_config", "The detector can't change through this API. Change it in the insight's alert settings."
        )
    try:
        # The rules the insight API applies, so the insight stack never holds a pair it cannot check.
        validate_alert_config(
            alert.insight.query or {},
            condition["comparison"],
            alert.config,
            condition["threshold"],
            alert.calculation_interval,
            detector_config=alert.detector_config,
        )
    except ValueError as error:
        raise InvalidPlatformAlertEdit("source_config", str(error)) from error


def write_native_alert_edit(
    *, team_id: int, alert_id: UUID, changes: Mapping[str, Any], snooze_changed: bool, rescheduled: bool
) -> PlatformAlertConfigurationView | None:
    """Writes an edit the insight API checked onto an insight alert with no insight row. `changes`
    holds the alert's fields the edit sets, by name, with `threshold` as the threshold's
    configuration. `rescheduled` says the edit moved the alert's due time, to `next_check_at`.
    None when the alert is gone.

    Raises like `on_updated`.
    """
    view = native_insight_alert_view(team_id, alert_id, lock=True)
    if view is None:
        return None
    # Not the API's presentation, which fills in a threshold the alert may not have.
    alert = alert_from_platform(view, team_id=team_id, enabled=view.enabled)
    if alert is None:
        return None
    alert.schedule_start_time = view.anchor_time
    for field, value in changes.items():
        if field == "threshold":
            alert.threshold = Threshold(configuration=value) if value is not None else None
        else:
            setattr(alert, field, value)
    if not can_move(alert):
        raise PlatformCannotOwn("The alerts platform runs this alert, and it can't run checks at this frequency.")
    upsert = platform_upsert_of(alert)
    assert upsert is not None
    return update_configuration(
        team_id=team_id,
        source_kinds=[SourceKind.INSIGHT.value],
        configuration_id=alert_id,
        change=_platform_change_of(upsert),
        snooze_until=alert.snoozed_until,
        snooze_changed=snooze_changed,
        cadence=upsert,
        rescheduled=rescheduled,
        source_checked=True,
    )


def admit_platform_write(
    *,
    team_id: int,
    current: PlatformAlertConfigurationEdit | None,
    edit: PlatformAlertConfigurationEdit,
    check_interval_minutes: int | None,
) -> None:
    """The plan limits on an insight alert created or turned on through the platform, the same ones the
    insight API and the Max tool check. A create counts against the plan's alerts. An enabled alert
    needs the plan to include its cadence, and a real-time one counts against the active real-time
    limit. Without these, the next evaluation would switch the alert off again."""
    organization = Team.objects.select_related("organization").get(id=team_id).organization
    interval = interval_of(check_interval_minutes) if edit.enabled and check_interval_minutes else None
    error = (
        (AlertConfiguration.check_alert_limit(team_id, organization) if current is None else None)
        or AlertConfiguration.interval_entitlement_error(calculation_interval=interval, organization=organization)
        or AlertConfiguration.real_time_alert_validation_error(
            team_id=team_id, organization=organization, calculation_interval=interval, enabled=True
        )
    )
    if error is None:
        return
    if current is None:
        raise PlatformAlertCreateRefused(error)
    raise InvalidPlatformAlertEdit("enabled", error)


def remove_alert_destinations(*, team_id: int, alert_id: UUID) -> None:
    """Removes the HogFunction destinations of an insight alert the platform owns, whatever their events."""
    retire_alert_hog_functions(team_id=team_id, alert_id=str(alert_id))
