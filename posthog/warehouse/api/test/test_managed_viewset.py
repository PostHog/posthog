from posthog.test.base import APIBaseTest

from rest_framework import status

from posthog.schema import RevenueAnalyticsEventItem, RevenueCurrencyPropertyConfig

from posthog.warehouse.models import DataWarehouseSavedQuery, ManagedViewSet


class TestManagedViewSetAPI(APIBaseTest):
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

    def test_enable_managed_viewset(self):
        response = self.client.put(
            f"/api/environments/{self.team.id}/managed_viewsets/revenue_analytics/",
            {"enabled": True},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["enabled"], True)
        self.assertEqual(response.json()["kind"], "revenue_analytics")

        self.assertTrue(
            ManagedViewSet.objects.filter(team=self.team, kind=ManagedViewSet.Kind.REVENUE_ANALYTICS).exists()
        )

    def test_enable_managed_viewset_idempotent(self):
        response1 = self.client.put(
            f"/api/environments/{self.team.id}/managed_viewsets/revenue_analytics/",
            {"enabled": True},
        )
        response2 = self.client.put(
            f"/api/environments/{self.team.id}/managed_viewsets/revenue_analytics/",
            {"enabled": True},
        )

        self.assertEqual(response1.status_code, status.HTTP_200_OK)
        self.assertEqual(response2.status_code, status.HTTP_200_OK)

        self.assertEqual(ManagedViewSet.objects.filter(team=self.team).count(), 1)

    def test_disable_managed_viewset(self):
        managed_viewset = ManagedViewSet.objects.create(
            team=self.team,
            kind=ManagedViewSet.Kind.REVENUE_ANALYTICS,
        )

        saved_query = DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="test_view",
            query={"kind": "HogQLQuery", "query": "SELECT 1"},
            managed_viewset=managed_viewset,
        )

        response = self.client.put(
            f"/api/environments/{self.team.id}/managed_viewsets/revenue_analytics/",
            {"enabled": False},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["enabled"], False)
        self.assertFalse(ManagedViewSet.objects.filter(id=managed_viewset.id).exists())

        saved_query.refresh_from_db()
        self.assertTrue(saved_query.deleted)
        self.assertIsNotNone(saved_query.deleted_at)

    def test_disable_already_disabled_viewset(self):
        response = self.client.put(
            f"/api/environments/{self.team.id}/managed_viewsets/revenue_analytics/",
            {"enabled": False},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["enabled"], False)

    def test_invalid_kind(self):
        response = self.client.put(
            f"/api/environments/{self.team.id}/managed_viewsets/invalid_kind/",
            {"enabled": True},
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_sync_views_creates_views(self):
        """Test that enabling managed viewset creates the expected views"""
        response = self.client.put(
            f"/api/environments/{self.team.id}/managed_viewsets/revenue_analytics/",
            {"enabled": True},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Check that views were created
        views = DataWarehouseSavedQuery.objects.filter(
            team=self.team,
            managed_viewset__kind=ManagedViewSet.Kind.REVENUE_ANALYTICS,
        ).exclude(deleted=True)

        # Should have views for each event (purchase, subscription_charge) and each view type
        # Each event should generate 5 view types: customer, charge, subscription, revenue_item, product
        # Plus "all" views for each type
        expected_view_count = 2 * 5 + 5  # 2 events * 5 types + 5 "all" views
        self.assertGreaterEqual(views.count(), expected_view_count)

        # Check that views have the expected structure
        for view in views:
            self.assertTrue(view.is_materialized)
            self.assertIsNotNone(view.query)
            self.assertIsNotNone(view.columns)
            self.assertIn("HogQLQuery", view.query.get("kind", ""))  # type: ignore

        # TODO: There's a bug here, these shouldn't include the weird `no_property` bit
        # Will fix in a follow-up, not related to the changes that introduced this test
        expected_view_names = sorted(
            [
                "revenue_analytics.all.revenue_analytics_charge",
                "revenue_analytics.all.revenue_analytics_customer",
                "revenue_analytics.all.revenue_analytics_product",
                "revenue_analytics.all.revenue_analytics_revenue_item",
                "revenue_analytics.all.revenue_analytics_subscription",
                "revenue_analytics.events.purchase.charge_events_revenue_view",
                "revenue_analytics.events.purchase.customer_events_revenue_view",
                "revenue_analytics.events.purchase.revenue_item_events_revenue_view",
                "revenue_analytics.events.purchase_no_property.product_events_revenue_view",
                "revenue_analytics.events.purchase_no_property.subscription_events_revenue_view",
                "revenue_analytics.events.subscription_charge.charge_events_revenue_view",
                "revenue_analytics.events.subscription_charge.customer_events_revenue_view",
                "revenue_analytics.events.subscription_charge.product_events_revenue_view",
                "revenue_analytics.events.subscription_charge.revenue_item_events_revenue_view",
                "revenue_analytics.events.subscription_charge_no_property.subscription_events_revenue_view",
            ]
        )

        self.assertEqual(sorted([view.name for view in views]), expected_view_names)

    def test_sync_views_updates_existing_views(self):
        """Test that sync_views updates query and columns for existing views"""
        # First, create a managed viewset and some views
        managed_viewset = ManagedViewSet.objects.create(
            team=self.team,
            kind=ManagedViewSet.Kind.REVENUE_ANALYTICS,
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
        self.assertNotEqual(saved_query.query, old_query)
        self.assertNotEqual(saved_query.columns, old_columns)
        self.assertIn("HogQLQuery", saved_query.query.get("kind", ""))  # type: ignore

    def test_retrieve_managed_viewset_with_views(self):
        """Test retrieving a managed viewset that exists with views"""
        # Create a managed viewset
        managed_viewset = ManagedViewSet.objects.create(
            team=self.team,
            kind=ManagedViewSet.Kind.REVENUE_ANALYTICS,
        )

        # Create some saved queries associated with the managed viewset
        DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="test_view_1",
            query={"kind": "HogQLQuery", "query": "SELECT 1"},
            managed_viewset=managed_viewset,
            created_by=self.user,
        )
        DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="test_view_2",
            query={"kind": "HogQLQuery", "query": "SELECT 2"},
            managed_viewset=managed_viewset,
            created_by=self.user,
        )

        response = self.client.get(f"/api/environments/{self.team.id}/managed_viewsets/revenue_analytics/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()

        self.assertIn("views", data)
        self.assertIn("count", data)
        self.assertEqual(data["count"], 2)

        # Check that both views are returned with expected fields
        view_names = [view["name"] for view in data["views"]]
        self.assertIn("test_view_1", view_names)
        self.assertIn("test_view_2", view_names)

        # Check that each view has the expected fields
        for view in data["views"]:
            self.assertIn("id", view)
            self.assertIn("name", view)
            self.assertIn("created_at", view)
            self.assertIn("created_by_id", view)

    def test_retrieve_managed_viewset_without_views(self):
        """Test retrieving a managed viewset that exists but has no views"""
        # Create a managed viewset but no associated views
        ManagedViewSet.objects.create(
            team=self.team,
            kind=ManagedViewSet.Kind.REVENUE_ANALYTICS,
        )

        response = self.client.get(f"/api/environments/{self.team.id}/managed_viewsets/revenue_analytics/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()

        self.assertIn("views", data)
        self.assertIn("count", data)
        self.assertEqual(data["count"], 0)
        self.assertEqual(data["views"], [])

    def test_retrieve_managed_viewset_does_not_exist(self):
        """Test retrieving a managed viewset that doesn't exist"""
        response = self.client.get(f"/api/environments/{self.team.id}/managed_viewsets/revenue_analytics/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()

        self.assertIn("views", data)
        self.assertIn("count", data)
        self.assertEqual(data["count"], 0)
        self.assertEqual(data["views"], [])

    def test_retrieve_managed_viewset_excludes_deleted_views(self):
        """Test that deleted views are excluded from the response"""
        # Create a managed viewset
        managed_viewset = ManagedViewSet.objects.create(
            team=self.team,
            kind=ManagedViewSet.Kind.REVENUE_ANALYTICS,
        )

        # Create a non-deleted view
        active_view = DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="active_view",
            query={"kind": "HogQLQuery", "query": "SELECT 1"},
            managed_viewset=managed_viewset,
            created_by=self.user,
        )

        # Create a deleted view
        DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="deleted_view",
            query={"kind": "HogQLQuery", "query": "SELECT 2"},
            managed_viewset=managed_viewset,
            created_by=self.user,
            deleted=True,
        )

        response = self.client.get(f"/api/environments/{self.team.id}/managed_viewsets/revenue_analytics/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()

        self.assertEqual(data["count"], 1)
        self.assertEqual(len(data["views"]), 1)
        self.assertEqual(data["views"][0]["name"], "active_view")
        self.assertEqual(str(data["views"][0]["id"]), str(active_view.id))

    def test_retrieve_managed_viewset_invalid_kind(self):
        """Test retrieving with an invalid kind returns 400"""
        response = self.client.get(f"/api/environments/{self.team.id}/managed_viewsets/invalid_kind/")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        data = response.json()
        self.assertIn("detail", data)
        self.assertIn("Invalid kind", data["detail"])
