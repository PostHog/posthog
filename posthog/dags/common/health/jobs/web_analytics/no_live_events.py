import dagster

from posthog.dags.common import JobOwners
from posthog.dags.common.health.detectors import clickhouse_batch_detector_from_fn
from posthog.dags.common.health.framework import create_health_check
from posthog.dags.common.health.query import execute_clickhouse_health_team_query
from posthog.dags.common.health.types import HealthCheckResult
from posthog.models.health_issue import HealthIssue

NO_LIVE_EVENTS_LOOKBACK_DAYS = 30
NO_LIVE_EVENTS_SQL = """
SELECT team_id
FROM events
WHERE team_id IN %(team_ids)s
  AND event = '$pageview'
  AND timestamp >= now() - INTERVAL %(lookback_days)s DAY
GROUP BY team_id
"""


def detect_no_live_events(
    team_ids: list[int], context: dagster.OpExecutionContext
) -> dict[int, list[HealthCheckResult]]:
    rows = execute_clickhouse_health_team_query(
        NO_LIVE_EVENTS_SQL,
        team_ids=team_ids,
        lookback_days=NO_LIVE_EVENTS_LOOKBACK_DAYS,
        context=context,
    )

    teams_with_recent_pageviews = {team_id for team_id, *_ in rows}

    issues: dict[int, list[HealthCheckResult]] = {}
    for team_id in set(team_ids) - teams_with_recent_pageviews:
        issues[team_id] = [
            HealthCheckResult(
                severity=HealthIssue.Severity.CRITICAL,
                payload={"reason": f"No $pageview events in last {NO_LIVE_EVENTS_LOOKBACK_DAYS} days"},
                hash_keys=[],
            )
        ]

    return issues


no_live_events_check = create_health_check(
    name="no_live_events",
    kind="no_live_events",
    detector=clickhouse_batch_detector_from_fn(detect_no_live_events),
    owner=JobOwners.TEAM_WEB_ANALYTICS,
)
