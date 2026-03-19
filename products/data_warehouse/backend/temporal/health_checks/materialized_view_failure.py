from django.db.models import Q

from posthog.dags.common.owners import JobOwners
from posthog.models.health_issue import HealthIssue
from posthog.temporal.health_checks.detectors import DEFAULT_EXECUTION_POLICY
from posthog.temporal.health_checks.framework import HealthCheck
from posthog.temporal.health_checks.models import HealthCheckResult

from products.data_warehouse.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery


class MaterializedViewFailureCheck(HealthCheck):
    name = "materialized_view_failure"
    kind = "materialized_view_failure"
    owner = JobOwners.TEAM_DATA_MODELING
    policy = DEFAULT_EXECUTION_POLICY

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
