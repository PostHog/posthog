from posthog.test.base import APIBaseTest
from unittest.mock import AsyncMock, patch

from parameterized import parameterized
from rest_framework import status

from posthog.models import ProxyRecord
from posthog.models.organization import Organization, OrganizationMembership


class TestProxyRecordAPI(APIBaseTest):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.organization_membership.level = OrganizationMembership.Level.ADMIN
        cls.organization_membership.save()
        cls.organization.available_product_features = [
            {"key": "managed_reverse_proxy", "name": "managed_reverse_proxy", "limit": 2}
        ]
        cls.organization.save()

    def setUp(self):
        super().setUp()
        self.organization_membership.refresh_from_db()
        self.organization.refresh_from_db()

    def test_list_returns_max_proxy_records_from_feature(self):
        response = self.client.get(f"/api/organizations/{self.organization.id}/proxy_records/")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "results" in data
        assert "max_proxy_records" in data
        assert data["max_proxy_records"] == 2
        assert data["results"] == []

    def test_list_returns_default_without_feature(self):
        self.organization.available_product_features = []
        self.organization.save()

        response = self.client.get(f"/api/organizations/{self.organization.id}/proxy_records/")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["max_proxy_records"] == 2

    @patch("posthog.api.proxy_record.sync_connect")
    @patch("posthoganalytics.capture")
    def test_create_proxy_record(self, mock_capture, mock_sync_connect):
        mock_temporal = AsyncMock()
        mock_sync_connect.return_value = mock_temporal

        response = self.client.post(
            f"/api/organizations/{self.organization.id}/proxy_records/",
            {"domain": "test.example.com"},
        )
        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data["domain"] == "test.example.com"
        assert data["status"] == "waiting"
        assert "target_cname" in data

    @patch("posthog.api.proxy_record.sync_connect")
    @patch("posthoganalytics.capture")
    def test_cannot_exceed_feature_limit(self, mock_capture, mock_sync_connect):
        mock_temporal = AsyncMock()
        mock_sync_connect.return_value = mock_temporal

        for i in range(2):
            ProxyRecord.objects.create(
                organization=self.organization,
                created_by=self.user,
                domain=f"proxy{i}.example.com",
                target_cname=f"hash{i}.proxy.posthog.com",
            )

        response = self.client.post(
            f"/api/organizations/{self.organization.id}/proxy_records/",
            {"domain": "proxy2.example.com"},
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "Maximum of 2 proxy records" in response.json()["detail"]

    @patch("posthog.api.proxy_record.sync_connect")
    @patch("posthoganalytics.capture")
    def test_can_create_without_feature_using_default(self, mock_capture, mock_sync_connect):
        mock_temporal = AsyncMock()
        mock_sync_connect.return_value = mock_temporal

        self.organization.available_product_features = []
        self.organization.save()

        response = self.client.post(
            f"/api/organizations/{self.organization.id}/proxy_records/",
            {"domain": "test.example.com"},
        )
        assert response.status_code == status.HTTP_201_CREATED

    def test_create_with_missing_domain_rejected(self):
        response = self.client.post(
            f"/api/organizations/{self.organization.id}/proxy_records/",
            {},
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_create_with_empty_domain_rejected(self):
        response = self.client.post(
            f"/api/organizations/{self.organization.id}/proxy_records/",
            {"domain": ""},
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @patch("posthog.api.proxy_record.sync_connect")
    def test_create_cleans_up_on_temporal_failure(self, mock_sync_connect):
        mock_sync_connect.side_effect = Exception("connection failed")

        response = self.client.post(
            f"/api/organizations/{self.organization.id}/proxy_records/",
            {"domain": "fail.example.com"},
        )
        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        assert not ProxyRecord.objects.filter(organization=self.organization, domain="fail.example.com").exists()

    def test_non_admin_cannot_create_proxy_record(self):
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()

        response = self.client.post(
            f"/api/organizations/{self.organization.id}/proxy_records/",
            {"domain": "test.example.com"},
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_retrieve_proxy_record(self):
        record = ProxyRecord.objects.create(
            organization=self.organization,
            created_by=self.user,
            domain="retrieve.example.com",
            target_cname="abc123.proxy.posthog.com",
            status=ProxyRecord.Status.VALID,
        )

        response = self.client.get(
            f"/api/organizations/{self.organization.id}/proxy_records/{record.id}/",
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["domain"] == "retrieve.example.com"
        assert data["target_cname"] == "abc123.proxy.posthog.com"
        assert data["status"] == "valid"
        assert str(data["id"]) == str(record.id)

    def test_retrieve_proxy_record_from_other_org_not_found(self):
        other_org = Organization.objects.create(name="Other Org")
        record = ProxyRecord.objects.create(
            organization=other_org,
            created_by=self.user,
            domain="other.example.com",
            target_cname="abc123.proxy.posthog.com",
            status=ProxyRecord.Status.VALID,
        )

        response = self.client.get(
            f"/api/organizations/{self.organization.id}/proxy_records/{record.id}/",
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND

    @parameterized.expand(
        [
            ("erroring", ProxyRecord.Status.ERRORING, "Cloudflare API error"),
            ("timed_out", ProxyRecord.Status.TIMED_OUT, None),
        ]
    )
    @patch("posthog.api.proxy_record.sync_connect")
    @patch("posthoganalytics.capture")
    def test_retry_proxy_record(self, _name, initial_status, initial_message, mock_capture, mock_sync_connect):
        mock_temporal = AsyncMock()
        mock_sync_connect.return_value = mock_temporal

        record = ProxyRecord.objects.create(
            organization=self.organization,
            created_by=self.user,
            domain="retry.example.com",
            target_cname="abc123.proxy.posthog.com",
            status=initial_status,
            message=initial_message,
        )

        response = self.client.post(
            f"/api/organizations/{self.organization.id}/proxy_records/{record.id}/retry/",
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["status"] == "waiting"
        assert data["message"] is None

        record.refresh_from_db()
        assert record.status == ProxyRecord.Status.WAITING
        assert record.message is None
        mock_temporal.start_workflow.assert_called_once()

    @parameterized.expand(
        [
            ("waiting", ProxyRecord.Status.WAITING),
            ("issuing", ProxyRecord.Status.ISSUING),
            ("valid", ProxyRecord.Status.VALID),
            ("warning", ProxyRecord.Status.WARNING),
            ("deleting", ProxyRecord.Status.DELETING),
        ]
    )
    def test_cannot_retry_proxy_in_non_error_state(self, _name, initial_status):
        record = ProxyRecord.objects.create(
            organization=self.organization,
            created_by=self.user,
            domain="noretrystatus.example.com",
            target_cname="abc123.proxy.posthog.com",
            status=initial_status,
        )

        response = self.client.post(
            f"/api/organizations/{self.organization.id}/proxy_records/{record.id}/retry/",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "Cannot retry" in response.json()["detail"]

    @patch("posthog.api.proxy_record.sync_connect")
    def test_retry_returns_500_and_reverts_status_on_temporal_failure(self, mock_sync_connect):
        mock_sync_connect.side_effect = Exception("connection failed")

        record = ProxyRecord.objects.create(
            organization=self.organization,
            created_by=self.user,
            domain="fail.example.com",
            target_cname="abc123.proxy.posthog.com",
            status=ProxyRecord.Status.ERRORING,
        )

        response = self.client.post(
            f"/api/organizations/{self.organization.id}/proxy_records/{record.id}/retry/",
        )
        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        record.refresh_from_db()
        assert record.status == ProxyRecord.Status.ERRORING

    def test_non_admin_cannot_retry_proxy_record(self):
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()

        record = ProxyRecord.objects.create(
            organization=self.organization,
            created_by=self.user,
            domain="noadmin.example.com",
            target_cname="abc123.proxy.posthog.com",
            status=ProxyRecord.Status.ERRORING,
        )

        response = self.client.post(
            f"/api/organizations/{self.organization.id}/proxy_records/{record.id}/retry/",
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_retry_proxy_record_from_other_org_not_found(self):
        other_org = Organization.objects.create(name="Other Org")
        record = ProxyRecord.objects.create(
            organization=other_org,
            created_by=self.user,
            domain="other.example.com",
            target_cname="abc123.proxy.posthog.com",
            status=ProxyRecord.Status.ERRORING,
        )

        response = self.client.post(
            f"/api/organizations/{self.organization.id}/proxy_records/{record.id}/retry/",
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND

    @parameterized.expand(
        [
            ("waiting", ProxyRecord.Status.WAITING),
            ("erroring", ProxyRecord.Status.ERRORING),
            ("timed_out", ProxyRecord.Status.TIMED_OUT),
        ]
    )
    def test_destroy_proxy_in_pre_active_state_deletes_immediately(self, _name, initial_status):
        record = ProxyRecord.objects.create(
            organization=self.organization,
            created_by=self.user,
            domain="destroyme.example.com",
            target_cname="abc123.proxy.posthog.com",
            status=initial_status,
        )

        response = self.client.delete(
            f"/api/organizations/{self.organization.id}/proxy_records/{record.id}/",
        )
        assert response.status_code == status.HTTP_200_OK
        assert not ProxyRecord.objects.filter(id=record.id).exists()

    @parameterized.expand(
        [
            ("valid", ProxyRecord.Status.VALID),
            ("issuing", ProxyRecord.Status.ISSUING),
            ("warning", ProxyRecord.Status.WARNING),
        ]
    )
    @patch("posthog.api.proxy_record.sync_connect")
    @patch("posthoganalytics.capture")
    def test_destroy_active_proxy_starts_deletion_workflow(
        self, _name, initial_status, mock_capture, mock_sync_connect
    ):
        mock_temporal = AsyncMock()
        mock_sync_connect.return_value = mock_temporal

        record = ProxyRecord.objects.create(
            organization=self.organization,
            created_by=self.user,
            domain="activedestroy.example.com",
            target_cname="abc123.proxy.posthog.com",
            status=initial_status,
        )

        response = self.client.delete(
            f"/api/organizations/{self.organization.id}/proxy_records/{record.id}/",
        )
        assert response.status_code == status.HTTP_200_OK

        record.refresh_from_db()
        assert record.status == ProxyRecord.Status.DELETING
        mock_temporal.start_workflow.assert_called_once()

    @patch("posthog.api.proxy_record.sync_connect")
    def test_destroy_returns_500_and_reverts_status_on_temporal_failure(self, mock_sync_connect):
        mock_sync_connect.side_effect = Exception("connection failed")

        record = ProxyRecord.objects.create(
            organization=self.organization,
            created_by=self.user,
            domain="faildelete.example.com",
            target_cname="abc123.proxy.posthog.com",
            status=ProxyRecord.Status.VALID,
        )

        response = self.client.delete(
            f"/api/organizations/{self.organization.id}/proxy_records/{record.id}/",
        )
        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        record.refresh_from_db()
        assert record.status == ProxyRecord.Status.VALID

    def test_destroy_proxy_record_from_other_org_not_found(self):
        other_org = Organization.objects.create(name="Other Org")
        record = ProxyRecord.objects.create(
            organization=other_org,
            created_by=self.user,
            domain="other.example.com",
            target_cname="abc123.proxy.posthog.com",
            status=ProxyRecord.Status.VALID,
        )

        response = self.client.delete(
            f"/api/organizations/{self.organization.id}/proxy_records/{record.id}/",
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_non_admin_cannot_destroy_proxy_record(self):
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()

        record = ProxyRecord.objects.create(
            organization=self.organization,
            created_by=self.user,
            domain="noadmindestroy.example.com",
            target_cname="abc123.proxy.posthog.com",
            status=ProxyRecord.Status.VALID,
        )

        response = self.client.delete(
            f"/api/organizations/{self.organization.id}/proxy_records/{record.id}/",
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN
