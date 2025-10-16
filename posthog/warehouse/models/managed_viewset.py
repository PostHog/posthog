from django.db import models, transaction

import structlog

from posthog.hogql.database.models import DecimalDatabaseField

from posthog.models.team import Team
from posthog.models.utils import CreatedMetaFields, UpdatedMetaFields, UUIDTModel

logger = structlog.get_logger(__name__)


class ManagedViewSet(CreatedMetaFields, UpdatedMetaFields, UUIDTModel):
    class Kind(models.TextChoices):
        REVENUE_ANALYTICS = "revenue_analytics", "Revenue Analytics"

    team = models.ForeignKey(Team, on_delete=models.CASCADE)
    kind = models.CharField(max_length=64, choices=Kind.choices)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["team", "kind"],
                name="unique_managed_viewset_team_kind",
            )
        ]

    def sync_views(self) -> None:
        """
        Syncs DataWarehouseSavedQuery views for revenue analytics.

        Reuses build_all_revenue_analytics_views() from create_hogql_database logic.
        For each source (events + external data sources):
          - Creates 5 views: customer, charge, subscription, revenue_item, product

        Updates managed_viewset_id on all created/updated views.
        Deletes views that are no longer referenced.
        Materializes views by default.
        """
        from datetime import timedelta

        from posthog.warehouse.data_load.saved_query_service import sync_saved_query_workflow
        from posthog.warehouse.models.datawarehouse_saved_query import DataWarehouseSavedQuery

        from products.revenue_analytics.backend.views.orchestrator import build_all_revenue_analytics_views

        logger.info("sync_views_started", team_id=self.team_id, kind=self.kind)

        expected_views = build_all_revenue_analytics_views(self.team)
        expected_view_names = {view.name for view in expected_views}

        views_created = 0
        views_updated = 0
        views_scheduled = 0

        with transaction.atomic():
            for view in expected_views:
                columns = {}
                for field_name, field_obj in view.fields.items():
                    hogql_type = type(field_obj).__name__
                    clickhouse_type = self._get_clickhouse_type(field_obj)
                    columns[field_name] = {
                        "hogql": hogql_type,
                        "clickhouse": clickhouse_type,
                        "valid": True,
                    }

                query_dict = {
                    "kind": "HogQLQuery",
                    "query": view.query,
                }

                saved_query, created = DataWarehouseSavedQuery.objects.update_or_create(
                    name=view.name,
                    team=self.team,
                    managed_viewset=self,
                    defaults={
                        "query": query_dict,
                        "columns": columns,
                        "is_materialized": True,
                        "sync_frequency_interval": timedelta(hours=6),
                    },
                )

                # Always update query and columns, even for existing objects
                if not created:
                    saved_query.query = query_dict
                    saved_query.columns = columns
                    saved_query.save(update_fields=["query", "columns"])

                if created:
                    views_created += 1
                else:
                    views_updated += 1

                if created:
                    try:
                        sync_saved_query_workflow(saved_query, create=True)
                        views_scheduled += 1
                    except Exception as e:
                        logger.warning(
                            "failed_to_schedule_saved_query",
                            team_id=self.team_id,
                            saved_query_id=str(saved_query.id),
                            error=str(e),
                        )

            orphaned_views = (
                DataWarehouseSavedQuery.objects.filter(
                    team=self.team,
                    managed_viewset=self,
                )
                .exclude(name__in=expected_view_names)
                .exclude(deleted=True)
            )

            views_deleted = 0
            for orphaned_view in orphaned_views:
                try:
                    orphaned_view.revert_materialization()
                    orphaned_view.soft_delete()
                    views_deleted += 1
                except Exception as e:
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
                views_scheduled=views_scheduled,
                views_deleted=views_deleted,
            )

    def delete_with_views(self) -> int:
        """
        Delete the managed viewset and soft delete all related views.
        Reverts materialization for each view before soft deletion.
        Returns the number of views deleted.
        """
        from posthog.warehouse.models.datawarehouse_saved_query import DataWarehouseSavedQuery

        related_views = DataWarehouseSavedQuery.objects.filter(
            team=self.team,
            managed_viewset=self,
        ).exclude(deleted=True)

        views_deleted = 0
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

        logger.info(
            "managed_viewset_deleted_with_views",
            team_id=self.team_id,
            kind=self.kind,
            views_deleted=views_deleted,
        )

        self.delete()
        return views_deleted

    @staticmethod
    def _get_clickhouse_type(field) -> str:
        """Convert HogQL field type to ClickHouse type string."""
        from posthog.hogql.database.models import (
            BooleanDatabaseField,
            DateDatabaseField,
            DateTimeDatabaseField,
            FloatDatabaseField,
            IntegerDatabaseField,
            StringDatabaseField,
        )

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
