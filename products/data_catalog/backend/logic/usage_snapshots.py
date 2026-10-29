"""Reads of the usage snapshots that the weekly scan writes."""

import dataclasses
from datetime import datetime, timedelta
from typing import Any, TypedDict, Unpack
from uuid import UUID

from django.conf import settings
from django.db import transaction
from django.utils import timezone

import posthoganalytics
from pydantic import TypeAdapter
from rest_framework.exceptions import ValidationError

from posthog.hogql.database.schema.information_schema import references_denied_table

from posthog.dataclasses import frozen
from posthog.models import Team, User

from products.access_control.backend.facade.user_access_control import UserAccessControl

from ..facade.contracts import (
    AdjustedRun,
    MetricRunCounts,
    MetricUsage,
    TopicCluster,
    UncoveredGroup,
    UsageSnapshotDetail,
    UsageSnapshotPayload,
    UsageSnapshotSummary,
)
from ..facade.enums import USAGE_FLAG_KEY, UsageSnapshotStatus
from ..models import UsageSnapshot
from .metrics import _denied_tables, metrics_visible_to_user
from .validation import table_names_as_written

# A weekly scan writes one row a week, so this is a year of history.
USAGE_HISTORY_LIMIT = 52

SCAN_EXECUTION_TIMEOUT = timedelta(hours=12)
# A row still computing after the scan's execution timeout belongs to a scan that died.
STALE_COMPUTING = SCAN_EXECUTION_TIMEOUT + timedelta(hours=1)
SCAN_STOPPED_MESSAGE = "The scan stopped before it finished."

_PAYLOAD_ADAPTER = TypeAdapter(UsageSnapshotPayload)


def payload_to_json(payload: UsageSnapshotPayload) -> dict[str, Any]:
    return _PAYLOAD_ADAPTER.dump_python(payload, mode="json")


def payload_from_json(data: dict[str, Any]) -> UsageSnapshotPayload:
    return _PAYLOAD_ADAPTER.validate_python(data)


def usage_scans_supported() -> bool:
    """The scan reads MCP telemetry from PostHog's own project on US Cloud, so other deployments cannot scan."""
    return settings.CLOUD_DEPLOYMENT == "US" or settings.DEBUG or settings.TEST


def is_usage_enabled(user: User, team: Team) -> bool:
    return usage_scans_supported() and bool(
        posthoganalytics.feature_enabled(
            USAGE_FLAG_KEY,
            str(user.distinct_id),
            groups={"organization": str(team.organization_id), "project": str(team.uuid)},
            send_feature_flag_events=False,
        )
    )


def usage_snapshot_history(team_id: int) -> list[UsageSnapshotSummary]:
    rows = UsageSnapshot.objects.for_team(team_id).defer("payload").order_by("-created_at")[:USAGE_HISTORY_LIMIT]
    return [_summary(row) for row in rows]


@frozen
class UsageReader:
    """What one caller may see of a snapshot."""

    visible_metric_ids: frozenset[UUID]
    denied_tables: frozenset[str]


def usage_reader(team: Team, user: User, user_access_control: UserAccessControl) -> UsageReader:
    denied_tables = _denied_tables(team, user, user_access_control)
    return UsageReader(
        visible_metric_ids=frozenset(
            metrics_visible_to_user(team, user, user_access_control, denied_tables=denied_tables).values_list(
                "id", flat=True
            )
        ),
        denied_tables=frozenset(denied_tables),
    )


# A stored query that reaches this length was cut, and the part that was cut can name any table.
STORED_SQL_CHARS = 5000


def stored_sql_hidden(sql: str, denied_tables: frozenset[str], *, cut_at: int = STORED_SQL_CHARS) -> bool:
    """Whether a reader with denied tables must not see this stored query. A cut query counts as denied."""
    if not denied_tables:
        return False
    return len(sql) >= cut_at or sql_reads_denied_table(sql, denied_tables)


def sql_reads_denied_table(sql: str, denied_tables: frozenset[str]) -> bool:
    """Whether the SQL names a table the reader cannot read. SQL that does not parse counts as denied."""
    if not denied_tables:
        return False
    try:
        tables = table_names_as_written({"query": sql})
    except ValidationError:
        return True
    return references_denied_table(tables, set(denied_tables))


def visible_payload(payload: UsageSnapshotPayload, reader: UsageReader) -> UsageSnapshotPayload:
    """The payload without rows that would show a hidden metric or SQL over a denied table.

    The scan runs as the system, so it stores what every member of the team computed. Each read
    filters that down to what the reader may see.
    """
    return dataclasses.replace(
        payload,
        metric_runs=None
        if payload.metric_runs is None
        else [counts for counts in payload.metric_runs if counts.metric_id in reader.visible_metric_ids],
        adjusted_runs=None
        if payload.adjusted_runs is None
        else [
            run
            for run in payload.adjusted_runs
            if run.metric_id in reader.visible_metric_ids and not stored_sql_hidden(run.sql, reader.denied_tables)
        ],
    )


def latest_usage_snapshot(team_id: int, reader: UsageReader) -> UsageSnapshotDetail | None:
    row = _latest_done(team_id)
    if row is None:
        return None
    detail = _detail(row)
    return dataclasses.replace(detail, payload=visible_payload(detail.payload, reader))


def metric_usage(team_id: int, metric_id: UUID, reader: UsageReader) -> MetricUsage | None:
    """The metric's slice of the latest finished scan, or None when no scan has finished.

    A finished scan that counted no run of the metric gives a MetricUsage whose ``runs`` is None.
    """
    row = _latest_done(team_id)
    if row is None:
        return None
    stored = payload_from_json(row.payload)
    # Select the metric's rows first, so the visibility check parses only this metric's SQL.
    payload = visible_payload(
        dataclasses.replace(
            stored,
            metric_runs=None
            if stored.metric_runs is None
            else [counts for counts in stored.metric_runs if counts.metric_id == metric_id],
            adjusted_runs=None
            if stored.adjusted_runs is None
            else [run for run in stored.adjusted_runs if run.metric_id == metric_id],
        ),
        reader,
    )
    runs = next(iter(payload.metric_runs or []), None)
    return MetricUsage(
        metric_id=metric_id,
        snapshot_id=row.id,
        window_start=row.window_start,
        window_end=row.window_end,
        computed_at=row.computed_at,
        runs=runs,
        adjusted_runs=list(payload.adjusted_runs or []),
    )


@frozen
class UsageWindow:
    start: datetime
    end: datetime


def usage_snapshot_window(team_id: int, snapshot_id: UUID) -> UsageWindow:
    row = UsageSnapshot.objects.for_team(team_id).only("window_start", "window_end").get(id=snapshot_id)
    return UsageWindow(start=row.window_start, end=row.window_end)


class PayloadSections(TypedDict, total=False):
    """The sections a scan step can write. Each key must match a ``UsageSnapshotPayload`` field."""

    metric_runs: list[MetricRunCounts]
    adjusted_runs: list[AdjustedRun]
    topics: list[TopicCluster]
    uncovered: list[UncoveredGroup]


def write_payload_sections(team_id: int, snapshot_id: UUID, **sections: Unpack[PayloadSections]) -> None:
    """Replace the named payload sections and keep every other section.

    The row lock makes a section write from one scan step safe against a concurrent write from
    another step on the same snapshot.
    """
    with transaction.atomic():
        row = UsageSnapshot.objects.for_team(team_id).select_for_update().get(id=snapshot_id)
        payload = dataclasses.replace(payload_from_json(row.payload), **sections)
        row.payload = payload_to_json(payload)
        row.save(update_fields=["payload"])


def _latest_done(team_id: int) -> UsageSnapshot | None:
    return (
        UsageSnapshot.objects.for_team(team_id)
        .filter(status=UsageSnapshotStatus.DONE.value)
        .order_by("-computed_at")
        .first()
    )


def is_stale(row: UsageSnapshot) -> bool:
    return row.status == UsageSnapshotStatus.COMPUTING.value and row.created_at <= timezone.now() - STALE_COMPUTING


def _status_of(row: UsageSnapshot) -> tuple[UsageSnapshotStatus, str]:
    # A dead scan never closes its row, so the read reports it as failed instead of computing forever.
    if is_stale(row):
        return UsageSnapshotStatus.ERROR, SCAN_STOPPED_MESSAGE
    return UsageSnapshotStatus(row.status), row.error_message


def _summary(row: UsageSnapshot) -> UsageSnapshotSummary:
    status, error_message = _status_of(row)
    return UsageSnapshotSummary(
        id=row.id,
        status=status,
        error_message=error_message,
        window_start=row.window_start,
        window_end=row.window_end,
        judge_model=row.judge_model,
        computed_at=row.computed_at,
        created_at=row.created_at,
    )


def _detail(row: UsageSnapshot) -> UsageSnapshotDetail:
    return UsageSnapshotDetail(**dataclasses.asdict(_summary(row)), payload=payload_from_json(row.payload))
