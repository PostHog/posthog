from posthog.test.base import APIBaseTest

from rest_framework import status

from posthog.schema import RevenueAnalyticsEventItem, RevenueCurrencyPropertyConfig

from products.data_warehouse.backend.models import DataWarehouseManagedViewSet, DataWarehouseSavedQuery
from products.data_warehouse.backend.types import DataWarehouseManagedViewSetKind


# Define child classes for each managed viewset kind
# and define the special `kind`, `endpoint` and `expected_count` attributes
class TestDataWarehouseManagedViewSetAPIBase(APIBaseTest):
    __test__ = False

    kind: DataWarehouseManagedViewSetKind
    endpoint: str
    expected_count: int

    def test_enable_managed_viewset(self):
        response = self.client.put(
            f"/api/environments/{self.team.id}/managed_viewsets/{self.endpoint}/",
            {"enabled": True},
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["enabled"] == True
        assert response.json()["kind"] == self.endpoint

        assert DataWarehouseManagedViewSet.objects.filter(team=self.team, kind=self.kind).count() == 1

        assert DataWarehouseSavedQuery.objects.filter(team=self.team, managed_viewset__kind=self.kind).count() == self.expected_count

    def test_enable_managed_viewset_idempotent(self):
        response1 = self.client.put(
            f"/api/environments/{self.team.id}/managed_viewsets/{self.endpoint}/",
            {"enabled": True},
        )
        response2 = self.client.put(
            f"/api/environments/{self.team.id}/managed_viewsets/{self.endpoint}/",
            {"enabled": True},
        )

        assert response1.status_code == status.HTTP_200_OK
        assert response2.status_code == status.HTTP_200_OK

        assert DataWarehouseManagedViewSet.objects.filter(team=self.team).count() == 1

    def test_disable_managed_viewset(self):
        managed_viewset = DataWarehouseManagedViewSet.objects.create(
            team=self.team,
            kind=self.kind,
        )

        saved_query = DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="test_view",
            query={"kind": "HogQLQuery", "query": "SELECT 1"},
            managed_viewset=managed_viewset,
        )

        response = self.client.put(
            f"/api/environments/{self.team.id}/managed_viewsets/{self.endpoint}/",
            {"enabled": False},
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["enabled"] == False
        assert not DataWarehouseManagedViewSet.objects.filter(id=managed_viewset.id).exists()

        saved_query.refresh_from_db()
        assert saved_query.deleted
        assert saved_query.deleted_at is not None

    def test_disable_already_disabled_viewset(self):
        response = self.client.put(
            f"/api/environments/{self.team.id}/managed_viewsets/{self.endpoint}/",
            {"enabled": False},
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["enabled"] == False

    def test_retrieve_managed_viewset_with_views(self):
        """Test retrieving a managed viewset that exists with views"""
        # Create a managed viewset
        managed_viewset = DataWarehouseManagedViewSet.objects.create(
            team=self.team,
            kind=self.kind,
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

        response = self.client.get(f"/api/environments/{self.team.id}/managed_viewsets/{self.endpoint}/")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()

        assert "views" in data
        assert "count" in data
        assert data["count"] == 2

        # Check that both views are returned with expected fields
        view_names = [view["name"] for view in data["views"]]
        assert "test_view_1" in view_names
        assert "test_view_2" in view_names

        # Check that each view has the expected fields
        for view in data["views"]:
            assert "id" in view
            assert "name" in view
            assert "created_at" in view
            assert "created_by_id" in view

    def test_retrieve_managed_viewset_without_views(self):
        """Test retrieving a managed viewset that exists but has no views"""
        # Create a managed viewset but no associated views
        DataWarehouseManagedViewSet.objects.create(
            team=self.team,
            kind=self.kind,
        )

        response = self.client.get(f"/api/environments/{self.team.id}/managed_viewsets/{self.endpoint}/")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()

        assert "views" in data
        assert "count" in data
        assert data["count"] == 0
        assert data["views"] == []

    def test_retrieve_managed_viewset_does_not_exist(self):
        """Test retrieving a managed viewset that doesn't exist"""
        response = self.client.get(f"/api/environments/{self.team.id}/managed_viewsets/{self.endpoint}/")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()

        assert "views" in data
        assert "count" in data
        assert data["count"] == 0
        assert data["views"] == []

    def test_retrieve_managed_viewset_excludes_deleted_views(self):
        """Test that deleted views are excluded from the response"""
        # Create a managed viewset
        managed_viewset = DataWarehouseManagedViewSet.objects.create(
            team=self.team,
            kind=self.kind,
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

        response = self.client.get(f"/api/environments/{self.team.id}/managed_viewsets/{self.endpoint}/")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()

        assert data["count"] == 1
        assert len(data["views"]) == 1
        assert data["views"][0]["name"] == "active_view"
        assert str(data["views"][0]["id"]) == str(active_view.id)


class TestDataWarehouseManagedViewSetAPIBaseRevenueAnalytics(TestDataWarehouseManagedViewSetAPIBase):
    __test__ = True

    kind = DataWarehouseManagedViewSetKind.REVENUE_ANALYTICS
    endpoint = "revenue_analytics"
    expected_count = 12

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


class TestDataWarehouseManagedViewSetAPIInvalid(APIBaseTest):
    def test_enable_invalid_kind(self):
        response = self.client.put(
            f"/api/environments/{self.team.id}/managed_viewsets/invalid_kind/",
            {"enabled": True},
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_retrieve_invalid_kind(self):
        """Test retrieving with an invalid kind returns 400"""
        response = self.client.get(f"/api/environments/{self.team.id}/managed_viewsets/invalid_kind/")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        data = response.json()
        assert "detail" in data
        assert "Invalid kind" in data["detail"]
