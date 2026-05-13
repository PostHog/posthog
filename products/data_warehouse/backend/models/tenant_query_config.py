from django.db import models

from posthog.models.utils import CreatedMetaFields, UpdatedMetaFields, UUIDTModel, sane_repr


class DataWarehouseTenantQueryConfig(CreatedMetaFields, UpdatedMetaFields, UUIDTModel):
    class TenantColumnType(models.TextChoices):
        INTEGER = "integer", "integer"
        STRING = "string", "string"
        UUID = "uuid", "uuid"

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    external_data_source = models.OneToOneField(
        "data_warehouse.ExternalDataSource",
        on_delete=models.CASCADE,
        related_name="tenant_query_config",
    )
    enabled = models.BooleanField(default=False)
    tenant_column_name = models.CharField(max_length=128)
    tenant_column_type = models.CharField(max_length=32, choices=TenantColumnType.choices)
    default_timeout_ms = models.PositiveIntegerField(default=30_000)
    max_timeout_ms = models.PositiveIntegerField(default=120_000)
    max_result_limit = models.PositiveIntegerField(default=100_000)

    __repr__ = sane_repr("id", "team_id", "external_data_source_id", "enabled", "tenant_column_name")

    class Meta:
        app_label = "data_warehouse"
        db_table = "posthog_datawarehousetenantqueryconfig"
