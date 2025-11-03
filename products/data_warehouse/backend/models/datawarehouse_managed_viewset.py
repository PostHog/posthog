from dataclasses import dataclass
from datetime import timedelta
from typing import Any, cast

from django.db import models, transaction

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
from products.data_warehouse.backend.models.modeling import DataWarehouseModelPath
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
    kind = models.CharField(max_length=64, choices=DataWarehouseManagedViewSetKind.choices)

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
        from products.data_warehouse.backend.data_load.saved_query_service import sync_saved_query_workflow

        expected_views: list[ExpectedView] = []
        if self.kind == DataWarehouseManagedViewSetKind.REVENUE_ANALYTICS:
            expected_views = self._get_expected_views_for_revenue_analytics()
        else:
            raise DataWarehouseManagedViewSet.UnsupportedViewsetKind(cast(DataWarehouseManagedViewSetKind, self.kind))

        # NOTE: Views that depend on other views MUST be placed AFTER the views they depend on
        # or else we'll fail to build the paths properly.
        expected_view_names = [view.name for view in expected_views]

        views_created = 0
        views_updated = 0

        with transaction.atomic():
            for view in expected_views:
                # Get the one from the DB or create a new one if doesn't exist yet
                saved_query = DataWarehouseSavedQuery.objects.filter(
                    name=view.name, team=self.team, managed_viewset=self
                ).first()
                if saved_query:
                    created = False
                else:
                    saved_query = DataWarehouseSavedQuery(name=view.name, team=self.team, managed_viewset=self)
                    created = True

                # Do NOT use get_columns because it runs the query, and these are possibly heavy
                saved_query.query = view.query
                saved_query.columns = view.columns
                saved_query.external_tables = saved_query.s3_tables
                saved_query.is_materialized = True
                saved_query.sync_frequency_interval = timedelta(hours=12)
                saved_query.save()

                # Make sure paths properly exist both on creation and update
                # This is required for Temporal to properly build the DAG
                if not DataWarehouseModelPath.objects.filter(team=saved_query.team, saved_query=saved_query).exists():
                    DataWarehouseModelPath.objects.create_from_saved_query(saved_query)
                else:
                    DataWarehouseModelPath.objects.update_from_saved_query(saved_query)

                if created:
                    views_created += 1
                else:
                    views_updated += 1

                if created:
                    try:
                        sync_saved_query_workflow(saved_query, create=True)
                    except Exception as e:
                        capture_exception(e, {"managed_viewset_id": self.id, "view_name": saved_query.name})
                        logger.warning(
                            "failed_to_schedule_saved_query",
                            team_id=self.team_id,
                            saved_query_id=str(saved_query.id),
                            error=str(e),
                        )

                        # Disable materialization for this view if we failed to schedule the workflow
                        # TODO: Should we have a cron job that re-enables materialization for managed viewset-based views
                        # that failed to schedule?
                        saved_query.is_materialized = False
                        saved_query.save(update_fields=["is_materialized"])

            views_deleted = 0
            orphaned_views = self.saved_queries.exclude(name__in=expected_view_names).exclude(deleted=True)
            for orphaned_view in orphaned_views:
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
            raise DataWarehouseManagedViewSet.UnsupportedViewsetKind(self.kind)

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
          - Creates 5 views: customer, charge, subscription, revenue_item, product
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
