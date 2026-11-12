"""Reads of the shared alert tables, as a consumer outside this product sees them.

Separate from `platform_lifecycle`, which serves the source adapters. These serve a reader
outside the product, so they return views rather than rows and never change one.
"""

import operator
from collections.abc import Callable, Collection, Mapping, Sequence
from datetime import datetime
from functools import reduce
from typing import Any
from uuid import UUID

from django.db.models import Case, Exists, Max, OuterRef, Prefetch, Q, QuerySet, Subquery, Value, When
from django.db.models.functions import Coalesce

from posthog.helpers.trigram_search import NAME_FIELD, apply_trigram_search

from products.alerts_platform.backend.facade.contracts import (
    ControlChangeKind,
    EnabledNativeConfiguration,
    Grouping,
    InstanceCheckState,
    NativeConfigurationMatch,
    PlatformAlertConfigurationPage,
    PlatformAlertConfigurationView,
    PlatformAlertEvents,
    PlatformAlertHistory,
    PlatformAlertListHistory,
    PlatformAlertRuntime,
    PlatformAlertSnapshot,
    PlatformCheckEntry,
    PlatformCheckEventPage,
    PlatformCheckPage,
    PlatformControlChangePage,
    PlatformControlHistory,
    PlatformLastCheck,
)
from products.alerts_platform.backend.facade.enums import (
    PlatformAlertCheckStatus,
    PlatformAlertOwner,
    PlatformAlertState,
)
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
        created_by_id=configuration.created_by_id,
        first_enabled_at=configuration.first_enabled_at,
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
    created_by_uuid: UUID | None = None,
) -> PlatformAlertConfigurationPage:
    """One page of configurations, newest first, with the total behind it. With a
    `legacy_configuration_id`, only the copy of that source row. With `configuration_ids`, only those.
    With `created_by_uuid`, only the ones that user created.

    The page is taken in the database rather than in the caller, so a team with many alerts
    costs one page rather than all of them. Slicing keeps the prefetch, which resolves over the
    page's rows alone.
    """
    readable = _readable(team_id, source_kinds)
    if legacy_configuration_id is not None:
        readable = readable.filter(legacy_configuration_id=legacy_configuration_id)
    if configuration_ids is not None:
        readable = readable.filter(id__in=list(configuration_ids))
    if created_by_uuid is not None:
        readable = readable.filter(created_by__uuid=created_by_uuid)
    return PlatformAlertConfigurationPage(
        configurations=tuple(_configuration_view(row) for row in readable[offset : offset + limit]),
        total=readable.count(),
    )


def owned_copies_by_legacy_id(
    *, team_id: int, source_kind: str, legacy_configuration_ids: Collection[UUID]
) -> dict[UUID, PlatformAlertConfigurationView]:
    """The copies of the named source rows that the platform owns, by source row id, with their settings
    and no instances (`alerts` is empty). A row with no such copy is left out."""
    if not legacy_configuration_ids:
        return {}
    copies = (
        PlatformAlertConfiguration.objects.for_team(team_id, canonical=True)
        .filter(
            source_kind=source_kind,
            legacy_configuration_id__in=list(legacy_configuration_ids),
            owner=PlatformAlertOwner.PLATFORM,
        )
        .prefetch_related(Prefetch("alerts", queryset=PlatformAlert.objects.unscoped().none()))
    )
    return {
        legacy_id: _configuration_view(copy)
        for copy in copies
        if (legacy_id := copy.legacy_configuration_id) is not None
    }


def native_configuration_keys(
    *, team_id: int, source_kind: str, created_by_uuid: UUID | None = None
) -> tuple[tuple[datetime, UUID], ...]:
    """`(created_at, id)` of every configuration of a kind with no source row, newest first, without
    loading the rest of each row. With `created_by_uuid`, only the ones that user created."""
    rows = PlatformAlertConfiguration.objects.for_team(team_id, canonical=True).filter(
        source_kind=source_kind, legacy_configuration_id__isnull=True
    )
    if created_by_uuid is not None:
        rows = rows.filter(created_by__uuid=created_by_uuid)
    return tuple(rows.order_by("-created_at", "-id").values_list("created_at", "id"))


def native_configuration_matches(
    *, team_id: int, source_kind: str, search: str | None = None
) -> tuple[NativeConfigurationMatch, ...]:
    """Every configuration of a kind with no source row, or with `search` only the ones whose name
    matches it, both tiers included. A source decides the tiers across its own rows and these."""
    rows = PlatformAlertConfiguration.objects.for_team(team_id, canonical=True).filter(
        source_kind=source_kind, legacy_configuration_id__isnull=True
    )
    if not search:
        return tuple(
            NativeConfigurationMatch(
                id=row_id, created_at=created_at, created_by_id=created_by_id, source_config=source_config
            )
            for row_id, created_at, created_by_id, source_config in rows.values_list(
                "id", "created_at", "created_by_id", "source_config"
            )
        )
    searched = apply_trigram_search(rows, search, span_prefix="platform_alert.search", fields=(NAME_FIELD,))
    return tuple(
        NativeConfigurationMatch(
            id=row_id,
            created_at=created_at,
            created_by_id=created_by_id,
            source_config=source_config,
            is_exact=bool(is_exact),
            search_score=score,
        )
        for row_id, created_at, created_by_id, source_config, is_exact, score in searched.values_list(
            "id", "created_at", "created_by_id", "source_config", "_is_exact", "_search_score"
        )
    )


def _unmuted_at(at: datetime) -> Q:
    return Q(snooze_until__isnull=True) | Q(snooze_until__lte=at)


def enabled_native_configurations(
    *,
    team_ids: Collection[int],
    source_kind: str,
    created_by_id: int | None = None,
    source_config_key: str | None = None,
    values: Collection[Any] = (),
    limit: int | None = None,
    firing_at: datetime | None = None,
    errored_at: datetime | None = None,
    owned_copies: bool = False,
) -> tuple[EnabledNativeConfiguration, ...]:
    """The enabled configurations of a kind with no source row in these teams, and with `owned_copies`
    also the copies the platform owns, newest first. With
    `created_by_id`, only the ones that user created. With `source_config_key`, only the ones whose
    `source_config[key]` is one of `values`. With `limit`, at most that many. With `firing_at`, only
    the ones a reader sees firing then: a group fires, the last check succeeded, and no mute holds. With
    `errored_at`, only the ones a reader sees errored then: the last check failed, and no mute holds."""
    if not team_ids or (source_config_key is not None and not values):
        return ()
    # The caller names the teams, as a source's readers of its own rows across teams do.
    native = Q(legacy_configuration_id__isnull=True)
    rows = PlatformAlertConfiguration.objects.unscoped().filter(
        native | Q(owner=PlatformAlertOwner.PLATFORM) if owned_copies else native,
        team_id__in=list(team_ids),
        source_kind=source_kind,
        enabled=True,
    )
    if created_by_id is not None:
        rows = rows.filter(created_by_id=created_by_id)
    if source_config_key is not None:
        rows = rows.filter(_source_config_in(source_config_key, values))
    if firing_at is not None:
        # The composition `runtime_by_public_id` shows: a failed check status replaces the state.
        firing = PlatformAlert.objects.unscoped().filter(configuration=OuterRef("pk"), state=PlatformAlertState.FIRING)
        rows = rows.filter(Exists(firing), _unmuted_at(firing_at), check_status=PlatformAlertCheckStatus.OK)
    if errored_at is not None:
        rows = rows.filter(_unmuted_at(errored_at)).exclude(check_status=PlatformAlertCheckStatus.OK)
    ordered = rows.order_by("-created_at", "-id").values_list(
        "id", "team_id", "name", "created_at", "created_by_id", "source_config", "legacy_configuration_id"
    )
    return tuple(
        EnabledNativeConfiguration(
            id=row_id,
            team_id=team_id,
            name=name,
            created_at=created_at,
            created_by_id=row_created_by_id,
            source_config=source_config,
            legacy_configuration_id=legacy_configuration_id,
        )
        for row_id, team_id, name, created_at, row_created_by_id, source_config, legacy_configuration_id in (
            ordered if limit is None else ordered[:limit]
        )
    )


def native_source_config_values(
    *, team_ids: Collection[int], source_kind: str, source_config_key: str, values: Collection[Any]
) -> set[Any]:
    """Which of `values` a configuration of a kind with no source row in these teams holds as
    `source_config[key]`, enabled or not."""
    if not team_ids or not values:
        return set()
    # The caller names the teams, as a source's readers of its own rows across teams do.
    configs = (
        PlatformAlertConfiguration.objects.unscoped()
        .filter(team_id__in=list(team_ids), source_kind=source_kind, legacy_configuration_id__isnull=True)
        .filter(_source_config_in(source_config_key, values))
        .values_list("source_config", flat=True)
    )
    wanted = set(values)
    return {value for config in configs if (value := config.get(source_config_key)) in wanted}


def native_configuration_ids_by_source_config(
    *, team_id: int, source_kind: str, source_config_key: str, values: Collection[Any]
) -> dict[Any, list[UUID]]:
    """The configurations of a kind with no source row in the team, by which of `values` each holds as
    `source_config[key]`, enabled or not. A value no configuration holds is left out."""
    if not values:
        return {}
    # The caller names the team, as `native_source_config_values` takes its teams.
    configs = (
        PlatformAlertConfiguration.objects.unscoped()
        .filter(team_id=team_id, source_kind=source_kind, legacy_configuration_id__isnull=True)
        .filter(_source_config_in(source_config_key, values))
        .order_by("created_at", "id")
        .values_list("id", "source_config")
    )
    wanted = set(values)
    by_value: dict[Any, list[UUID]] = {}
    for configuration_id, config in configs:
        if (value := config.get(source_config_key)) in wanted:
            by_value.setdefault(value, []).append(configuration_id)
    return by_value


def _source_config_in(key: str, values: Collection[Any]) -> Q:
    return reduce(operator.or_, (Q(source_config__contains={key: value}) for value in values))


def native_configuration_team_id(*, configuration_id: UUID, source_kind: str) -> int | None:
    """The team of a configuration of a kind with no source row, or None when there is none. For a
    caller with no team yet, such as a click on a button in a message, which then checks access
    against the team this returns."""
    unscoped = PlatformAlertConfiguration.objects.unscoped()
    # nosemgrep: idor-lookup-without-team — resolves the team only; the caller authorizes against it
    rows = unscoped.filter(id=configuration_id, source_kind=source_kind, legacy_configuration_id__isnull=True)
    return rows.values_list("team_id", flat=True).first()


def owned_configuration_ids_without_source_rows(
    *,
    team_id: int,
    source_kind: str,
    source_config_key: str,
    values: Collection[Any],
    existing_source_ids: Callable[[Collection[UUID]], Collection[UUID]],
) -> tuple[UUID, ...]:
    """Ids of the team's configurations of a kind the platform owns whose `source_config[key]` is one
    of `values` and that have no source row: the ones that never had one, and copies whose row
    `existing_source_ids` does not return."""
    found = list(
        PlatformAlertConfiguration.objects.for_team(team_id, canonical=True)
        .filter(
            source_kind=source_kind,
            owner=PlatformAlertOwner.PLATFORM,
            **{f"source_config__{source_config_key}__in": list(values)},
        )
        .values_list("id", "legacy_configuration_id")
    )
    existing = set(existing_source_ids([legacy_id for _, legacy_id in found if legacy_id is not None]))
    return tuple(configuration_id for configuration_id, legacy_id in found if legacy_id not in existing)


def count_configurations(
    *,
    team_id: int,
    source_kind: str,
    native_only: bool = False,
    enabled_only: bool = False,
    check_interval_minutes: int | None = None,
    exclude_id: UUID | None = None,
    source_config_contains: Mapping[str, Any] | None = None,
) -> int:
    """How many alerts of a kind a team has on the platform, whoever owns them. With `native_only`, only
    the ones with no source row. With `exclude_id`, the alert an edit is checked for is left out. With
    `source_config_contains`, only the ones whose `source_config` holds that object."""
    configurations = PlatformAlertConfiguration.objects.for_team(team_id, canonical=True).filter(
        source_kind=source_kind
    )
    if exclude_id is not None:
        configurations = configurations.exclude(id=exclude_id)
    if source_config_contains:
        configurations = configurations.filter(source_config__contains=source_config_contains)
    if native_only:
        configurations = configurations.filter(legacy_configuration_id__isnull=True)
    if enabled_only:
        configurations = configurations.filter(enabled=True)
    if check_interval_minutes is not None:
        configurations = configurations.filter(check_interval_minutes=check_interval_minutes)
    return configurations.count()


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
            "labels",
            "annotations",
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
            labels=labels,
            annotations=annotations,
        )
        for public_id, state, check_status, last_notified_at, consecutive_failures, next_check_at, grouping, labels, annotations in rows
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


def control_changes_by_public_id(
    *, team_id: int, public_id: UUID, kinds: Collection[ControlChangeKind], limit: int
) -> PlatformControlChangePage | None:
    """The newest control-plane changes of the named alert, or None when the platform does not own it."""
    platform_id = _platform_id_of(team_id, public_id)
    if platform_id is None:
        return None
    return platform_alert_events.control_changes(team_id, platform_id, kinds=kinds, limit=limit)


def alert_list_history(
    *, team_id: int, configuration_ids: Collection[UUID], since: datetime, until: datetime
) -> PlatformAlertListHistory:
    """What an alert list shows of each configuration's checks, keyed by configuration id: its newest
    check, its state changes in `[since, until)` across every group, and its control-plane changes."""
    return PlatformAlertListHistory(
        last_checks=platform_alert_events.last_checks(team_id, configuration_ids, all_groups=True),
        histories=platform_alert_events.history(team_id, configuration_ids, since=since, until=until, all_groups=True),
        controls=platform_alert_events.control_history(team_id, configuration_ids, since=since, until=until),
    )


def alert_events(*, team_id: int, configuration_id: UUID, since: datetime, limit: int) -> PlatformAlertEvents:
    """A configuration's checks across every group that moved its state or failed since `since`, and
    its control-plane changes since then, each newest first."""
    return PlatformAlertEvents(
        checks=platform_alert_events.notable_checks(
            team_id, configuration_id, since=since, limit=limit, all_groups=True
        ),
        changes=platform_alert_events.control_changes(
            team_id, configuration_id, kinds=tuple(ControlChangeKind), limit=limit, since=since
        ),
    )


def control_history_by_public_id(
    *, team_id: int, public_ids: Collection[UUID], since: datetime, until: datetime
) -> dict[UUID, PlatformControlHistory]:
    """The control-plane changes in `[since, until)` of each named alert the platform owns, keyed by
    its public id. An alert the platform does not own is left out, as in `runtime_by_public_id`."""
    if not public_ids:
        return {}
    public_by_platform_id = _public_id_by_platform_id(team_id, public_ids)
    histories = platform_alert_events.control_history(team_id, public_by_platform_id, since=since, until=until)
    return {public_by_platform_id[platform_id]: history for platform_id, history in histories.items()}


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
