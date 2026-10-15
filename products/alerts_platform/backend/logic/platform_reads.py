"""Reads of the shared alert tables, as a consumer outside this product sees them.

Separate from `platform_lifecycle`, which serves the source adapters. These serve a reader
outside the product, so they return views rather than rows and never change one.
"""

from collections.abc import Collection, Sequence
from datetime import datetime
from uuid import UUID

from django.db.models import OuterRef, Prefetch, QuerySet, Subquery

from products.alerts_platform.backend.facade.contracts import (
    InstanceCheckState,
    PlatformAlertConfigurationPage,
    PlatformAlertConfigurationView,
    PlatformAlertHistory,
    PlatformAlertRuntime,
    PlatformAlertSnapshot,
)
from products.alerts_platform.backend.facade.enums import PlatformAlertOwner, PlatformAlertState
from products.alerts_platform.backend.logic import platform_alert_events
from products.alerts_platform.backend.models import PlatformAlert, PlatformAlertConfiguration


def instance_view(alert: PlatformAlert, configuration: PlatformAlertConfiguration) -> PlatformAlertSnapshot:
    """One instance row as a contract. Shared with the test doors, so both describe one shape.

    A configuration whose checks fail shows that status on every instance, because nothing says
    which group caused the failure. The row keeps its own state so a recovery continues its firing.
    A configuration mute shows on every instance for the same reason a check reads it there.
    """
    seen = InstanceCheckState.composed(
        grouping_key=alert.grouping_key,
        state=alert.state,
        check_status=configuration.check_status,
        configuration_snooze_until=configuration.snooze_until,
        snooze_until=alert.snooze_until,
    )
    return PlatformAlertSnapshot(
        id=alert.id,
        grouping_key=alert.grouping_key,
        state=seen.state,
        firing_started_at=alert.firing_started_at,
        last_notified_at=alert.last_notified_at,
        snooze_until=seen.snooze_until,
    )


def _configuration_view(configuration: PlatformAlertConfiguration) -> PlatformAlertConfigurationView:
    return PlatformAlertConfigurationView(
        id=configuration.id,
        name=configuration.name,
        enabled=configuration.enabled,
        source_kind=configuration.source_kind,
        source_config=configuration.source_config,
        check_interval_minutes=configuration.check_interval_minutes,
        recurrence_unit=configuration.recurrence_unit,
        anchor_time=configuration.anchor_time,
        evaluation_periods=configuration.evaluation_periods,
        datapoints_to_alarm=configuration.datapoints_to_alarm,
        cooldown_minutes=configuration.cooldown_minutes,
        schedule_restriction=configuration.schedule_restriction,
        next_check_at=configuration.next_check_at,
        consecutive_failures=configuration.consecutive_failures,
        legacy_configuration_id=configuration.legacy_configuration_id,
        created_at=configuration.created_at,
        updated_at=configuration.updated_at,
        alerts=tuple(instance_view(alert, configuration) for alert in configuration.alerts.all()),
    )


def _readable(team_id: int, source_kinds: Sequence[str]) -> QuerySet[PlatformAlertConfiguration]:
    """Configurations of the given kinds belonging to `team_id`, instances prefetched.

    The caller resolves which kinds it may read, because that depends on the caller's grants
    rather than on anything this product knows.
    """
    instances = PlatformAlert.objects.for_team(team_id, canonical=True).order_by("grouping_key")
    return (
        PlatformAlertConfiguration.objects.for_team(team_id, canonical=True)
        .filter(source_kind__in=list(source_kinds))
        .prefetch_related(Prefetch("alerts", queryset=instances))
        .order_by("-created_at", "-id")
    )


def list_configurations(
    *, team_id: int, source_kinds: Sequence[str], limit: int, offset: int
) -> PlatformAlertConfigurationPage:
    """One page of configurations, newest first, with the total behind it.

    The page is taken in the database rather than in the caller, so a team with many alerts
    costs one page rather than all of them. Slicing keeps the prefetch, which resolves over the
    page's rows alone.
    """
    readable = _readable(team_id, source_kinds)
    return PlatformAlertConfigurationPage(
        configurations=tuple(_configuration_view(row) for row in readable[offset : offset + limit]),
        total=readable.count(),
    )


def get_configuration(
    *, team_id: int, source_kinds: Sequence[str], configuration_id: UUID
) -> PlatformAlertConfigurationView | None:
    """One configuration, or None when it does not exist or the caller may not read its kind."""
    row = _readable(team_id, source_kinds).filter(id=configuration_id).first()
    return None if row is None else _configuration_view(row)


def alert_snapshot(team_id: int, configuration_id: str, grouping_key: str) -> PlatformAlertSnapshot | None:
    """One group's current runtime state, or None when the platform has recorded none."""
    alert = (
        PlatformAlert.objects.for_team(team_id)
        .select_related("configuration")
        .filter(configuration_id=configuration_id, grouping_key=grouping_key)
        .first()
    )
    return instance_view(alert, alert.configuration) if alert is not None else None


def runtime_by_legacy_id(
    *, team_id: int, legacy_configuration_ids: Collection[UUID]
) -> dict[UUID, PlatformAlertRuntime]:
    """The runtime state of each named alert the platform owns, keyed by the source's id, in one query.

    An alert the platform does not own is left out, because its source's own row is then the one
    that moves. Only the ungrouped instance is read: a source that shows one state per alert has
    no groups, and a copy with no instance yet has not been checked since the handover.
    """
    if not legacy_configuration_ids:
        return {}
    ungrouped = PlatformAlert.objects.for_team(team_id).filter(configuration=OuterRef("pk"), grouping_key="")
    rows = (
        PlatformAlertConfiguration.objects.for_team(team_id)
        .filter(legacy_configuration_id__in=list(legacy_configuration_ids), owner=PlatformAlertOwner.PLATFORM)
        .annotate(
            instance_state=Subquery(ungrouped.values("state")[:1]),
            instance_last_notified_at=Subquery(ungrouped.values("last_notified_at")[:1]),
        )
        .values_list(
            "legacy_configuration_id",
            "instance_state",
            "check_status",
            "instance_last_notified_at",
            "consecutive_failures",
            "next_check_at",
        )
    )
    return {
        legacy_id: PlatformAlertRuntime(
            state=PlatformAlertState(
                InstanceCheckState.composed(
                    grouping_key="",
                    state=state or PlatformAlertState.NOT_FIRING,
                    check_status=check_status,
                    configuration_snooze_until=None,
                ).state
            ),
            last_notified_at=last_notified_at,
            consecutive_failures=consecutive_failures,
            next_check_at=next_check_at,
        )
        for legacy_id, state, check_status, last_notified_at, consecutive_failures, next_check_at in rows
        if legacy_id is not None
    }


def history_by_legacy_id(
    *, team_id: int, legacy_configuration_ids: Collection[UUID], since: datetime, until: datetime
) -> dict[UUID, PlatformAlertHistory]:
    """The check history in `[since, until)` of each named alert the platform owns, keyed by the
    source's id.

    One Postgres query finds the platform's ids and one ClickHouse query reads the history. An
    alert the platform does not own is left out, as in `runtime_by_legacy_id`.
    """
    if not legacy_configuration_ids:
        return {}
    legacy_by_platform_id = {
        platform_id: legacy_id
        for platform_id, legacy_id in PlatformAlertConfiguration.objects.for_team(team_id)
        .filter(legacy_configuration_id__in=list(legacy_configuration_ids), owner=PlatformAlertOwner.PLATFORM)
        .values_list("id", "legacy_configuration_id")
        if legacy_id is not None
    }
    histories = platform_alert_events.history(team_id, legacy_by_platform_id, since=since, until=until)
    return {legacy_by_platform_id[platform_id]: history for platform_id, history in histories.items()}
