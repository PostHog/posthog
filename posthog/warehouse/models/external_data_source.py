from datetime import datetime
from django.db import models

from posthog.helpers.cryptography import EncryptedJSONField
from posthog.models.team import Team
from posthog.models.utils import CreatedMetaFields, DeletedMetaFields, UUIDModel, UpdatedMetaFields, sane_repr
from posthog.warehouse.util import database_sync_to_async
from uuid import UUID

import structlog
import temporalio

logger = structlog.get_logger(__name__)


class ExternalDataSource(CreatedMetaFields, UpdatedMetaFields, UUIDModel, DeletedMetaFields):
    class Type(models.TextChoices):
        STRIPE = "Stripe", "Stripe"
        HUBSPOT = "Hubspot", "Hubspot"
        POSTGRES = "Postgres", "Postgres"
        ZENDESK = "Zendesk", "Zendesk"
        SNOWFLAKE = "Snowflake", "Snowflake"
        SALESFORCE = "Salesforce", "Salesforce"
        MYSQL = "MySQL", "MySQL"
        MSSQL = "MSSQL", "MSSQL"
        VITALLY = "Vitally", "Vitally"

    class Status(models.TextChoices):
        RUNNING = "Running", "Running"
        PAUSED = "Paused", "Paused"
        ERROR = "Error", "Error"
        COMPLETED = "Completed", "Completed"
        CANCELLED = "Cancelled", "Cancelled"

    # Deprecated, use `ExternalDataSchema.SyncFrequency`
    class SyncFrequency(models.TextChoices):
        DAILY = "day", "Daily"
        WEEKLY = "week", "Weekly"
        MONTHLY = "month", "Monthly"
        # TODO provide flexible schedule definition

    source_id = models.CharField(max_length=400)
    connection_id = models.CharField(max_length=400)
    destination_id = models.CharField(max_length=400, null=True, blank=True)
    team = models.ForeignKey(Team, on_delete=models.CASCADE)

    # Deprecated, use `ExternalDataSchema.sync_frequency_interval`
    sync_frequency = models.CharField(
        max_length=128, choices=SyncFrequency.choices, default=SyncFrequency.DAILY, blank=True
    )

    # `status` is deprecated in favour of external_data_schema.status
    status = models.CharField(max_length=400)
    source_type = models.CharField(max_length=128, choices=Type.choices)
    job_inputs: EncryptedJSONField = EncryptedJSONField(null=True, blank=True)
    are_tables_created = models.BooleanField(default=False)
    prefix = models.CharField(max_length=100, null=True, blank=True)

    __repr__ = sane_repr("id")

    def soft_delete(self):
        self.deleted = True
        self.deleted_at = datetime.now()
        self.save()

    def reload_schemas(self):
        from posthog.warehouse.models.external_data_schema import ExternalDataSchema
        from posthog.warehouse.data_load.service import sync_external_data_job_workflow, trigger_external_data_workflow

        for schema in (
            ExternalDataSchema.objects.exclude(deleted=True)
            .filter(team_id=self.team.pk, source_id=self.id, should_sync=True)
            .all()
        ):
            try:
                trigger_external_data_workflow(schema)
            except temporalio.service.RPCError as e:
                if e.status == temporalio.service.RPCStatusCode.NOT_FOUND:
                    sync_external_data_job_workflow(schema, create=True)

            except Exception as e:
                logger.exception(f"Could not trigger external data job for schema {schema.name}", exc_info=e)


@database_sync_to_async
def get_external_data_source(source_id: UUID) -> ExternalDataSource:
    return ExternalDataSource.objects.get(pk=source_id)
