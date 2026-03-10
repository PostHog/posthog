import time

import dagster

from posthog.dags.common.health.db import _resolve_stale_issues, _upsert_issues
from posthog.dags.common.health.types import BatchDetectFn, BatchResult
from posthog.dags.common.health.validation import _validate_batch_output


def _process_batch_detection(
    team_ids: list[int],
    kind: str,
    detect_fn: BatchDetectFn,
    context: dagster.OpExecutionContext,
    *,
    dry_run: bool = False,
) -> BatchResult:
    result = BatchResult(batch_size=len(team_ids))

    start = time.monotonic()
    issues_by_team = detect_fn(team_ids, context)
    result.detect_duration = time.monotonic() - start

    issues_by_team = _validate_batch_output(issues_by_team, set(team_ids), kind, context)

    result.teams_with_issues = len(issues_by_team)
    result.teams_healthy = len(team_ids) - len(issues_by_team)

    if dry_run:
        issue_count = sum(len(v) for v in issues_by_team.values())
        context.log.info(
            f"[dry_run] Health check '{kind}': {result.teams_with_issues} teams with {issue_count} issues, "
            f"{result.teams_healthy} healthy — skipping DB writes"
        )
        return result

    start = time.monotonic()
    result.issues_upserted = _upsert_issues(kind, issues_by_team)
    result.db_write_duration = time.monotonic() - start

    healthy_team_ids = set(team_ids) - set(issues_by_team.keys())

    start = time.monotonic()
    result.issues_resolved = _resolve_stale_issues(kind, issues_by_team, healthy_team_ids)
    result.resolve_duration = time.monotonic() - start

    return result
