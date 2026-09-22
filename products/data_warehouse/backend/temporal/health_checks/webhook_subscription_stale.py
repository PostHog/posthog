from django.db.models import Q

import structlog

from posthog.job_owners import JobOwners
from posthog.models.health_issue import HealthIssue
from posthog.temporal.health_checks.detectors import HealthExecutionPolicy
from posthog.temporal.health_checks.framework import AlertContent, HealthCheck, Remediation
from posthog.temporal.health_checks.models import HealthCheckResult

from products.warehouse_sources.backend.facade.models import ExternalDataSchema, ExternalDataSource
from products.warehouse_sources.backend.facade.types import ExternalDataSourceType

logger = structlog.get_logger(__name__)

_MAX_LISTED = 20


class WebhookSubscriptionStaleCheck(HealthCheck):
    """Flag a webhook source that silently receives nothing because its provider endpoint is
    subscribed to too narrow a set of events.

    A webhook endpoint created before its source's resource-to-event map grew keeps its original,
    narrower ``enabled_events`` forever, because the reconcile that would widen it only runs when a
    user edits a schema. A table added later never receives a delivery and freezes at the
    source-creation date, with no error anywhere. This check flags a webhook-synced schema that has
    never landed data and whose own mapped events are entirely absent from the endpoint.
    """

    name = "webhook_subscription_stale"
    kind = "webhook_subscription_stale"
    owner = JobOwners.TEAM_DATA_STACK
    policy = HealthExecutionPolicy(batch_size=50, max_concurrent=3)
    schedule = "45 7 * * *"
    active_since_days = 30
    access_controlled_resource = "external_data_source"
    remediation = Remediation(
        human="""
            The webhook on your source is subscribed to fewer event types than the connected tables
            need, so some tables never receive data. Open the source (Data pipeline / Data warehouse →
            Sources), go to the Webhook tab, and add the missing events — or delete and recreate the
            webhook so it picks up the full set. Webhooks can't backfill, so after the events are
            subscribed, run a one-time full refresh on the affected tables to load their history.
        """,
        agent="""
            Confirm the gap with `external-data-sources-retrieve` and the source's webhook info, which
            lists the endpoint's enabled events against the events the source wants. Have the user add
            the missing events or recreate the webhook from the Webhook tab (webhook subscriptions
            can't be changed over the API). Once the endpoint is subscribed, trigger a full refresh on
            the affected schemas with `external-data-schemas-resync` to backfill the history webhooks
            can't deliver. The check clears once a delivery lands and the schema syncs.
        """,
    )

    @classmethod
    def render_alert(cls, issue: HealthIssue) -> AlertContent:
        name = issue.payload.get("pipeline_name") or issue.payload.get("source_type", "a webhook source")
        return AlertContent(
            title="Webhook source is missing event subscriptions",
            summary=f"{name} has tables that never receive data because its webhook events are incomplete",
            link="/health/pipeline-status",
        )

    def detect(self, team_ids: list[int]) -> dict[int, list[HealthCheckResult]]:
        from products.cdp.backend.facade.models import HogFunction
        from products.data_warehouse.backend.logic.external_data_source.webhooks import get_webhook_url
        from products.warehouse_sources.backend.facade.source_management import SourceRegistry, WebhookSource

        stale_schemas = (
            ExternalDataSchema.objects.filter(
                team_id__in=team_ids,
                deleted=False,
                should_sync=True,
                sync_type=ExternalDataSchema.SyncType.WEBHOOK,
            )
            .filter(Q(table__isnull=True) | Q(table__row_count=0))
            .select_related("source")
        )

        schemas_by_source: dict[str, list[ExternalDataSchema]] = {}
        sources: dict[str, ExternalDataSource] = {}
        for schema in stale_schemas:
            source = schema.source
            if source is None or not source.job_inputs:
                continue
            schemas_by_source.setdefault(str(source.pk), []).append(schema)
            sources[str(source.pk)] = source

        issues: dict[int, list[HealthCheckResult]] = {}

        for source_pk, schemas in schemas_by_source.items():
            source = sources[source_pk]
            try:
                source_impl = SourceRegistry.get_source(ExternalDataSourceType(source.source_type))
            except Exception:
                continue
            if not isinstance(source_impl, WebhookSource):
                continue

            hog_function = HogFunction.objects.filter(
                team_id=source.team_id,
                type="warehouse_source_webhook",
                inputs__source_id__value=source_pk,
                deleted=False,
            ).first()
            if hog_function is None:
                continue

            webhook_url = get_webhook_url(hog_function.id)
            try:
                config = source_impl.parse_config(source.job_inputs)
                api_version = source_impl.resolve_api_version(source.api_version)
                external = source_impl.get_external_webhook_info(
                    config, webhook_url, source.team_id, api_version=api_version
                )
            except Exception as e:
                logger.warning(
                    "webhook_subscription_stale: could not read webhook info",
                    source_id=source_pk,
                    error_type=type(e).__name__,
                )
                continue

            if external is None or not external.exists or external.error:
                continue
            enabled = set(external.enabled_events or [])
            if "*" in enabled:
                continue

            affected_schemas: list[str] = []
            missing_events: set[str] = set()
            for schema in schemas:
                try:
                    desired = source_impl.get_desired_webhook_events(config, [schema.name]) or []
                except Exception:
                    continue
                key = source_impl.webhook_mapping_key(schema.name)
                schema_events = [event for event in desired if event == key or event.startswith(f"{key}.")]
                if schema_events and not any(event in enabled for event in schema_events):
                    affected_schemas.append(schema.name)
                    missing_events.update(schema_events)

            if not affected_schemas:
                continue

            issues.setdefault(source.team_id, []).append(
                HealthCheckResult(
                    severity=HealthIssue.Severity.WARNING,
                    payload={
                        "pipeline_type": "external_data_webhook",
                        "pipeline_id": source_pk,
                        "pipeline_name": source.prefix or source.source_type,
                        "source_type": source.source_type,
                        "affected_schemas": sorted(affected_schemas)[:_MAX_LISTED],
                        "missing_events": sorted(missing_events)[:_MAX_LISTED],
                    },
                    hash_keys=["pipeline_type", "pipeline_id"],
                )
            )

        return issues
