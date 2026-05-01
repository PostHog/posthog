from __future__ import annotations

from datetime import timedelta

from django.db import models

from posthog.models.utils import CreatedMetaFields, UpdatedMetaFields, UUIDTModel, sane_repr


class ManagedWarehousePromotedTable(CreatedMetaFields, UpdatedMetaFields, UUIDTModel):
    """A DuckLake table in a customer's managed warehouse that has been promoted
    for use within PostHog as a queryable ``DataWarehouseTable``.

    Each row owns a Temporal Schedule that periodically extracts the source
    table to parquet via ``COPY ... TO 's3://...'`` and refreshes the linked
    ``DataWarehouseTable``. v1 is full-refresh only.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        RUNNING = "running", "Running"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)

    source_schema_name = models.CharField(
        max_length=255,
        help_text="Schema name of the source table in the customer's DuckLake catalog",
    )
    source_table_name = models.CharField(
        max_length=255,
        help_text="Table name of the source table in the customer's DuckLake catalog",
    )

    data_warehouse_table = models.ForeignKey(
        "data_warehouse.DataWarehouseTable",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="managed_warehouse_promoted_tables",
        help_text="The DataWarehouseTable PostHog uses to query the promoted parquet snapshot",
    )

    sync_frequency_interval = models.DurationField(
        default=timedelta(hours=1),
        help_text="How often to refresh the promoted parquet snapshot",
    )

    status = models.CharField(
        max_length=32,
        choices=Status.choices,
        default=Status.PENDING,
    )
    last_error = models.TextField(null=True, blank=True)
    last_run_started_at = models.DateTimeField(null=True, blank=True)
    last_synced_at = models.DateTimeField(null=True, blank=True)
    row_count = models.BigIntegerField(null=True, blank=True)
    size_in_s3_mib = models.FloatField(null=True, blank=True)

    last_url_pattern = models.CharField(
        max_length=500,
        null=True,
        blank=True,
        help_text="The url_pattern most recently written to. Used by cleanup to delete the prior run.",
    )

    deleted = models.BooleanField(default=False)

    __repr__ = sane_repr("team_id", "source_schema_name", "source_table_name")

    class Meta:
        db_table = "posthog_managedwarehousepromotedtable"
        verbose_name = "Managed warehouse promoted table"
        verbose_name_plural = "Managed warehouse promoted tables"
        constraints = [
            models.UniqueConstraint(
                fields=["team", "source_schema_name", "source_table_name"],
                condition=models.Q(deleted=False),
                name="unique_managed_warehouse_promoted_table_per_team",
            ),
        ]

    @property
    def schedule_id(self) -> str:
        return f"managed-warehouse-promote-{self.id}"
