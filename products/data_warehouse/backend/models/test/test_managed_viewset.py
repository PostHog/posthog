import pytest
from posthog.test.base import BaseTest

from django.db import IntegrityError

from posthog.schema import RevenueAnalyticsEventItem, RevenueCurrencyPropertyConfig

from products.data_warehouse.backend.models import DataWarehouseManagedViewSet, DataWarehouseSavedQuery
from products.data_warehouse.backend.types import DataWarehouseManagedViewSetKind


class TestDataWarehouseManagedViewSetModel(BaseTest):
    def setUp(self):
        super().setUp()

        # Set up revenue analytics events configuration
        self.team.revenue_analytics_config.events = [
            RevenueAnalyticsEventItem(
                eventName="purchase",
                revenueProperty="amount",
                currencyAwareDecimal=True,
                revenueCurrencyProperty=RevenueCurrencyPropertyConfig(static="USD"),
            ),
            RevenueAnalyticsEventItem(
                eventName="subscription_charge",
                revenueProperty="price",
                currencyAwareDecimal=False,
                revenueCurrencyProperty=RevenueCurrencyPropertyConfig(property="currency"),
                productProperty="product_id",
            ),
        ]
        self.team.revenue_analytics_config.save()

    def test_sync_views_creates_views(self):
        """Test that enabling managed viewset creates the expected views"""
        managed_viewset = DataWarehouseManagedViewSet.objects.create(
            team=self.team,
            kind=DataWarehouseManagedViewSetKind.REVENUE_ANALYTICS,
        )

        # Call sync_views to create the views
        managed_viewset.sync_views()

        # Check that views were created
        views = DataWarehouseSavedQuery.objects.filter(
            team=self.team,
            managed_viewset__kind=DataWarehouseManagedViewSetKind.REVENUE_ANALYTICS,
        ).exclude(deleted=True)

        # Should have views for each event (purchase, subscription_charge) and each view type
        # Each event should generate 6 view types: customer, charge, subscription, revenue_item, product, mrr
        expected_view_count = 2 * 6  # 2 events * 6 types
        assert views.count() >= expected_view_count

        # Check that views have the expected structure
        for view in views:
            assert view.is_materialized
            assert view.query is not None
            assert view.columns is not None
            assert view.external_tables is not None
            assert "HogQLQuery" in view.query.get("kind", "")  # type: ignore

        expected_view_names = sorted(
            [
                "revenue_analytics.events.purchase.charge_events_revenue_view",
                "revenue_analytics.events.purchase.customer_events_revenue_view",
                "revenue_analytics.events.purchase.mrr_events_revenue_view",
                "revenue_analytics.events.purchase.revenue_item_events_revenue_view",
                "revenue_analytics.events.purchase.product_events_revenue_view",
                "revenue_analytics.events.purchase.subscription_events_revenue_view",
                "revenue_analytics.events.subscription_charge.charge_events_revenue_view",
                "revenue_analytics.events.subscription_charge.customer_events_revenue_view",
                "revenue_analytics.events.subscription_charge.mrr_events_revenue_view",
                "revenue_analytics.events.subscription_charge.product_events_revenue_view",
                "revenue_analytics.events.subscription_charge.revenue_item_events_revenue_view",
                "revenue_analytics.events.subscription_charge.subscription_events_revenue_view",
            ]
        )

        assert sorted([view.name for view in views]) == expected_view_names

    def test_sync_views_updates_existing_views(self):
        """Test that sync_views updates query and columns for existing views"""
        # First, create a managed viewset and some views
        managed_viewset = DataWarehouseManagedViewSet.objects.create(
            team=self.team,
            kind=DataWarehouseManagedViewSetKind.REVENUE_ANALYTICS,
        )

        # Create a view with old query/columns
        old_query = {"kind": "HogQLQuery", "query": "SELECT 1 as old_column"}
        old_columns = {"old_column": {"hogql": "String", "clickhouse": "String", "valid": True}}

        saved_query = DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="revenue_analytics.events.purchase.customer_events_revenue_view",
            query=old_query,
            columns=old_columns,
            managed_viewset=managed_viewset,
            is_materialized=True,
        )

        # Now call sync_views
        managed_viewset.sync_views()

        # Check that the view was updated
        saved_query.refresh_from_db()
        assert saved_query.query != old_query
        assert saved_query.columns != old_columns
        assert saved_query.external_tables is not None  # Was unset, guarantee we've set it
        assert "HogQLQuery" in saved_query.query.get("kind", "")  # type: ignore

    def test_delete_with_views(self):
        """Test that delete_with_views properly deletes the managed viewset and marks views as deleted"""
        managed_viewset = DataWarehouseManagedViewSet.objects.create(
            team=self.team,
            kind=DataWarehouseManagedViewSetKind.REVENUE_ANALYTICS,
        )

        # Create some views associated with the managed viewset
        view1 = DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="test_view_1",
            query={"kind": "HogQLQuery", "query": "SELECT 1"},
            managed_viewset=managed_viewset,
            created_by=self.user,
        )
        view2 = DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="test_view_2",
            query={"kind": "HogQLQuery", "query": "SELECT 2"},
            managed_viewset=managed_viewset,
            created_by=self.user,
        )

        # Delete the managed viewset with its views
        managed_viewset.delete_with_views()

        # Check that the managed viewset is deleted
        assert not DataWarehouseManagedViewSet.objects.filter(id=managed_viewset.id).exists()

        # Check that views are marked as deleted
        view1.refresh_from_db()
        view2.refresh_from_db()
        assert view1.deleted
        assert view2.deleted
        assert view1.deleted_at is not None
        assert view2.deleted_at is not None

    def test_managed_viewset_creation(self):
        """Test basic managed viewset creation"""
        managed_viewset = DataWarehouseManagedViewSet.objects.create(
            team=self.team,
            kind=DataWarehouseManagedViewSetKind.REVENUE_ANALYTICS,
        )

        assert managed_viewset.team == self.team
        assert managed_viewset.kind == DataWarehouseManagedViewSetKind.REVENUE_ANALYTICS
        assert managed_viewset.id is not None
        assert managed_viewset.created_at is not None

    def test_managed_viewset_unique_constraint(self):
        """Test that managed viewset has unique constraint on team and kind"""
        # Create first managed viewset
        DataWarehouseManagedViewSet.objects.create(
            team=self.team,
            kind=DataWarehouseManagedViewSetKind.REVENUE_ANALYTICS,
        )

        # Try to create another with same team and kind - should raise IntegrityError
        with pytest.raises(IntegrityError):
            DataWarehouseManagedViewSet.objects.create(
                team=self.team,
                kind=DataWarehouseManagedViewSetKind.REVENUE_ANALYTICS,
            )
