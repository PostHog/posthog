"""Copies a source's own alert history into the platform's history, so it outlives the source's rows.

A copied row is keyed by the source row's id (`legacy_evaluation_key`), which is what makes the copy
safe to rerun: a run first reads which keys the platform already holds and copies only the rest. A
retry of one insert is dropped by the replicated engine's deduplication token, as for any batch.

From the platform's oldest row of a kind it records itself on, the source's rows of that kind are
second copies of the platform's, and readers already hide them, so they are not copied. A copy then
moves that oldest row back, and the readers hide every source row from there on. So one alert's rows
are inserted a month at a time, newest first: a run that stops part way leaves the copied rows
contiguous with the platform's own, and the source rows it has not reached yet still show.
"""

from collections.abc import Callable, Collection, Iterable, Sequence
from dataclasses import replace
from datetime import UTC, datetime
from itertools import groupby
from typing import Final
from uuid import UUID

import structlog

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.connection import ClickHouseUser
from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.clickhouse.workload import Workload
from posthog.dataclasses import frozen

from products.alerts_platform.backend.facade.contracts import (
    AlertEventKind,
    ControlChangeKind,
    LegacyAlertHistory,
    LegacyAlertHistoryCopy,
    LegacyHistoryCopy,
    LegacyHistoryCopyRun,
    LegacyHistoryEntry,
)
from products.alerts_platform.backend.facade.enums import PlatformAlertOwner
from products.alerts_platform.backend.logic.platform_alert_events import (
    CHECKS_ONLY,
    CONFIGURATION_ROW_ALERT_ID,
    LEGACY_KEY_PREFIX,
    PlatformAlertEventRow,
    insert_backfilled_events,
)
from products.alerts_platform.backend.logic.platform_lifecycle import event_row
from products.alerts_platform.backend.models import PlatformAlert, PlatformAlertConfiguration
from products.alerts_platform.backend.models.platform_alert_events_sql import PLATFORM_ALERT_EVENTS_TABLE

logger = structlog.get_logger(__name__)

_PLATFORM_CONTROL_KINDS: Final = tuple(kind.value for kind in ControlChangeKind if kind.recorded_by_platform)

_COPY_STATE_SQL = f"""
SELECT groupUniqArrayIf(evaluation_key, startsWith(evaluation_key, %(prefix)s)),
       minIf(occurred_at, is_control AND NOT is_copy),
       countIf(is_control AND NOT is_copy),
       minIf(occurred_at, is_check AND NOT is_copy),
       countIf(is_check AND NOT is_copy)
FROM (
    SELECT evaluation_key,
           occurred_at,
           startsWith(evaluation_key, %(prefix)s) AS is_copy,
           kind IN %(control_kinds)s AND alert_id = %(configuration_row)s AS is_control,
           {CHECKS_ONLY} AS is_check
    FROM {PLATFORM_ALERT_EVENTS_TABLE}
    WHERE team_id = %(team_id)s
      AND configuration_id = %(configuration_id)s
)
"""


def legacy_evaluation_key(legacy_id: UUID) -> str:
    """The evaluation key of a copied row. Its own prefix, so it never shares a key, and with it an
    insert's deduplication token, with a row the platform recorded."""
    return f"{LEGACY_KEY_PREFIX}{legacy_id}"


@frozen
class _CopyState:
    copied_keys: frozenset[str]
    oldest_control_at: datetime | None
    oldest_check_at: datetime | None


def _copy_state(configuration: PlatformAlertConfiguration) -> _CopyState:
    tag_queries(product=Product.PLATFORM_AND_SUPPORT, feature=Feature.ALERTING)
    [(copied, oldest_control, controls, oldest_check, checks)] = sync_execute(
        _COPY_STATE_SQL,
        {
            "team_id": configuration.team_id,
            "configuration_id": configuration.id,
            "prefix": LEGACY_KEY_PREFIX,
            "configuration_row": CONFIGURATION_ROW_ALERT_ID,
            "control_kinds": list(_PLATFORM_CONTROL_KINDS),
        },
        team_id=configuration.team_id,
        workload=Workload.OFFLINE,  # a backfill command, no person waits for it
        ch_user=ClickHouseUser.ALERTS_PLATFORM,
    )
    return _CopyState(
        copied_keys=frozenset(copied),
        oldest_control_at=oldest_control if controls else None,
        oldest_check_at=oldest_check if checks else None,
    )


def _covered(entry: LegacyHistoryEntry, state: _CopyState, *, platform_checks_replace_source: bool) -> bool:
    if isinstance(entry.kind, ControlChangeKind):
        if not entry.kind.recorded_by_platform:
            return False
        oldest = state.oldest_control_at
    elif not platform_checks_replace_source:
        return False
    else:
        oldest = state.oldest_check_at
    return oldest is not None and entry.occurred_at >= oldest


def copy_team_histories(
    *,
    team_ids: Collection[int],
    alert_ids: Callable[[int], Iterable[UUID]],
    legacy_history: Callable[[int, UUID], LegacyAlertHistory],
    apply: bool,
) -> LegacyHistoryCopyRun:
    """Copies the history of every alert `alert_ids` names, team by team, an alert at a time.

    A team that fails is logged and left for a rerun, which copies only what is still missing.
    """
    alerts: list[LegacyAlertHistoryCopy] = []
    failed: list[int] = []
    for team_id in team_ids:
        try:
            for alert_id in alert_ids(team_id):
                history = legacy_history(team_id, alert_id)
                result = copy_legacy_history_by_public_id(
                    team_id=team_id,
                    public_id=alert_id,
                    entries=history.entries,
                    apply=apply,
                    platform_checks_replace_source=history.platform_checks_replace_source,
                )
                if result is None:
                    continue
                alert = LegacyAlertHistoryCopy(
                    team_id=team_id, alert_id=alert_id, copy=result, left_out=dict(history.left_out)
                )
                logger.info(
                    "legacy_alert_history_copy.alert",
                    team_id=team_id,
                    alert_id=str(alert_id),
                    applied=apply,
                    legacy=result.legacy,
                    already_copied=result.already_copied,
                    covered=result.covered,
                    to_copy=result.to_copy,
                    copied=result.copied,
                    left_out=history.left_out,
                )
                alerts.append(alert)
        except Exception:
            logger.exception("legacy_alert_history_copy.failed", team_id=team_id)
            failed.append(team_id)
    return LegacyHistoryCopyRun(alerts=tuple(alerts), failed_team_ids=tuple(failed))


def copy_legacy_history_by_public_id(
    *,
    team_id: int,
    public_id: UUID,
    entries: Sequence[LegacyHistoryEntry],
    apply: bool,
    platform_checks_replace_source: bool = True,
) -> LegacyHistoryCopy | None:
    configuration = (
        PlatformAlertConfiguration.objects.for_team(team_id)
        .filter(PlatformAlertConfiguration.with_destination_alert_ids([public_id]), owner=PlatformAlertOwner.PLATFORM)
        .first()
    )
    if configuration is None:
        return None
    return copy_legacy_history(
        configuration, entries, apply=apply, platform_checks_replace_source=platform_checks_replace_source
    )


def copy_legacy_history(
    configuration: PlatformAlertConfiguration,
    entries: Sequence[LegacyHistoryEntry],
    *,
    apply: bool,
    platform_checks_replace_source: bool = True,
) -> LegacyHistoryCopy:
    """Copies the entries the platform holds neither as a copy nor as its own row into its history.

    Writes nothing unless `apply`. Raises when ClickHouse fails, so a caller stops rather than
    reporting a copy that did not land.
    """
    state = _copy_state(configuration)
    already_copied = covered = 0
    pending: list[LegacyHistoryEntry] = []
    for entry in entries:
        if legacy_evaluation_key(entry.legacy_id) in state.copied_keys:
            already_copied += 1
        elif _covered(entry, state, platform_checks_replace_source=platform_checks_replace_source):
            covered += 1
        else:
            pending.append(entry)
    copied = _insert(configuration, pending) if apply and pending else 0
    return LegacyHistoryCopy(
        configuration_id=configuration.id,
        legacy=len(entries),
        already_copied=already_copied,
        covered=covered,
        to_copy=len(pending),
        copied=copied,
    )


def _insert(configuration: PlatformAlertConfiguration, entries: Sequence[LegacyHistoryEntry]) -> int:
    instance = (
        PlatformAlert.objects.for_team(configuration.team_id)
        .filter(configuration=configuration, grouping_key="")
        .first()
    )
    rows = sorted(
        (_row(configuration, entry, instance) for entry in entries), key=lambda row: row.occurred_at, reverse=True
    )
    # One insert per month, the table's partition, so each lands as one part, whole or not at all.
    for _, month in groupby(rows, key=lambda row: row.occurred_at.astimezone(UTC).strftime("%Y%m")):
        insert_backfilled_events(configuration.team_id, list(month))
    return len(rows)


def _row(
    configuration: PlatformAlertConfiguration, entry: LegacyHistoryEntry, instance: PlatformAlert | None
) -> PlatformAlertEventRow:
    is_check = entry.kind == AlertEventKind.CHECK
    row = event_row(
        configuration,
        alert=instance if is_check else None,
        evaluation_key=legacy_evaluation_key(entry.legacy_id),
        kind=entry.kind.value,
        previous_state=entry.previous_state.value,
        state=entry.state.value,
        # No firing start, so delivery never reads a copy as the opening of a firing it resolves.
        episode_started_at=None,
        consecutive_failures=0,
        now=entry.occurred_at,
        value=entry.value,
        query_duration_ms=entry.query_duration_ms,
        error_message=entry.error_message,
        source_detail=entry.source_detail,
    )
    # The source kept no snapshot of what it checked against, so the copy states none rather than
    # today's settings, which a reader would take for the ones the check ran under.
    return replace(row, condition_snapshot={}, source_config_snapshot={})
