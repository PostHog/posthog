from datetime import datetime
from uuid import UUID

from django.db import models

import structlog
import temporalio

from posthog.helpers.encrypted_fields import EncryptedJSONField
from posthog.models.activity_logging.model_activity import ModelActivityMixin
from posthog.models.team import Team
from posthog.models.utils import CreatedMetaFields, DeletedMetaFields, UpdatedMetaFields, UUIDTModel, sane_repr
from posthog.sync import database_sync_to_async
from posthog.warehouse.types import ExternalDataSourceType

logger = structlog.get_logger(__name__)


class ExternalDataSourceManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().select_related("revenue_analytics_config")


class ExternalDataSource(ModelActivityMixin, CreatedMetaFields, UpdatedMetaFields, UUIDTModel, DeletedMetaFields):
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
    source_type = models.CharField(max_length=128, choices=ExternalDataSourceType.choices)
    job_inputs = EncryptedJSONField(null=True, blank=True)
    are_tables_created = models.BooleanField(default=False)
    prefix = models.CharField(max_length=100, null=True, blank=True)

    # DEPRECATED: Check inside `revenue_analytics_config` instead
    revenue_analytics_enabled = models.BooleanField(default=False, blank=True, null=True)

    objects = ExternalDataSourceManager()

    __repr__ = sane_repr("id", "source_id", "connection_id", "destination_id", "team_id")

    @property
    def revenue_analytics_config_safe(self):
        """
        Safely access revenue_analytics_config with automatic creation fallback.
        Use this instead of direct access when you need to guarantee the config exists.
        """
        from .revenue_analytics_config import ExternalDataSourceRevenueAnalyticsConfig

        try:
            return self.revenue_analytics_config
        except ExternalDataSourceRevenueAnalyticsConfig.DoesNotExist:
            config, _ = ExternalDataSourceRevenueAnalyticsConfig.objects.get_or_create(
                external_data_source=self,
                defaults={
                    "enabled": self.source_type == ExternalDataSourceType.STRIPE,
                },
            )
            return config

    def soft_delete(self):
        self.deleted = True
        self.deleted_at = datetime.now()
        self.save()

    def reload_schemas(self):
        from posthog.warehouse.data_load.service import sync_external_data_job_workflow, trigger_external_data_workflow
        from posthog.warehouse.models.external_data_schema import ExternalDataSchema

        for schema in (
            ExternalDataSchema.objects.filter(team_id=self.team.pk, source_id=self.id, should_sync=True)
            .exclude(deleted=True)
            .all()
        ):
            try:
                trigger_external_data_workflow(schema)
            except temporalio.service.RPCError as e:
                if e.status == temporalio.service.RPCStatusCode.NOT_FOUND:
                    sync_external_data_job_workflow(schema, create=True, should_sync=True)

            except Exception as e:
                logger.exception(f"Could not trigger external data job for schema {schema.name}", exc_info=e)


@database_sync_to_async
def get_external_data_source(source_id: UUID) -> ExternalDataSource:
    return ExternalDataSource.objects.get(pk=source_id)
