from posthog.clickhouse.query_tagging import Product
from posthog.job_owners import JobOwners
from posthog.models.health_issue import HealthIssue
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

INGESTION_STOPPED_SILENCE_HOURS = 3
INGESTION_STOPPED_BASELINE_HOURS = 24
# A project must send events in most hours of the baseline, so a project that sends only in
# working hours or in daily batches does not look stopped during its normal quiet hours.
INGESTION_STOPPED_MIN_ACTIVE_HOURS = 20

# Capture returns HTTP 200 before an event reaches storage, so a project can lose all its data
# without an error on the client side. This finds projects that sent events steadily and then stopped.
INGESTION_STOPPED_SQL = """
SELECT
    team_id,
    max(timestamp) AS last_event_at,
    uniq(toStartOfHour(timestamp)) AS active_hours
FROM events
WHERE team_id IN %(team_ids)s
  AND timestamp >= now() - INTERVAL %(window_hours)s HOUR
GROUP BY team_id
HAVING active_hours >= %(min_active_hours)s
   AND last_event_at < now() - INTERVAL %(silence_hours)s HOUR
"""


class IngestionStoppedCheck(HealthCheck):
    name = "ingestion_stopped"
    kind = "ingestion_stopped"
    owner = JobOwners.TEAM_INGESTION
    product = Product.INGESTION
    policy = CLICKHOUSE_BATCH_EXECUTION_POLICY
    schedule = "15 * * * *"
    active_since_days = 30
    remediation = Remediation(
        human="""
            Your project sent events every hour and then stopped. Open Activity → Live events and confirm
            whether events arrive now. Make sure your app still loads the PostHog SDK and uses the current
            project API key from Project settings. If you rotated the project API key, update it everywhere
            you send data. If the SDK sends events and they still do not arrive, contact PostHog support.
        """,
        agent="""
            Use `execute-sql` to find when events stopped (`SELECT toStartOfHour(timestamp) AS hour, count()
            FROM events WHERE timestamp > now() - INTERVAL 2 DAY GROUP BY hour ORDER BY hour`). Use
            `advanced-activity-logs-list` to look for a project API key rotation or a project setting change
            at that time. Then check the user's codebase: find where PostHog is initialized and confirm that
            it runs with the current project API key and host, and that no recent deploy removed or
            disabled it. If the configuration is correct and events still do not arrive, tell the user to
            contact PostHog support with the time the events stopped. The issue resolves when events arrive
            again.
        """,
    )

    @classmethod
    def render_alert(cls, issue: HealthIssue) -> AlertContent:
        return AlertContent(
            title="Events stopped arriving",
            summary=issue.payload.get("reason", "This project stopped receiving events"),
            link="/health/ingestion",
        )

    @classmethod
    def render_signal(cls, issue: HealthIssue) -> SignalContent | None:
        title = "Events stopped arriving"
        summary = issue.payload.get("reason", "This project stopped receiving events.")
        return SignalContent(
            description=(
                f"This project received events in most hours of the previous day, but no events in the last "
                f"{INGESTION_STOPPED_SILENCE_HOURS} hours. Capture accepts requests before the data reaches "
                "storage, so the SDK shows no error while the data is lost. Recommend checking that the SDK still "
                "runs with the current project API key, and contacting PostHog support if it does."
            ),
            weight=_SEVERITY_WEIGHT[issue.severity],
            extra=build_signal_extra(issue, title=title, summary=summary, link="/health/ingestion"),
        )

    def detect(self, team_ids: list[int]) -> dict[int, list[HealthCheckResult]]:
        rows = execute_clickhouse_health_team_query(
            INGESTION_STOPPED_SQL,
            team_ids=team_ids,
            params={
                "window_hours": INGESTION_STOPPED_BASELINE_HOURS + INGESTION_STOPPED_SILENCE_HOURS,
                "silence_hours": INGESTION_STOPPED_SILENCE_HOURS,
                "min_active_hours": INGESTION_STOPPED_MIN_ACTIVE_HOURS,
            },
        )

        return {
            team_id: [
                HealthCheckResult(
                    severity=HealthIssue.Severity.CRITICAL,
                    payload={
                        "reason": f"No events in the last {INGESTION_STOPPED_SILENCE_HOURS} hours",
                        "last_event_at": str(last_event_at),
                        "active_hours": active_hours,
                    },
                    hash_keys=[],
                )
            ]
            for team_id, last_event_at, active_hours in rows
        }
