from django.db.models import Q

from posthog.dags.common.owners import JobOwners
from posthog.models.health_issue import HealthIssue
from posthog.temporal.health_checks.detectors import DEFAULT_EXECUTION_POLICY
from posthog.temporal.health_checks.framework import AlertContent, HealthCheck, Remediation
from posthog.temporal.health_checks.models import HealthCheckResult

from products.warehouse_sources.backend.facade.models import ExternalDataSchema


class ExternalDataFailureCheck(HealthCheck):
    name = "external_data_failure"
    kind = "external_data_failure"
    owner = JobOwners.TEAM_DATA_STACK
    policy = DEFAULT_EXECUTION_POLICY
    schedule = "15 7 * * *"
    active_since_days = 30
    remediation = Remediation(
        human="""
            Open the Pipeline status page (Data pipeline / Data warehouse → Sources). Find the failing
            source, open its latest run, and read the error. The most common causes are expired or rotated
            credentials, a permissions change on the source, or a schema change upstream (a renamed or
            removed column). Fix the root cause — reconnect or update the credentials, re-grant access, or
            update the schema mapping — then trigger a new sync and confirm it completes.
        """,
        agent="""
            Diagnose it with the external-data tools rather than guessing: `external-data-sources-list` /
            `external-data-sources-retrieve` to find the source, then `external-data-sources-jobs` and
            `external-data-sync-logs` to read the actual failure. If it's a config problem you can fix it
            with `external-data-sources-partial-update` and re-run via `external-data-schemas-resync` (or
            `external-data-sources-reload`). If it's expired or revoked credentials, surface the exact
            error and have the user reconnect the source — credentials can't be set over the API. Use
            `docs-search` for the connector's docs. The check clears once a sync succeeds.
        """,
    )

    @classmethod
    def render_alert(cls, issue: HealthIssue) -> AlertContent:
        name = issue.payload.get("pipeline_name") or issue.payload.get("source_type", "an external data sync")
        return AlertContent(
            title="External data sync failed",
            summary=f"{name} is failing to sync",
            link="/health/pipeline-status",
        )

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
