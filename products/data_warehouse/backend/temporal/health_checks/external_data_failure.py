from django.db.models import Q

from posthog.dags.common.owners import JobOwners
from posthog.models.health_issue import HealthIssue
from posthog.temporal.health_checks.detectors import DEFAULT_EXECUTION_POLICY
from posthog.temporal.health_checks.framework import HealthCheck
from posthog.temporal.health_checks.models import HealthCheckResult

from products.data_warehouse.backend.models.external_data_schema import ExternalDataSchema


class ExternalDataFailureCheck(HealthCheck):
    name = "external_data_failure"
    kind = "external_data_failure"
    owner = JobOwners.TEAM_DATA_STACK
    policy = DEFAULT_EXECUTION_POLICY

    def detect(self, team_ids: list[int]) -> dict[int, list[HealthCheckResult]]:
        issues: dict[int, list[HealthCheckResult]] = {}

        failed_schemas = (
            ExternalDataSchema.objects.filter(
                team_id__in=team_ids,
                deleted=False,
            )
            .filter(
                Q(status=ExternalDataSchema.Status.FAILED)
                | Q(status=ExternalDataSchema.Status.BILLING_LIMIT_REACHED)
                | Q(status=ExternalDataSchema.Status.BILLING_LIMIT_TOO_LOW)
                | Q(should_sync=False, latest_error__isnull=False)
            )
            .select_related("source")
        )

        for schema in failed_schemas:
            error = schema.latest_error or ""
            issues.setdefault(schema.team_id, []).append(
                HealthCheckResult(
                    severity=HealthIssue.Severity.WARNING,
                    payload={
                        "pipeline_type": "external_data_sync",
                        "pipeline_id": str(schema.id),
                        "pipeline_name": schema.name,
                        "source_type": schema.source.source_type if schema.source else "unknown",
                        "error": error[:500],
                    },
                    hash_keys=["pipeline_type", "pipeline_id"],
                )
            )

        return issues
