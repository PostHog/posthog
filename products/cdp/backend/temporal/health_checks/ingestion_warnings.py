from datetime import datetime

import structlog

from posthog.dags.common.owners import JobOwners
from posthog.models.health_issue import HealthIssue
from posthog.models.ingestion_warnings.sql_v2 import DISTRIBUTED_TABLE_NAME
from posthog.models.team import Team
from posthog.temporal.health_checks.detectors import CLICKHOUSE_BATCH_EXECUTION_POLICY
from posthog.temporal.health_checks.framework import (
    _SEVERITY_WEIGHT,
    AlertContent,
    HealthCheck,
    Remediation,
    SignalContent,
    build_signal_extra,
)
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
#
# Capture-sourced warnings carry team_id=0 and the project's API token (capture has no
# database access to resolve the team), so the query also matches the batch's tokens and
# returns the token column; rows are grouped per (team_id, token, type) here and merged
# into per-team results in Python, where the min-count threshold is applied post-merge so
# a team's direct and token-matched rows count together.
INGESTION_WARNINGS_SQL = f"""
SELECT team_id, token, type, count() AS cnt, max(timestamp) AS last_seen_at
FROM {DISTRIBUTED_TABLE_NAME}
WHERE (team_id IN %(team_ids)s OR (team_id = 0 AND token IN %(tokens)s))
  AND timestamp >= now() - INTERVAL %(lookback_days)s DAY
GROUP BY team_id, token, type
"""


class IngestionWarningsCheck(HealthCheck):
    name = "ingestion_warnings"
    kind = "ingestion_warning"
    owner = JobOwners.TEAM_INGESTION
    policy = CLICKHOUSE_BATCH_EXECUTION_POLICY
    schedule = "0 7 * * *"
    active_since_days = 30
    remediation = Remediation(
        human="""
            Open the Ingestion warnings page. It groups warnings by type and shows examples of the affected
            events. Use the type and the examples to trace the warning back to the instrumentation that
            produced it, then fix how those events are sent.
        """,
        agent="""
            Read this issue with `health-issues-get` to get the `warning_type` and `affected_count` from
            the payload, and use `execute-sql` to pull example offending events for that warning type so
            you can see the exact properties involved. Then fix it in the user's codebase at the
            `posthog.capture` (or autocapture) call sites that emit those events — for example stop sending
            oversized or malformed properties, correct the event timestamp, or align the event name — and
            redeploy. Use `docs-search` for the specific warning type. The issue clears once the warning
            stops firing.
        """,
    )

    @classmethod
    def render_alert(cls, issue: HealthIssue) -> AlertContent:
        warning_type = issue.payload.get("warning_type", "ingestion warning")
        count = issue.payload.get("affected_count")
        summary = f"{warning_type} fired {count} times" if count is not None else f"{warning_type} detected"
        return AlertContent(
            title="Ingestion warning detected",
            summary=summary,
            link="/health/ingestion",
        )

    @classmethod
    def render_signal(cls, issue: HealthIssue) -> SignalContent | None:
        warning_type = issue.payload.get("warning_type", "ingestion warning")
        count = issue.payload.get("affected_count")
        count_clause = f"{count:,} times" if isinstance(count, int) else "repeatedly"
        title = "Ingestion warning detected"
        summary = f"{warning_type} fired {count} times" if count is not None else f"{warning_type} detected"
        return SignalContent(
            description=(
                f"PostHog raised the ingestion warning `{warning_type}` {count_clause} for this project in the last "
                "week. Ingestion warnings mean events are being dropped, mis-merged, or degraded on the way in — so "
                "the affected data is incomplete or inaccurate. Recommend reviewing the ingestion warnings page to "
                "find the source and fix the instrumentation producing them."
            ),
            weight=_SEVERITY_WEIGHT[issue.severity],
            extra=build_signal_extra(issue, title=title, summary=summary, link="/health/ingestion"),
        )

    def detect(self, team_ids: list[int]) -> dict[int, list[HealthCheckResult]]:
        token_to_team_id: dict[str, int] = {
            token: team_id for team_id, token in Team.objects.filter(id__in=team_ids).values_list("id", "api_token")
        }
        rows = execute_clickhouse_health_team_query(
            INGESTION_WARNINGS_SQL,
            team_ids=team_ids,
            lookback_days=INGESTION_WARNINGS_LOOKBACK_DAYS,
            params={"tokens": list(token_to_team_id.keys())},
        )

        # Merge direct (team_id) and token-matched (team_id=0) rows per team, then
        # apply the min-count threshold to the merged totals.
        merged_counts: dict[tuple[int, str], int] = {}
        merged_last_seen: dict[tuple[int, str], datetime] = {}
        for team_id, token, warning_type, affected_count, last_seen_at in rows:
            resolved_team_id = team_id if team_id != 0 else token_to_team_id.get(token)
            if resolved_team_id is None:
                continue
            key = (resolved_team_id, warning_type)
            merged_counts[key] = merged_counts.get(key, 0) + affected_count
            merged_last_seen[key] = max(merged_last_seen.get(key, last_seen_at), last_seen_at)

        issues: dict[int, list[HealthCheckResult]] = {}
        for (team_id, warning_type), affected_count in merged_counts.items():
            if affected_count < INGESTION_WARNINGS_MIN_COUNT:
                continue
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
                        "last_seen_at": str(merged_last_seen[(team_id, warning_type)]),
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
