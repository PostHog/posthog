import time

import structlog

from posthog.temporal.health_checks.alerts import emit_health_check_alert
from posthog.temporal.health_checks.db import resolve_stale_issues_with_deltas, upsert_issues_with_deltas
from posthog.temporal.health_checks.live_gate import live_team_ids
from posthog.temporal.health_checks.models import BatchDetectFn, BatchResult
from posthog.temporal.health_checks.registry import HEALTH_CHECKS, ensure_registry_loaded, get_detect_fn
from posthog.temporal.health_checks.signal_emitter import emit_health_check_signals
from posthog.temporal.health_checks.validation import _validate_batch_output

logger = structlog.get_logger(__name__)


def run_check_for_team(kind: str, team_id: int) -> BatchResult:
    """Run a registered check for one team with its configured dry-run default.

    The one entry point for manual single-team paths (the Health page refresh task, agent
    tools), so no caller can forget to forward the registration's `dry_run` again. That
    `dry_run` is the fallback rather than the decision: a team the check's live flag
    enables writes issues here too.

    Raises KeyError for an unregistered kind.
    """
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

    live_ids = live_team_ids(kind, team_ids, default_dry_run=dry_run)
    # A dry team passed to resolution would lose its active issues and emit resolved alerts.
    live_issues_by_team = {t: results for t, results in issues_by_team.items() if t in live_ids}

    if len(live_ids) < len(team_ids):
        logger.info(
            "skipping DB writes for dry teams",
            kind=kind,
            teams_dry=len(team_ids) - len(live_ids),
            teams_live=len(live_ids),
            dry_teams_with_issues=len(issues_by_team) - len(live_issues_by_team),
            dry_issue_count=sum(len(v) for t, v in issues_by_team.items() if t not in live_ids),
        )

    if not live_ids:
        return result

    start = time.monotonic()
    newly_active = upsert_issues_with_deltas(kind, live_issues_by_team)
    result.issues_upserted = len(newly_active)
    result.db_write_duration = time.monotonic() - start

    healthy_team_ids = live_ids - live_issues_by_team.keys()

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
