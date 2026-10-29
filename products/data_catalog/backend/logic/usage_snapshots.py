"""Reads of the usage snapshots that the weekly scan writes."""

from collections import Counter
from collections.abc import Iterable
from typing import Any
from uuid import UUID

import posthoganalytics
from pydantic import TypeAdapter

from posthog.models import Team, User

from ..facade.contracts import (
    AdjustedRun,
    FetchOutcomeCounts,
    MetricUsage,
    UsageSnapshotDetail,
    UsageSnapshotPayload,
    UsageSnapshotSummary,
)
from ..facade.enums import USAGE_FLAG_KEY, FetchOutcome, UsageSnapshotStatus
from ..models import UsageSnapshot

# A weekly scan writes one row a week, so this is a year of history.
USAGE_HISTORY_LIMIT = 52

_PAYLOAD_ADAPTER = TypeAdapter(UsageSnapshotPayload)


def payload_to_json(payload: UsageSnapshotPayload) -> dict[str, Any]:
    return _PAYLOAD_ADAPTER.dump_python(payload, mode="json")


def payload_from_json(data: dict[str, Any]) -> UsageSnapshotPayload:
    return _PAYLOAD_ADAPTER.validate_python(data)


def is_usage_enabled(user: User, team: Team) -> bool:
    return bool(
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


def get_usage_snapshot(team_id: int, snapshot_id: UUID) -> UsageSnapshotDetail | None:
    row = UsageSnapshot.objects.for_team(team_id).filter(id=snapshot_id).first()
    return _detail(row) if row else None


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
    adjusted = [run for run in payload.adjusted_runs or [] if run.metric_id == metric_id]
    return MetricUsage(
        metric_id=metric_id,
        snapshot_id=row.id,
        window_start=row.window_start,
        window_end=row.window_end,
        computed_at=row.computed_at,
        runs=runs,
        adjusted=_count_outcomes(run for run in adjusted if not run.is_scout),
        scout_adjusted=_count_outcomes(run for run in adjusted if run.is_scout),
        adjusted_runs=adjusted,
    )


def _count_outcomes(runs: Iterable[AdjustedRun]) -> FetchOutcomeCounts:
    outcomes = Counter(run.fetch_outcome for run in runs)
    return FetchOutcomeCounts(
        adapted=outcomes[FetchOutcome.ADAPTED],
        missed=outcomes[FetchOutcome.MISSED],
        silent=outcomes[FetchOutcome.SILENT],
    )


def _latest_done(team_id: int) -> UsageSnapshot | None:
    return (
        UsageSnapshot.objects.for_team(team_id)
        .filter(status=UsageSnapshotStatus.DONE.value)
        .order_by("-computed_at")
        .first()
    )


def _summary(row: UsageSnapshot) -> UsageSnapshotSummary:
    return UsageSnapshotSummary(
        id=row.id,
        status=UsageSnapshotStatus(row.status),
        error_message=row.error_message,
        window_start=row.window_start,
        window_end=row.window_end,
        judge_model=row.judge_model,
        computed_at=row.computed_at,
        created_at=row.created_at,
    )


def _detail(row: UsageSnapshot) -> UsageSnapshotDetail:
    return UsageSnapshotDetail(
        id=row.id,
        status=UsageSnapshotStatus(row.status),
        error_message=row.error_message,
        window_start=row.window_start,
        window_end=row.window_end,
        judge_model=row.judge_model,
        computed_at=row.computed_at,
        created_at=row.created_at,
        payload=payload_from_json(row.payload),
    )
