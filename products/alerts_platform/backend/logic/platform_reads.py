"""Reads of the shared alert tables, as a consumer outside this product sees them.

Separate from `platform_lifecycle`, which serves the source adapters. These serve a reader
outside the product, so they return views rather than rows and never change one.
"""

from collections.abc import Collection, Sequence
from datetime import datetime
from uuid import UUID

from django.db.models import Case, Exists, Max, OuterRef, Prefetch, QuerySet, Subquery, Value, When
from django.db.models.functions import Coalesce

from products.alerts_platform.backend.facade.contracts import (
    Grouping,
    InstanceCheckState,
    PlatformAlertConfigurationPage,
    PlatformAlertConfigurationView,
    PlatformAlertHistory,
    PlatformAlertRuntime,
    PlatformAlertSnapshot,
    PlatformCheckEntry,
    PlatformCheckEventPage,
    PlatformCheckPage,
    PlatformLastCheck,
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
        labels=alert.labels,
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
        grouping=Grouping.from_stored(configuration.grouping),
        snooze_until=configuration.snooze_until,
        check_status=configuration.check_status,
        overflowed_groups=configuration.overflowed_groups,
        overflow_is_lower_bound=configuration.overflow_is_lower_bound,
        owner=configuration.owner,
        created_at=configuration.created_at,
        updated_at=configuration.updated_at,
        alerts=tuple(instance_view(alert, configuration) for alert in configuration.alerts.all()),
        labels=configuration.labels,
        annotations=configuration.annotations,
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
    *,
    team_id: int,
    source_kinds: Sequence[str],
    limit: int,
    offset: int,
    legacy_configuration_id: UUID | None = None,
    configuration_ids: Collection[UUID] | None = None,
) -> PlatformAlertConfigurationPage:
    """One page of configurations, newest first, with the total behind it. With a
    `legacy_configuration_id`, only the copy of that source row. With `configuration_ids`, only those.

    The page is taken in the database rather than in the caller, so a team with many alerts
    costs one page rather than all of them. Slicing keeps the prefetch, which resolves over the
    page's rows alone.
    """
    readable = _readable(team_id, source_kinds)
    if legacy_configuration_id is not None:
        readable = readable.filter(legacy_configuration_id=legacy_configuration_id)
    if configuration_ids is not None:
        readable = readable.filter(id__in=list(configuration_ids))
    return PlatformAlertConfigurationPage(
        configurations=tuple(_configuration_view(row) for row in readable[offset : offset + limit]),
        total=readable.count(),
    )


def count_configurations(
    *, team_id: int, source_kind: str, enabled_only: bool = False, check_interval_minutes: int | None = None
) -> int:
    """How many alerts of a kind a team has on the platform, copies included, whoever owns them."""
    configurations = PlatformAlertConfiguration.objects.for_team(team_id, canonical=True).filter(
        source_kind=source_kind
    )
    if enabled_only:
        configurations = configurations.filter(enabled=True)
    if check_interval_minutes is not None:
        configurations = configurations.filter(check_interval_minutes=check_interval_minutes)
    return configurations.count()


def copied_legacy_ids(*, team_id: int, source_kind: str) -> frozenset[UUID]:
    """The ids of a team's source rows of a kind that have a platform copy, so a source counting its
    alerts can add only the rows the platform does not already count."""
    return frozenset(
        legacy_id
        for legacy_id in PlatformAlertConfiguration.objects.for_team(team_id, canonical=True)
        .filter(source_kind=source_kind, legacy_configuration_id__isnull=False)
        .values_list("legacy_configuration_id", flat=True)
        if legacy_id is not None
    )


def get_configuration(
    *, team_id: int, source_kinds: Sequence[str], configuration_id: UUID, lock: bool = False
) -> PlatformAlertConfigurationView | None:
    """One configuration, or None when it does not exist or the caller may not read its kind.

    With `lock`, the row stays locked until the caller's transaction ends, so a delete waits for it.
    """
    rows = _readable(team_id, source_kinds).filter(id=configuration_id)
    if lock:
        rows = rows.select_for_update(no_key=True)
    row = rows.first()
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


# A configuration's `destination_alert_id`, computed in the query.
_PUBLIC_ID = Coalesce("legacy_configuration_id", "id")


def _owned_with_public_ids(team_id: int, public_ids: Collection[UUID]) -> QuerySet[PlatformAlertConfiguration]:
    """The alerts the platform owns with these public ids (`PlatformAlertConfiguration.destination_alert_id`)."""
    return PlatformAlertConfiguration.objects.for_team(team_id).filter(
        PlatformAlertConfiguration.with_destination_alert_ids(public_ids), owner=PlatformAlertOwner.PLATFORM
    )


def runtime_by_public_id(*, team_id: int, public_ids: Collection[UUID]) -> dict[UUID, PlatformAlertRuntime]:
    """The runtime state of each named alert the platform owns, keyed by its public id, in one query.

    An alert the platform does not own is left out, because its source's own row is then the one
    that moves. A source shows one state per alert, so a grouped alert fires while any of its groups
    fires, and was last notified when any group last was. A copy with no instance yet has not been
    checked since the handover.
    """
    if not public_ids:
        return {}
    instances = PlatformAlert.objects.for_team(team_id).filter(configuration=OuterRef("pk"))
    latest_notified = instances.order_by().values("configuration").annotate(at=Max("last_notified_at")).values("at")
    rows = (
        _owned_with_public_ids(team_id, public_ids)
        .annotate(
            public_id=_PUBLIC_ID,
            instance_state=Case(
                When(
                    Exists(instances.filter(state=PlatformAlertState.FIRING)),
                    then=Value(PlatformAlertState.FIRING.value),
                ),
                default=Subquery(instances.filter(grouping_key="").values("state")[:1]),
            ),
            instance_last_notified_at=Subquery(latest_notified),
        )
        .values_list(
            "public_id",
            "instance_state",
            "check_status",
            "instance_last_notified_at",
            "consecutive_failures",
            "next_check_at",
            "grouping",
        )
    )
    return {
        public_id: PlatformAlertRuntime(
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
            grouping=Grouping.from_stored(grouping),
        )
        for public_id, state, check_status, last_notified_at, consecutive_failures, next_check_at, grouping in rows
    }


def _public_id_by_platform_id(team_id: int, public_ids: Collection[UUID]) -> dict[UUID, UUID]:
    """The public id of each named alert the platform owns, keyed by the platform's id."""
    return dict(
        _owned_with_public_ids(team_id, public_ids).annotate(public_id=_PUBLIC_ID).values_list("id", "public_id")
    )


def _platform_id_of(team_id: int, public_id: UUID) -> UUID | None:
    return _owned_with_public_ids(team_id, [public_id]).values_list("id", flat=True).first()


def history_by_public_id(
    *, team_id: int, public_ids: Collection[UUID], since: datetime, until: datetime
) -> dict[UUID, PlatformAlertHistory]:
    """The check history in `[since, until)` of each named alert the platform owns, keyed by its
    public id.

    One Postgres query finds the platform's ids and one ClickHouse query reads the history. An
    alert the platform does not own is left out, as in `runtime_by_public_id`.
    """
    if not public_ids:
        return {}
    public_by_platform_id = _public_id_by_platform_id(team_id, public_ids)
    histories = platform_alert_events.history(team_id, public_by_platform_id, since=since, until=until)
    return {public_by_platform_id[platform_id]: history for platform_id, history in histories.items()}


def last_check_by_public_id(*, team_id: int, public_ids: Collection[UUID]) -> dict[UUID, PlatformLastCheck]:
    """The newest check of each named alert the platform owns, keyed by its public id.

    An alert the platform does not own is left out, as in `runtime_by_public_id`.
    """
    if not public_ids:
        return {}
    public_by_platform_id = _public_id_by_platform_id(team_id, public_ids)
    checks = platform_alert_events.last_checks(team_id, public_by_platform_id)
    return {public_by_platform_id[platform_id]: check for platform_id, check in checks.items()}


def notable_checks_by_public_id(
    *, team_id: int, public_id: UUID, since: datetime, limit: int
) -> PlatformCheckEventPage | None:
    """The newest checks since `since` that moved the named alert's state or failed, or None when
    the platform does not own it."""
    platform_id = _platform_id_of(team_id, public_id)
    if platform_id is None:
        return None
    return platform_alert_events.notable_checks(team_id, platform_id, since=since, limit=limit)


def check_page_by_public_id(
    *, team_id: int, public_id: UUID, since: datetime, until: datetime, limit: int, offset: int
) -> PlatformCheckPage | None:
    """A page of the checks of one alert the platform owns, or None when the platform does not own it."""
    platform_id = _platform_id_of(team_id, public_id)
    if platform_id is None:
        return None
    return platform_alert_events.check_page(team_id, platform_id, since=since, until=until, limit=limit, offset=offset)


def checks_with_detail_by_public_id(
    *,
    team_id: int,
    public_ids: Collection[UUID],
    detail_paths: Sequence[Sequence[str]],
    since: datetime,
    limit: int,
) -> dict[UUID, tuple[PlatformCheckEntry, ...]]:
    """Each named alert's newest `limit` checks since `since` whose source detail holds every one of `detail_paths`,
    keyed by its public id.

    An alert the platform does not own is left out, as in `runtime_by_public_id`.
    """
    if not public_ids:
        return {}
    public_by_platform_id = _public_id_by_platform_id(team_id, public_ids)
    checks = platform_alert_events.checks_with_detail(
        team_id, public_by_platform_id, detail_paths=detail_paths, since=since, limit=limit
    )
    return {public_by_platform_id[platform_id]: entries for platform_id, entries in checks.items()}
