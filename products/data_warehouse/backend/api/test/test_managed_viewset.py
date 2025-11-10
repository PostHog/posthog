from posthog.test.base import APIBaseTest

from rest_framework import status

from posthog.schema import RevenueAnalyticsEventItem, RevenueCurrencyPropertyConfig

from products.data_warehouse.backend.models import DataWarehouseManagedViewSet, DataWarehouseSavedQuery
from products.data_warehouse.backend.types import DataWarehouseManagedViewSetKind


class TestDataWarehouseManagedViewSetAPI(APIBaseTest):
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
            DataWarehouseManagedViewSet.objects.filter(
                team=self.team, kind=DataWarehouseManagedViewSetKind.REVENUE_ANALYTICS
            ).exists()
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

        self.assertEqual(DataWarehouseManagedViewSet.objects.filter(team=self.team).count(), 1)

    def test_disable_managed_viewset(self):
        managed_viewset = DataWarehouseManagedViewSet.objects.create(
            team=self.team,
            kind=DataWarehouseManagedViewSetKind.REVENUE_ANALYTICS,
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
        self.assertFalse(DataWarehouseManagedViewSet.objects.filter(id=managed_viewset.id).exists())

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

    def test_retrieve_managed_viewset_with_views(self):
        """Test retrieving a managed viewset that exists with views"""
        # Create a managed viewset
        managed_viewset = DataWarehouseManagedViewSet.objects.create(
            team=self.team,
            kind=DataWarehouseManagedViewSetKind.REVENUE_ANALYTICS,
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
        DataWarehouseManagedViewSet.objects.create(
            team=self.team,
            kind=DataWarehouseManagedViewSetKind.REVENUE_ANALYTICS,
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
        managed_viewset = DataWarehouseManagedViewSet.objects.create(
            team=self.team,
            kind=DataWarehouseManagedViewSetKind.REVENUE_ANALYTICS,
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
