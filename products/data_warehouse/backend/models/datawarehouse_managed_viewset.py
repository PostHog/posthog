from dataclasses import dataclass
from datetime import timedelta
from typing import Any, cast

from django.db import connection, models, transaction

import structlog

from posthog.hogql.database.models import (
    BooleanDatabaseField,
    DateDatabaseField,
    DateTimeDatabaseField,
    DecimalDatabaseField,
    FieldOrTable,
    FloatDatabaseField,
    IntegerDatabaseField,
    StringDatabaseField,
)

from posthog.exceptions_capture import capture_exception
from posthog.models.utils import CreatedMetaFields, UpdatedMetaFields, UUIDTModel, sane_repr

from products.data_warehouse.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery
from products.data_warehouse.backend.types import DataWarehouseManagedViewSetKind
from products.revenue_analytics.backend.views.schemas import SCHEMAS as REVENUE_ANALYTICS_SCHEMAS

logger = structlog.get_logger(__name__)


@dataclass
class ExpectedView:
    name: str
    query: dict[str, Any]
    columns: dict[str, dict[str, Any]]


class DataWarehouseManagedViewSet(CreatedMetaFields, UpdatedMetaFields, UUIDTModel):
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    kind = models.CharField(max_length=64, choices=DataWarehouseManagedViewSetKind)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["team", "kind"],
                name="datawarehouse_unique_managed_viewset_team_kind",
            )
        ]
        db_table = "posthog_datawarehousemanagedviewset"

    class UnsupportedViewsetKind(ValueError):
        kind: DataWarehouseManagedViewSetKind

        def __init__(self, kind: DataWarehouseManagedViewSetKind):
            self.kind = kind
            super().__init__(f"Unsupported viewset kind: {self.kind}")

    def __str__(self) -> str:
        return f"DataWarehouseManagedViewSet({self.kind}) for Team {self.team.id}"

    __repr__ = sane_repr("team", "kind")

    def sync_views(self) -> None:
        """
        Syncs the views for the managed viewset.

        Updates managed_viewset_id on all created/updated views.
        Deletes views that are no longer referenced.
        Materializes views by default.
        """

        expected_views: list[ExpectedView] = []
        if self.kind == DataWarehouseManagedViewSetKind.REVENUE_ANALYTICS:
            expected_views = self._get_expected_views_for_revenue_analytics()
        else:
            raise DataWarehouseManagedViewSet.UnsupportedViewsetKind(cast(DataWarehouseManagedViewSetKind, self.kind))

        # NOTE: Views that depend on other views MUST be placed AFTER the views they depend on
        # or else we'll fail to build the paths properly.
        expected_view_names = [view.name for view in expected_views]

        # Pre-compute external_tables OUTSIDE the transaction. get_s3_tables is expensive:
        # it builds a HogQL Database context, parses, and resolves each query. Doing
        # this inside the transaction held row locks for seconds across all 6 views.
        # Build the database once and reuse it for all views.
        from posthog.hogql.database.database import Database

        database = Database.create_for(self.team.pk)
        external_tables_by_view: dict[str, list] = {}
        for view in expected_views:
            temp_sq = DataWarehouseSavedQuery(
                name=view.name,
                team=self.team,
                query=view.query,
                columns=view.columns,
            )
            try:
                external_tables_by_view[view.name] = temp_sq.get_s3_tables(database=database)
            except Exception as e:
                capture_exception(e, {"view_name": view.name, "team_id": self.team.pk})
                logger.warning(
                    "failed_to_compute_s3_tables",
                    team_id=self.team_id,
                    view_name=view.name,
                    error=str(e),
                )
                external_tables_by_view[view.name] = []

        views_created = 0
        views_updated = 0
        saved_queries_to_schedule: list[DataWarehouseSavedQuery] = []
        orphaned_views_to_revert: list[DataWarehouseSavedQuery] = []

        # Keep this transaction short: persist DB changes only. The post-commit work
        # (schedule_materialization → Temporal RPCs + DataWarehouseModelPath updates,
        # and orphan revert_materialization) runs outside the atomic block so row
        # locks on posthog_datawarehousesavedquery aren't held across synchronous
        # Temporal RPCs.
        with transaction.atomic():
            # Serialize concurrent sync_views calls for the same team+kind to prevent
            # deadlocks when multiple data source schemas complete simultaneously and
            # each tries to update the same set of saved queries.
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT pg_advisory_xact_lock(hashtext(%s)::bigint)",
                    [f"{self.team_id}_sync_views_{self.kind}"],
                )

            for view in expected_views:
                # Get the one from the DB or create a new one if doesn't exist yet
                saved_query = DataWarehouseSavedQuery.objects.filter(
                    name=view.name, team=self.team, managed_viewset=self
                ).first()
                if saved_query:
                    created = False
                else:
                    saved_query = DataWarehouseSavedQuery(
                        name=view.name,
                        team=self.team,
                        managed_viewset=self,
                        origin=DataWarehouseSavedQuery.Origin.MANAGED_VIEWSET,
                    )
                    created = True

                # Do NOT use get_columns because it runs the query, and these are possibly heavy
                saved_query.query = view.query
                saved_query.columns = view.columns
                saved_query.external_tables = external_tables_by_view[view.name]
                saved_query.is_materialized = True
                saved_query.sync_frequency_interval = timedelta(hours=12)

                saved_query.save()
                saved_queries_to_schedule.append(saved_query)

                if created:
                    views_created += 1
                else:
                    views_updated += 1

            orphaned_views_to_revert = list(
                self.saved_queries.exclude(name__in=expected_view_names).exclude(deleted=True)
            )

        for saved_query in saved_queries_to_schedule:
            try:
                saved_query.schedule_materialization()
            except Exception as e:
                capture_exception(e, {"managed_viewset_id": self.id, "view_name": saved_query.name})
                logger.warning(
                    "failed_to_schedule_managed_view",
                    team_id=self.team_id,
                    view_name=saved_query.name,
                    error=str(e),
                )

        views_deleted = 0
        for orphaned_view in orphaned_views_to_revert:
            try:
                orphaned_view.revert_materialization()
                orphaned_view.soft_delete()
                views_deleted += 1
            except Exception as e:
                capture_exception(e, {"managed_viewset_id": self.id, "view_name": orphaned_view.name})
                logger.warning(
                    "failed_to_delete_orphaned_view",
                    team_id=self.team_id,
                    view_name=orphaned_view.name,
                    error=str(e),
                )

        logger.info(
            "sync_views_completed",
            team_id=self.team_id,
            kind=self.kind,
            views_created=views_created,
            views_updated=views_updated,
            views_deleted=views_deleted,
        )

    def delete_with_views(self) -> int:
        """
        Delete the managed viewset and soft delete all related views.
        Reverts materialization for each view before soft deletion.
        Returns the number of views deleted.
        """
        related_views = self.saved_queries.exclude(deleted=True)

        views_deleted = 0
        with transaction.atomic():
            for view in related_views:
                try:
                    view.revert_materialization()
                    view.soft_delete()
                    views_deleted += 1
                except Exception as e:
                    logger.warning(
                        "failed_to_delete_managed_view",
                        team_id=self.team_id,
                        view_name=view.name,
                        error=str(e),
                    )

                    capture_exception(e, {"managed_viewset_id": self.id, "view_name": view.name})

            logger.info(
                "managed_viewset_deleted_with_views",
                team_id=self.team_id,
                kind=self.kind,
                views_deleted=views_deleted,
            )

            self.delete()
        return views_deleted

    def to_saved_query_metadata(self, name: str):
        if self.kind != DataWarehouseManagedViewSetKind.REVENUE_ANALYTICS:
            raise DataWarehouseManagedViewSet.UnsupportedViewsetKind(cast(DataWarehouseManagedViewSetKind, self.kind))

        return {
            "managed_viewset_kind": self.kind,
            "revenue_analytics_kind": next(
                (
                    schema.kind
                    for schema in REVENUE_ANALYTICS_SCHEMAS.values()
                    if name.endswith(schema.events_suffix) or name.endswith(schema.source_suffix)
                ),
                None,
            ),
        }

    def _get_expected_views_for_revenue_analytics(self) -> list[ExpectedView]:
        """
        Reuses build_all_revenue_analytics_views() from Database.create_for logic.
        For each source (events + external data sources):
          - Creates 6 views: customer, charge, subscription, revenue_item, product, mrr
        """

        from products.revenue_analytics.backend.views.orchestrator import build_all_revenue_analytics_views

        expected_views = build_all_revenue_analytics_views(self.team)
        return [
            ExpectedView(
                name=view.name,
                query={"kind": "HogQLQuery", "query": view.query},
                columns=self._get_columns_from_fields(view.fields),
            )
            for view in expected_views
        ]

    @staticmethod
    def _get_columns_from_fields(fields: dict[str, FieldOrTable]) -> dict[str, dict[str, Any]]:
        return {
            field_name: {
                "hogql": type(field_obj).__name__,
                "clickhouse": DataWarehouseManagedViewSet._get_clickhouse_type(field_obj),
                "valid": True,
            }
            for field_name, field_obj in fields.items()
        }

    @staticmethod
    def _get_clickhouse_type(field) -> str:
        """Convert HogQL field type to ClickHouse type string."""

        # NOTE: This function has a really bad smell
        # These types won't usually map appropriately because it's hard to predict what Clickhouse is actually storing
        # but we need these to exist if we want the `SavedQuery` to be saved correctly.
        # We do NOT use these types extensively so it's not a big deal if they aren't 100% accurate,
        # but we should be mindful of this function and consider removing the need for it in the future.
        #
        # If the types here prove to be wrong, we can easily run the following script to update the types:
        # ```python
        # from products.data_warehouse.backend.models.datawarehouse_managed_viewset import DataWarehouseManagedViewSet
        # for viewset in DataWarehouseManagedViewSet.objects.iterator():
        #     viewset.sync_views()
        # ```

        if isinstance(field, StringDatabaseField):
            type = "String"
        elif isinstance(field, IntegerDatabaseField):
            type = "Int64"
        elif isinstance(field, FloatDatabaseField):
            type = "Float64"
        elif isinstance(field, DecimalDatabaseField):
            type = "Decimal64(10)"
        elif isinstance(field, DateTimeDatabaseField):
            type = "DateTime64(6, 'UTC')"
        elif isinstance(field, BooleanDatabaseField):
            type = "Boolean"
        elif isinstance(field, DateDatabaseField):
            type = "Date"
        else:
            type = "String"

        if field.is_nullable():
            type = f"Nullable({type})"

        return type
