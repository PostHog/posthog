import structlog

from posthog.dags.common.owners import JobOwners
from posthog.models.health_issue import HealthIssue
from posthog.temporal.health_checks.detectors import CLICKHOUSE_BATCH_EXECUTION_POLICY
from posthog.temporal.health_checks.framework import HealthCheck
from posthog.temporal.health_checks.models import HealthCheckResult
from posthog.temporal.health_checks.query import execute_clickhouse_health_team_query

logger = structlog.get_logger(__name__)

INGESTION_WARNINGS_LOOKBACK_DAYS = 7
INGESTION_WARNINGS_MIN_COUNT = 10

# Per-type critical thresholds based on p90/p95 distributions.
# Types not listed here are always marked with WARNING severity.
INGESTION_WARNINGS_CRITICAL_THRESHOLDS: dict[str, int] = {
    "client_ingestion_warning": 5000,
    "cannot_merge_already_identified": 1000,
    "invalid_heatmap_data": 3500,
    "message_timestamp_diff_too_large": 300,
    "cannot_merge_with_illegal_distinct_id": 2500,
    "invalid_event_when_process_person_profile_is_false": 800,
    "message_size_too_large": 300,
    "invalid_process_person_profile": 200,
    "cookieless_timestamp_out_of_range": 100,
}

# Ingestion warnings are written to ClickHouse during event ingestion (not detected here).
# This query aggregates those pre-existing warnings to surface them as health issues.
INGESTION_WARNINGS_SQL = """
SELECT team_id, type, count() AS cnt, max(timestamp) AS last_seen_at
FROM ingestion_warnings
WHERE team_id IN %(team_ids)s
  AND timestamp >= now() - INTERVAL %(lookback_days)s DAY
GROUP BY team_id, type
HAVING cnt >= %(min_count)s
"""


class IngestionWarningsCheck(HealthCheck):
    name = "ingestion_warnings"
    kind = "ingestion_warning"
    owner = JobOwners.TEAM_INGESTION
    policy = CLICKHOUSE_BATCH_EXECUTION_POLICY

    def detect(self, team_ids: list[int]) -> dict[int, list[HealthCheckResult]]:
        rows = execute_clickhouse_health_team_query(
            INGESTION_WARNINGS_SQL,
            team_ids=team_ids,
            lookback_days=INGESTION_WARNINGS_LOOKBACK_DAYS,
            params={"min_count": INGESTION_WARNINGS_MIN_COUNT},
        )

        issues: dict[int, list[HealthCheckResult]] = {}
        for team_id, warning_type, affected_count, last_seen_at in rows:
            threshold = INGESTION_WARNINGS_CRITICAL_THRESHOLDS.get(warning_type)
            severity = (
                HealthIssue.Severity.CRITICAL
                if threshold is not None and affected_count >= threshold
                else HealthIssue.Severity.WARNING
            )
            issues.setdefault(team_id, []).append(
                HealthCheckResult(
                    severity=severity,
                    payload={
                        "warning_type": warning_type,
                        "affected_count": affected_count,
                        "last_seen_at": str(last_seen_at),
                    },
                    hash_keys=["warning_type"],
                )
            )

        if issues:
            type_teams: dict[str, int] = {}
            type_counts: dict[str, int] = {}
            type_severity: dict[str, str] = {}
            for team_results in issues.values():
                for r in team_results:
                    wt = r.payload["warning_type"]
                    type_teams[wt] = type_teams.get(wt, 0) + 1
                    type_counts[wt] = type_counts.get(wt, 0) + r.payload["affected_count"]
                    if r.severity == HealthIssue.Severity.CRITICAL:
                        type_severity[wt] = HealthIssue.Severity.CRITICAL
                    else:
                        type_severity.setdefault(wt, r.severity)

            lines = [f"Ingestion warnings breakdown ({len(type_counts)} types across {len(issues)} teams):"]
            for wt in sorted(type_counts, key=lambda k: type_counts[k], reverse=True):
                lines.append(f"  {wt}: {type_counts[wt]:,} events, {type_teams[wt]} teams, {type_severity[wt]}")
            logger.info("\n".join(lines))

        return issues
