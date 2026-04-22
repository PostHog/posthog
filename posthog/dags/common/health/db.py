from posthog.dags.common.health.types import HealthCheckResult
from posthog.models.health_issue import HealthIssue


def _upsert_issues(
    kind: str,
    issues_by_team: dict[int, list[HealthCheckResult]],
) -> int:
    issues = [
        {
            "team_id": team_id,
            "severity": result.severity,
            "payload": result.payload,
            "unique_hash": HealthIssue.compute_unique_hash(kind, result.payload, result.hash_keys),
        }
        for team_id, results in issues_by_team.items()
        for result in results
    ]
    return HealthIssue.bulk_upsert(kind, issues)


def _resolve_stale_issues(
    kind: str,
    issues_by_team: dict[int, list[HealthCheckResult]],
    healthy_team_ids: set[int],
) -> int:
    all_team_ids = healthy_team_ids | set(issues_by_team.keys())

    keep_hashes: dict[int, set[str]] = {}
    for team_id, results in issues_by_team.items():
        keep_hashes[team_id] = {HealthIssue.compute_unique_hash(kind, r.payload, r.hash_keys) for r in results}

    return HealthIssue.bulk_resolve(kind, all_team_ids, keep_hashes or None)
