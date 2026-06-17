import time

import structlog

from posthog.temporal.health_checks.alerts import emit_health_check_alert
from posthog.temporal.health_checks.db import resolve_stale_issues_with_deltas, upsert_issues_with_deltas
from posthog.temporal.health_checks.models import BatchDetectFn, BatchResult
from posthog.temporal.health_checks.signal_emitter import emit_health_check_signals
from posthog.temporal.health_checks.validation import _validate_batch_output

logger = structlog.get_logger(__name__)


def _process_batch_detection(
    team_ids: list[int],
    kind: str,
    detect_fn: BatchDetectFn,
    *,
    dry_run: bool = False,
) -> BatchResult:
    result = BatchResult(batch_size=len(team_ids))

    start = time.monotonic()
    issues_by_team = detect_fn(team_ids)
    result.detect_duration = time.monotonic() - start

    issues_by_team, teams_dropped = _validate_batch_output(issues_by_team, set(team_ids), kind)

    result.teams_skipped = teams_dropped
    result.teams_with_issues = len(issues_by_team)
    result.teams_healthy = len(team_ids) - len(issues_by_team) - teams_dropped

    if dry_run:
        issue_count = sum(len(v) for v in issues_by_team.values())
        logger.info(
            "dry run complete, skipping DB writes",
            kind=kind,
            teams_with_issues=result.teams_with_issues,
            issue_count=issue_count,
            teams_healthy=result.teams_healthy,
        )
        return result

    start = time.monotonic()
    newly_active = upsert_issues_with_deltas(kind, issues_by_team)
    result.issues_upserted = len(newly_active)
    result.db_write_duration = time.monotonic() - start

    healthy_team_ids = set(team_ids) - set(issues_by_team.keys())

    start = time.monotonic()
    newly_resolved = resolve_stale_issues_with_deltas(kind, issues_by_team, healthy_team_ids)
    result.issues_resolved = len(newly_resolved)
    result.resolve_duration = time.monotonic() - start

    for issue in newly_active:
        emit_health_check_alert(issue, status="firing")
    emit_health_check_signals(newly_active)
    for issue in newly_resolved:
        emit_health_check_alert(issue, status="resolved")

    return result
