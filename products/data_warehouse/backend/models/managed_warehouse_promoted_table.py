from __future__ import annotations

from django.db import models

from posthog.models.utils import CreatedMetaFields, UpdatedMetaFields, UUIDTModel, sane_repr


class ManagedWarehousePromotedTable(CreatedMetaFields, UpdatedMetaFields, UUIDTModel):
    """A table in a customer's managed DuckLake warehouse that has been promoted
    for querying within PostHog.

    Unlike sync'd ``DataWarehouseTable`` rows, promoted managed-warehouse tables
    are queried live via ClickHouse's ``postgresql()`` table function over the
    customer's duckgres (DuckDB-over-Postgres) instance. Credentials live in
    ``posthog/ducklake`` (per-org ``DuckgresServer``) — this model only stores
    *which* tables are exposed, not how to connect to them.
    """

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)

    source_schema_name = models.CharField(
        max_length=255,
        help_text="Schema name of the source table in the customer's DuckLake catalog.",
    )
    source_table_name = models.CharField(
        max_length=255,
        help_text="Table name of the source table in the customer's DuckLake catalog.",
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
    def qualified_source_name(self) -> str:
        return f"{self.source_schema_name}.{self.source_table_name}"
