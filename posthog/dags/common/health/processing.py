import time

import dagster

from posthog.dags.common.health.db import _resolve_stale_issues, _upsert_issues
from posthog.dags.common.health.types import BatchDetectFn, BatchResult, HealthCheckResult, TeamDetectFn
from posthog.dags.common.health.validation import _validate_batch_output
from posthog.exceptions_capture import capture_exception


def _process_batch_detection(
    team_ids: list[int],
    kind: str,
    detect_fn: BatchDetectFn,
    context: dagster.OpExecutionContext,
) -> BatchResult:
    result = BatchResult(batch_size=len(team_ids))

    start = time.monotonic()
    issues_by_team = detect_fn(team_ids, context)
    result.detect_duration = time.monotonic() - start

    issues_by_team = _validate_batch_output(issues_by_team, set(team_ids), kind, context)

    result.teams_with_issues = len(issues_by_team)
    result.teams_healthy = len(team_ids) - len(issues_by_team)

    start = time.monotonic()
    result.issues_upserted = _upsert_issues(kind, issues_by_team)
    result.db_write_duration = time.monotonic() - start

    healthy_team_ids = set(team_ids) - set(issues_by_team.keys())

    start = time.monotonic()
    result.issues_resolved = _resolve_stale_issues(kind, issues_by_team, healthy_team_ids)
    result.resolve_duration = time.monotonic() - start

    return result


def _process_per_team_detection(
    team_ids: list[int],
    kind: str,
    detect_fn: TeamDetectFn,
    context: dagster.OpExecutionContext,
) -> BatchResult:
    result = BatchResult(batch_size=len(team_ids))
    issues_by_team: dict[int, list[HealthCheckResult]] = {}
    skipped_team_ids: set[int] = set()
    failed_team_ids: set[int] = set()

    start = time.monotonic()
    for team_id in team_ids:
        team_start = time.monotonic()
        try:
            team_results = detect_fn(team_id, context)
            if team_results is None:
                skipped_team_ids.add(team_id)
            elif len(team_results) > 0:
                issues_by_team[team_id] = team_results
        except Exception as e:
            failed_team_ids.add(team_id)
            context.log.warning(f"Health check '{kind}' failed for team {team_id}: {e}")
            capture_exception(e, {"team_id": team_id, "health_check_kind": kind})

        team_duration = time.monotonic() - team_start
        if team_duration > 1.0:
            context.log.warning(f"Health check '{kind}' took {team_duration:.1f}s for team {team_id} (>1s threshold)")
    result.detect_duration = time.monotonic() - start

    result.teams_with_issues = len(issues_by_team)
    result.teams_failed = len(failed_team_ids)
    result.teams_skipped = len(skipped_team_ids)
    result.teams_healthy = len(team_ids) - len(issues_by_team) - len(failed_team_ids) - len(skipped_team_ids)

    start = time.monotonic()
    result.issues_upserted = _upsert_issues(kind, issues_by_team)
    result.db_write_duration = time.monotonic() - start

    # Only resolve stale issues for teams that were successfully checked (not skipped/failed)
    checked_healthy = set(team_ids) - set(issues_by_team.keys()) - skipped_team_ids - failed_team_ids

    start = time.monotonic()
    result.issues_resolved = _resolve_stale_issues(kind, issues_by_team, checked_healthy)
    result.resolve_duration = time.monotonic() - start

    return result
