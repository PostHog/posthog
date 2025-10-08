import logging
from datetime import timedelta
from typing import Any, Optional

from django.db import models, transaction

from posthog.schema import RevenueAnalyticsEventItem

from posthog.models.team import Team
from posthog.models.utils import CreatedMetaFields, UUIDModel
from posthog.warehouse.models.datawarehouse_saved_query import DataWarehouseSavedQuery
from posthog.warehouse.models.external_data_source import ExternalDataSource
from posthog.warehouse.models.util import convert_hogql_type_to_clickhouse_type

from products.revenue_analytics.backend.views import (
    RevenueAnalyticsBaseView,
    RevenueAnalyticsChargeView,
    RevenueAnalyticsCustomerView,
    RevenueAnalyticsProductView,
    RevenueAnalyticsRevenueItemView,
    RevenueAnalyticsSubscriptionView,
)

logger = logging.getLogger(__name__)


class DataWarehouseManagedView(CreatedMetaFields, UUIDModel):
    class Kind(models.TextChoices):
        """Possible kinds of this Managed view."""

        REVENUE_ANALYTICS_CHARGE = "Revenue Analytics Charge"
        REVENUE_ANALYTICS_CUSTOMER = "Revenue Analytics Customer"
        REVENUE_ANALYTICS_PRODUCT = "Revenue Analytics Product"
        REVENUE_ANALYTICS_SUBSCRIPTION = "Revenue Analytics Subscription"
        REVENUE_ANALYTICS_REVENUE_ITEM = "Revenue Analytics Revenue Item"
        # REVENUE_ANALYTICS_MRR = "Revenue Analytics MRR"

    team = models.ForeignKey(Team, on_delete=models.CASCADE)
    external_data_source = models.ForeignKey("posthog.ExternalDataSource", on_delete=models.CASCADE, null=True)
    event_source = models.CharField(max_length=128, null=True)
    kind = models.CharField(max_length=128, choices=Kind.choices)

    # there's also a reverse relationship to DataWarehouseSavedQuery
    # the field is stored in the DataWarehouseSavedQuery model to allow efficient presence checks

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["team", "external_data_source", "kind"],
                name="posthog_datawarehouse_view_package_uniqueness",
            )
        ]


REVENUE_ANALYTICS_KINDS: list[DataWarehouseManagedView.Kind] = [
    DataWarehouseManagedView.Kind.REVENUE_ANALYTICS_CHARGE,
    DataWarehouseManagedView.Kind.REVENUE_ANALYTICS_CUSTOMER,
    DataWarehouseManagedView.Kind.REVENUE_ANALYTICS_PRODUCT,
    DataWarehouseManagedView.Kind.REVENUE_ANALYTICS_SUBSCRIPTION,
    DataWarehouseManagedView.Kind.REVENUE_ANALYTICS_REVENUE_ITEM,
    # DataWarehouseManagedView.Kind.REVENUE_ANALYTICS_MRR,
]


def _get_managed_view_query(
    kind: DataWarehouseManagedView.Kind,
    team: Team,
    source: Optional[ExternalDataSource] = None,
    event_item: Optional[RevenueAnalyticsEventItem] = None,
) -> tuple[str, str, dict[str, Any]]:
    """Get the name, query, and columns for a managed view using the revenue analytics orchestrator."""
    from products.revenue_analytics.backend.views.orchestrator import get_managed_view_query

    if kind in REVENUE_ANALYTICS_KINDS:
        return get_managed_view_query(
            kind=kind.value,
            team=team,
            source=source,
            event_item=event_item,
        )

    raise ValueError(f"Invalid kind: {kind}")


def _create_managed_view(
    team: Team,
    kind: DataWarehouseManagedView.Kind,
    *,
    query: str,
    name: str,
    columns: dict[str, Any],
    source_id: Optional[str] = None,
    event_source_name: Optional[str] = None,
):
    with transaction.atomic():
        managed_view, created = DataWarehouseManagedView.objects.get_or_create(
            team=team,
            kind=kind,
            external_data_source_id=source_id,
            event_source=event_source_name,
        )

        # If the managed view is created, create a saved query for it
        if created:
            DataWarehouseSavedQuery.objects.create(
                team=team,
                managed_view=managed_view,
                name=name,
                query={"kind": "HogQLQuery", "query": query},
                columns=columns,
                is_materialized=True,
                sync_frequency_interval=timedelta(hours=6),
            )

    return managed_view


def delete_revenue_analytics_managed_views(team: Team):
    """
    Delete all managed views for revenue analytics entities for a team.
    """
    for managed_view in DataWarehouseManagedView.objects.filter(
        team=team, kind__in=REVENUE_ANALYTICS_KINDS
    ).prefetch_related("saved_query"):
        managed_view.saved_query.soft_delete()
        managed_view.saved_query.revert_materialization()
        managed_view.delete()


def create_revenue_analytics_managed_views(team: Team):
    """
    Create managed views for revenue analytics entities for all revenue-enabled external data sources and events.
    """
    from products.revenue_analytics.backend.views.orchestrator import build_all_revenue_analytics_views

    revenue_analytics_view_to_managed_view_kind: dict[type[RevenueAnalyticsBaseView], DataWarehouseManagedView.Kind] = {
        RevenueAnalyticsChargeView: DataWarehouseManagedView.Kind.REVENUE_ANALYTICS_CHARGE,
        RevenueAnalyticsCustomerView: DataWarehouseManagedView.Kind.REVENUE_ANALYTICS_CUSTOMER,
        RevenueAnalyticsProductView: DataWarehouseManagedView.Kind.REVENUE_ANALYTICS_PRODUCT,
        RevenueAnalyticsSubscriptionView: DataWarehouseManagedView.Kind.REVENUE_ANALYTICS_SUBSCRIPTION,
        RevenueAnalyticsRevenueItemView: DataWarehouseManagedView.Kind.REVENUE_ANALYTICS_REVENUE_ITEM,
    }

    all_views = build_all_revenue_analytics_views(team)
    for view in all_views:
        columns = {
            field_name: {
                "hogql": field.__name__,
                "clickhouse": convert_hogql_type_to_clickhouse_type(field),
                "valid": True,
            }
            for field_name, field in view.fields.items()
        }

        _create_managed_view(
            team,
            revenue_analytics_view_to_managed_view_kind[type(view)],
            name=view.name,
            query=view.query,
            columns=columns,
            source_id=view.source_id,
            event_source_name=view.event_name,
        )
