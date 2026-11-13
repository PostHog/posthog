"""Send catalog effectiveness results to PostHog's own project as events, so that staff can compare teams."""

import uuid
from datetime import datetime
from typing import Any
from uuid import UUID

from django.utils import timezone

from posthog.models import Team
from posthog.ph_client import ph_scoped_capture

from .effectiveness import DEFINITION_VERSION, AssetKind, SessionOutcome, TeamEffectiveness, TeamSkipped, trace_url

SESSION_OUTCOME_EVENT = "data catalog session outcome"
TEAM_MEASURED_EVENT = "data catalog effectiveness measured"

_CAPTURE_BATCH = 1000


def capture_effectiveness(result: TeamEffectiveness, team: Team) -> None:
    """Send the results of one run. A rerun can give a session another asset, and ClickHouse drops a repeated
    id only when it merges parts. So every event carries ``run_id``, and readers count only the latest run of
    each team and window. The team event goes last, so a run without one did not finish its delivery. The event
    ids hold the run id, so a rerun that stops partway cannot replace the rows of a finished run."""
    run_id = str(uuid.uuid4())
    distinct_id = _team_distinct_id(team)
    groups = _team_groups(team)
    shared = _shared_properties(team, result.window_start, result.window_end, run_id)
    # The SDK drops events once its queue is full, and that drop does not raise, so each batch flushes on its own.
    for start in range(0, len(result.rows), _CAPTURE_BATCH):
        with ph_scoped_capture(raise_on_error=True) as capture:
            for row in result.rows[start : start + _CAPTURE_BATCH]:
                capture(
                    SESSION_OUTCOME_EVENT,
                    distinct_id=distinct_id,
                    groups=groups,
                    timestamp=result.window_start,
                    uuid=_event_uuid(
                        run_id, team.id, result.window_start, row.session_id, row.asset_kind, row.metric_id
                    ),
                    properties={
                        **shared,
                        "session_id": row.session_id,
                        "client": row.client,
                        "source": row.source,
                        "outcome": row.outcome.value,
                        "asset_kind": row.asset_kind.value,
                        "is_headline": row.is_headline,
                        "metric_id": str(row.metric_id) if row.metric_id else None,
                        "metric_status": row.metric_status.value if row.metric_status else None,
                        "relation": row.relation.value if row.relation else None,
                        "missed_reason": row.missed_reason.value if row.missed_reason else None,
                        "metric_name": row.metric_name or None,
                        "session_started_at": row.started_at.isoformat() if row.started_at else None,
                        "is_example": row.is_example,
                        "trace_url": trace_url(row.session_id, result.telemetry_team_id),
                    },
                )
    counts = result.headline_counts
    with ph_scoped_capture(raise_on_error=True) as capture:
        capture(
            TEAM_MEASURED_EVENT,
            distinct_id=distinct_id,
            groups=groups,
            timestamp=result.window_start,
            uuid=_event_uuid(run_id, team.id, result.window_start, "team", AssetKind.NONE, None),
            properties={
                **shared,
                "measured_at": timezone.now().isoformat(),
                "sessions_read": result.sessions_read,
                "is_sample": result.is_sample,
                "chains_read": result.chains_read,
                "pieces_read": result.pieces_read,
                "stitch_failures": result.stitch_failures,
                "unread_sessions": result.unread_sessions,
                "analysis_sessions": result.analysis_sessions,
                "unchecked_queries": result.unchecked_queries,
                "unchecked_sessions": result.unchecked_sessions,
                # An outcome with no sessions still sends 0, so a sum across teams never meets a null.
                **{f"sessions_{outcome.value}": counts[outcome] for outcome in SessionOutcome},
            },
        )


def capture_team_skipped(skipped: TeamSkipped, team: Team, *, window_start: datetime, window_end: datetime) -> None:
    """Without this event, a skipped team looks the same as a team that never ran."""
    run_id = str(uuid.uuid4())
    with ph_scoped_capture(raise_on_error=True) as capture:
        capture(
            TEAM_MEASURED_EVENT,
            distinct_id=_team_distinct_id(team),
            groups=_team_groups(team),
            timestamp=window_start,
            uuid=_event_uuid(run_id, team.id, window_start, "team", AssetKind.NONE, None),
            properties={
                **_shared_properties(team, window_start, window_end, run_id),
                "measured_at": timezone.now().isoformat(),
                "skipped_reason": skipped.reason.value,
            },
        )


def _team_distinct_id(team: Team) -> str:
    return f"data_catalog_effectiveness_team_{team.id}"


def _team_groups(team: Team) -> dict[str, str]:
    return {"organization": str(team.organization_id), "project": str(team.uuid)}


def _shared_properties(team: Team, window_start: datetime, window_end: datetime, run_id: str) -> dict[str, Any]:
    return {
        "$process_person_profile": False,
        "team_id": team.id,
        "definition_version": DEFINITION_VERSION,
        "window_start": window_start.isoformat(),
        "window_end": window_end.isoformat(),
        "run_id": run_id,
    }


def _event_uuid(
    run_id: str, team_id: int, window_start: datetime, subject: str, asset_kind: AssetKind, metric_id: UUID | None
) -> str:
    """The same event sent twice in one run keeps one id, so ClickHouse drops the repeat."""
    name = f"{DEFINITION_VERSION}:{run_id}:{team_id}:{window_start.isoformat()}:{subject}:{asset_kind}:{metric_id}"
    return str(uuid.uuid5(uuid.NAMESPACE_URL, name))
