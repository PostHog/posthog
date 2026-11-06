"""Reads of the usage snapshots that the weekly scan writes."""

import dataclasses
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from django.conf import settings
from django.db import transaction
from django.utils import timezone

import posthoganalytics
from pydantic import TypeAdapter

from posthog.dataclasses import frozen
from posthog.models import Team, User

from ..facade.contracts import MetricUsage, UsageSnapshotDetail, UsageSnapshotPayload, UsageSnapshotSummary
from ..facade.enums import USAGE_FLAG_KEY, UsageSnapshotStatus
from ..models import UsageSnapshot

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


def latest_usage_snapshot(team_id: int) -> UsageSnapshotDetail | None:
    row = _latest_done(team_id)
    return _detail(row) if row else None


def metric_usage(team_id: int, metric_id: UUID) -> MetricUsage | None:
    """The metric's slice of the latest finished scan, or None when no scan has finished."""
    row = _latest_done(team_id)
    if row is None:
        return None
    payload = payload_from_json(row.payload)
    runs = next((counts for counts in payload.metric_runs or [] if counts.metric_id == metric_id), None)
    return MetricUsage(
        metric_id=metric_id,
        snapshot_id=row.id,
        window_start=row.window_start,
        window_end=row.window_end,
        computed_at=row.computed_at,
        runs=runs,
        adjusted_runs=[run for run in payload.adjusted_runs or [] if run.metric_id == metric_id],
    )


@frozen
class UsageWindow:
    start: datetime
    end: datetime


def usage_snapshot_window(team_id: int, snapshot_id: UUID) -> UsageWindow:
    row = UsageSnapshot.objects.for_team(team_id).only("window_start", "window_end").get(id=snapshot_id)
    return UsageWindow(start=row.window_start, end=row.window_end)


def read_payload(team_id: int, snapshot_id: UUID) -> UsageSnapshotPayload:
    return payload_from_json(UsageSnapshot.objects.for_team(team_id).only("payload").get(id=snapshot_id).payload)


def write_payload_sections(team_id: int, snapshot_id: UUID, **sections: Any) -> None:
    """Replace the named payload sections and keep every other section.

    The row lock makes a section write from one scan step safe against a concurrent write from
    another step on the same snapshot.
    """
    with transaction.atomic():
        row = UsageSnapshot.objects.for_team(team_id).select_for_update().get(id=snapshot_id)
        payload = dataclasses.replace(payload_from_json(row.payload), **sections)
        row.payload = payload_to_json(payload)
        row.save(update_fields=["payload"])


@frozen
class TopicDefinition:
    title: str
    description: str


def previous_topic_list(team_id: int, snapshot_id: UUID) -> list[TopicDefinition]:
    """The topics of the newest finished scan that has topics, other than this one."""
    topics = (
        UsageSnapshot.objects.for_team(team_id)
        .filter(status=UsageSnapshotStatus.DONE.value, payload__topics__0__isnull=False)
        .exclude(id=snapshot_id)
        .order_by("-computed_at")
        .values_list("payload__topics", flat=True)
        .first()
    )
    return [TopicDefinition(title=topic["title"], description=topic.get("description", "")) for topic in topics or []]


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
    status, error_message = _status_of(row)
    return UsageSnapshotDetail(
        id=row.id,
        status=status,
        error_message=error_message,
        window_start=row.window_start,
        window_end=row.window_end,
        judge_model=row.judge_model,
        computed_at=row.computed_at,
        created_at=row.created_at,
        payload=payload_from_json(row.payload),
    )
