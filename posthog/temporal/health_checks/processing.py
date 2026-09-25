import time

import structlog

from posthog.temporal.health_checks.alerts import emit_health_check_alert
from posthog.temporal.health_checks.db import resolve_stale_issues_with_deltas, upsert_issues_with_deltas
from posthog.temporal.health_checks.live_gate import partition_teams_by_posture
from posthog.temporal.health_checks.models import BatchDetectFn, BatchResult
from posthog.temporal.health_checks.registry import HEALTH_CHECKS, ensure_registry_loaded, get_detect_fn
from posthog.temporal.health_checks.signal_emitter import emit_health_check_signals
from posthog.temporal.health_checks.validation import _validate_batch_output

logger = structlog.get_logger(__name__)


def run_check_for_team(kind: str, team_id: int) -> BatchResult:
    """Run a registered check for one team with its configured dry-run default."""
    ensure_registry_loaded()
    return _process_batch_detection(
        team_ids=[team_id],
        kind=kind,
        detect_fn=get_detect_fn(kind),
        dry_run=HEALTH_CHECKS[kind].dry_run,
    )


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

    live_team_ids, dry_team_ids = partition_teams_by_posture(kind, team_ids, default_dry_run=dry_run)

    if dry_team_ids:
        dry_issues_by_team = {t: issues_by_team[t] for t in dry_team_ids if t in issues_by_team}
        logger.info(
            "dry run complete, skipping DB writes",
            kind=kind,
            teams_dry=len(dry_team_ids),
            teams_live=len(live_team_ids),
            teams_with_issues=len(dry_issues_by_team),
            issue_count=sum(len(v) for v in dry_issues_by_team.values()),
        )

    if not live_team_ids:
        return result

    live_ids = set(live_team_ids)
    # A dry team passed to resolution would lose its active issues and emit resolved alerts.
    live_issues_by_team = {t: results for t, results in issues_by_team.items() if t in live_ids}

    start = time.monotonic()
    newly_active = upsert_issues_with_deltas(kind, live_issues_by_team)
    result.issues_upserted = len(newly_active)
    result.db_write_duration = time.monotonic() - start

    healthy_team_ids = live_ids - set(live_issues_by_team.keys())

    start = time.monotonic()
    newly_resolved = resolve_stale_issues_with_deltas(kind, live_issues_by_team, healthy_team_ids)
    result.issues_resolved = len(newly_resolved)
    result.resolve_duration = time.monotonic() - start

    for issue in newly_active:
        emit_health_check_alert(issue, status="firing")
    emit_health_check_signals(newly_active)
    for issue in newly_resolved:
        emit_health_check_alert(issue, status="resolved")

    return result
