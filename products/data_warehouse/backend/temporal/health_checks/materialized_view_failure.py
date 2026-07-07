from django.db.models import Q

from posthog.dags.common.owners import JobOwners
from posthog.models.health_issue import HealthIssue
from posthog.temporal.health_checks.detectors import DEFAULT_EXECUTION_POLICY
from posthog.temporal.health_checks.framework import (
    _SEVERITY_WEIGHT,
    AlertContent,
    HealthCheck,
    Remediation,
    SignalContent,
    build_signal_extra,
)
from posthog.temporal.health_checks.models import HealthCheckResult

from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery


class MaterializedViewFailureCheck(HealthCheck):
    name = "materialized_view_failure"
    kind = "materialized_view_failure"
    owner = JobOwners.TEAM_DATA_MODELING
    policy = DEFAULT_EXECUTION_POLICY
    schedule = "30 7 * * *"
    active_since_days = 30
    remediation = Remediation(
        human="""
            Open Data modeling (the Data warehouse / data modeling section). Find the failing view, open
            its latest materialization run, and read the error. Common causes are a query that no longer
            compiles (a renamed column or table it depends on), an upstream source that's itself failing,
            or a timeout / resource limit on a heavy query. Fix the view's SQL or the upstream dependency,
            then re-run the materialization and confirm it succeeds.
        """,
        agent="""
            Read this issue with `health-issues-get` for the view name and error from the payload, use
            `read-data-warehouse-schema` to see the available tables and columns, and `execute-sql` to run
            the view's query (or its upstream tables) directly to pinpoint what broke. The view's SQL is
            stored in PostHog Data modeling rather than the user's codebase, so the edit happens there —
            diagnose the exact failure, propose the corrected query, and have it re-run. Use `docs-search`
            for the data modeling / materialized view docs. The check clears once a materialization
            succeeds.
        """,
    )

    @classmethod
    def render_alert(cls, issue: HealthIssue) -> AlertContent:
        name = issue.payload.get("pipeline_name", "a materialized view")
        return AlertContent(
            title="Materialized view failed",
            summary=f"{name} failed to refresh",
            link="/health/data_modeling",
        )

    @classmethod
    def render_signal(cls, issue: HealthIssue) -> SignalContent | None:
        name = issue.payload.get("pipeline_name", "a materialized view")
        error = (issue.payload.get("error") or "").strip()
        error_clause = f' Latest error: "{error}".' if error else ""
        title = "Materialized view failed"
        summary = f"{name} failed to refresh"
        return SignalContent(
            description=(
                f'The materialized view "{name}" failed to refresh for this project, so queries and insights '
                f"reading from it are serving stale data.{error_clause} Recommend opening the model, reviewing the "
                "error, and re-running the materialization once the underlying query is fixed."
            ),
            weight=_SEVERITY_WEIGHT[issue.severity],
            extra=build_signal_extra(issue, title=title, summary=summary, link="/health/data_modeling"),
        )

    def detect(self, team_ids: list[int]) -> dict[int, list[HealthCheckResult]]:
        queryset = (
            DataWarehouseSavedQuery.objects.filter(
                team_id__in=team_ids,
                deleted=False,
            )
            .filter(
                Q(status=DataWarehouseSavedQuery.Status.FAILED)
                | (~Q(is_materialized=True) & Q(latest_error__isnull=False))
            )
            .exclude(status=DataWarehouseSavedQuery.Status.RUNNING)
        )

        issues: dict[int, list[HealthCheckResult]] = {}
        for row in queryset.values("team_id", "id", "name", "latest_error"):
            team_id = row["team_id"]
            error = row["latest_error"] or ""
            issues.setdefault(team_id, []).append(
                HealthCheckResult(
                    severity=HealthIssue.Severity.WARNING,
                    payload={
                        "pipeline_type": "materialized_view",
                        "pipeline_id": str(row["id"]),
                        "pipeline_name": row["name"],
                        "error": error[:500],
                    },
                    hash_keys=["pipeline_type", "pipeline_id"],
                )
            )
        return issues
