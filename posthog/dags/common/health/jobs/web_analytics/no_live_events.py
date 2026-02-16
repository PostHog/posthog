import dagster

from posthog.clickhouse.client import sync_execute
from posthog.dags.common import JobOwners
from posthog.dags.common.health.framework import create_health_check
from posthog.dags.common.health.types import HealthCheckResult
from posthog.models.health_issue import HealthIssue


def detect_no_live_events(
    team_ids: list[int], context: dagster.OpExecutionContext
) -> dict[int, list[HealthCheckResult]]:
    rows = (
        sync_execute(
            """
        SELECT team_id, dateDiff('day', max(timestamp), now()) AS days_inactive
        FROM events
        WHERE team_id IN %(team_ids)s
        GROUP BY team_id
        """,
            {"team_ids": team_ids},
        )
        or []
    )

    issues: dict[int, list[HealthCheckResult]] = {}
    teams_with_events: set[int] = set()

    for team_id, days_inactive in rows:
        teams_with_events.add(team_id)
        if days_inactive > 7:
            severity = HealthIssue.Severity.CRITICAL if days_inactive > 30 else HealthIssue.Severity.WARNING
            issues[team_id] = [
                HealthCheckResult(
                    severity=severity,
                    payload={"days_inactive": days_inactive},
                    hash_keys=[],
                )
            ]

    for team_id in set(team_ids) - teams_with_events:
        issues[team_id] = [
            HealthCheckResult(
                severity=HealthIssue.Severity.CRITICAL,
                payload={"days_inactive": -1, "reason": "No events ever"},
                hash_keys=[],
            )
        ]

    return issues


no_live_events_check = create_health_check(
    name="no_live_events",
    kind="no_live_events",
    detect_fn=detect_no_live_events,
    owner=JobOwners.TEAM_WEB_ANALYTICS,
)
