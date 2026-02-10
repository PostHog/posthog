from posthog.test.base import APIBaseTest
from unittest.mock import AsyncMock, patch

from rest_framework import status

from posthog.models import ProxyRecord
from posthog.models.organization import OrganizationMembership


class TestProxyRecordAPI(APIBaseTest):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.organization_membership.level = OrganizationMembership.Level.ADMIN
        cls.organization_membership.save()
        # Set up managed_reverse_proxy feature with limit of 2
        cls.organization.available_product_features = [
            {"key": "managed_reverse_proxy", "name": "managed_reverse_proxy", "limit": 2}
        ]
        cls.organization.save()

    def test_list_returns_max_proxy_records_from_feature(self):
        """The list endpoint should return max_proxy_records from the org's available features."""
        response = self.client.get(f"/api/organizations/{self.organization.id}/proxy_records/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertIn("results", data)
        self.assertIn("max_proxy_records", data)
        self.assertEqual(data["max_proxy_records"], 2)
        self.assertEqual(data["results"], [])

    def test_list_returns_zero_without_feature(self):
        """Without the managed_reverse_proxy feature, max_proxy_records should be 0."""
        self.organization.available_product_features = []
        self.organization.save()

        response = self.client.get(f"/api/organizations/{self.organization.id}/proxy_records/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data["max_proxy_records"], 0)

        # Restore for other tests
        self.organization.available_product_features = [
            {"key": "managed_reverse_proxy", "name": "managed_reverse_proxy", "limit": 2}
        ]
        self.organization.save()

    @patch("posthog.api.proxy_record.sync_connect")
    @patch("posthoganalytics.capture")
    def test_create_proxy_record(self, mock_capture, mock_sync_connect):
        """Should allow creating a proxy record when feature is available."""
        mock_temporal = AsyncMock()
        mock_sync_connect.return_value = mock_temporal

        response = self.client.post(
            f"/api/organizations/{self.organization.id}/proxy_records/",
            {"domain": "test.example.com"},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data["domain"], "test.example.com")
        self.assertEqual(data["status"], "waiting")
        self.assertIn("target_cname", data)

    @patch("posthog.api.proxy_record.sync_connect")
    @patch("posthoganalytics.capture")
    def test_cannot_exceed_feature_limit(self, mock_capture, mock_sync_connect):
        """Should reject creation when the org has reached the feature limit (2)."""
        mock_temporal = AsyncMock()
        mock_sync_connect.return_value = mock_temporal

        # Create 2 records (the limit)
        for i in range(2):
            response = self.client.post(
                f"/api/organizations/{self.organization.id}/proxy_records/",
                {"domain": f"proxy{i}.example.com"},
            )
            self.assertEqual(response.status_code, status.HTTP_200_OK, f"Failed to create record {i}")

        # The 3rd should be rejected
        response = self.client.post(
            f"/api/organizations/{self.organization.id}/proxy_records/",
            {"domain": "proxy2.example.com"},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Maximum of 2 proxy records", response.json()["detail"])

        # Verify only 2 records exist
        self.assertEqual(ProxyRecord.objects.filter(organization=self.organization).count(), 2)

    def test_cannot_create_without_feature(self):
        """Without the feature, creation should be blocked (limit is 0)."""
        self.organization.available_product_features = []
        self.organization.save()

        response = self.client.post(
            f"/api/organizations/{self.organization.id}/proxy_records/",
            {"domain": "test.example.com"},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Maximum of 0 proxy records", response.json()["detail"])

        # Restore for other tests
        self.organization.available_product_features = [
            {"key": "managed_reverse_proxy", "name": "managed_reverse_proxy", "limit": 2}
        ]
        self.organization.save()

    def test_non_admin_cannot_create_proxy_record(self):
        """Members below admin should not be able to create proxy records."""
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()

        response = self.client.post(
            f"/api/organizations/{self.organization.id}/proxy_records/",
            {"domain": "test.example.com"},
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
