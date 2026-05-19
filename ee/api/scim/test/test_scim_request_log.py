from datetime import timedelta

from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from parameterized import parameterized
from rest_framework import status

from posthog.constants import AvailableFeature
from posthog.models import Organization
from posthog.models.organization import OrganizationMembership
from posthog.models.organization_domain import OrganizationDomain

from ee.api.scim.auth import generate_scim_token
from ee.api.test.base import APILicensedTest
from ee.models.scim_request_log import SCIMRequestLog
from ee.tasks.scim_request_log_cleanup import cleanup_old_scim_request_logs


class TestSCIMRequestLogCapture(APILicensedTest):
    def setUp(self):
        super().setUp()

        if not self.organization.is_feature_available(AvailableFeature.SCIM):
            features = self.organization.available_product_features or []
            if not any(f.get("key") == AvailableFeature.SCIM for f in features):
                features.append({"key": AvailableFeature.SCIM, "name": "SCIM"})
            self.organization.available_product_features = features
            self.organization.save()

        self.domain = OrganizationDomain.objects.create(
            organization=self.organization,
            domain="example.com",
            verified_at="2024-01-01T00:00:00Z",
        )
        self.plain_token, hashed_token = generate_scim_token()
        self.domain.scim_enabled = True
        self.domain.scim_bearer_token = hashed_token
        self.domain.save()

    def test_get_request_creates_log(self):
        response = self.client.get(
            f"/scim/v2/{self.domain.id}/Users", headers={"authorization": f"Bearer {self.plain_token}"}
        )
        assert response.status_code == status.HTTP_200_OK

        logs = SCIMRequestLog.objects.filter(organization_domain=self.domain)
        assert logs.count() == 1

        log = logs.first()
        assert log is not None
        assert log.request_method == "GET"
        assert f"/scim/v2/{self.domain.id}/Users" in log.request_path
        assert log.response_status == 200
        assert log.duration_ms is not None
        assert log.duration_ms >= 0

    def test_post_request_logs_masked_body(self):
        self.client.post(
            f"/scim/v2/{self.domain.id}/Users",
            data={
                "schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"],
                "userName": "testuser",
                "emails": [{"value": "test@example.com", "type": "work", "primary": True}],
                "name": {"givenName": "Test", "familyName": "User"},
                "active": True,
            },
            content_type="application/scim+json",
            headers={"authorization": f"Bearer {self.plain_token}"},
        )

        log = SCIMRequestLog.objects.filter(organization_domain=self.domain).first()
        assert log is not None
        assert log.request_body is not None
        assert "test@example.com" not in str(log.request_body)

    def test_authorization_header_is_fully_masked(self):
        self.client.get(f"/scim/v2/{self.domain.id}/Users", headers={"authorization": f"Bearer {self.plain_token}"})
        log = SCIMRequestLog.objects.filter(organization_domain=self.domain).first()
        assert log is not None
        auth_header = log.request_headers.get("Authorization", "")
        assert self.plain_token not in auth_header
        assert auth_header == "***"

    def test_response_body_stored(self):
        self.client.get(
            f"/scim/v2/{self.domain.id}/ServiceProviderConfig", headers={"authorization": f"Bearer {self.plain_token}"}
        )
        log = SCIMRequestLog.objects.filter(organization_domain=self.domain).first()
        assert log is not None
        assert log.response_body is not None
        assert "schemas" in log.response_body

    def test_duration_is_tracked(self):
        self.client.get(f"/scim/v2/{self.domain.id}/Users", headers={"authorization": f"Bearer {self.plain_token}"})
        log = SCIMRequestLog.objects.filter(organization_domain=self.domain).first()
        assert log is not None
        assert log.duration_ms is not None
        assert isinstance(log.duration_ms, int)
        assert log.duration_ms >= 0


class TestSCIMRequestLogCleanup(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(name="Test Org")
        self.domain = OrganizationDomain.objects.create(
            organization=self.organization,
            domain="cleanup-test.com",
            verified_at=timezone.now(),
        )

    def _create_log(self, age_days: int) -> SCIMRequestLog:
        log = SCIMRequestLog.objects.create(
            organization_domain=self.domain,
            request_method="GET",
            request_path="/scim/v2/test/Users",
            request_headers={},
            response_status=200,
            identity_provider="other",
        )
        SCIMRequestLog.objects.filter(id=log.id).update(created_at=timezone.now() - timedelta(days=age_days))
        return log

    @parameterized.expand(
        [
            ("old_deleted", 200, True),
            ("recent_kept", 10, False),
            ("boundary_kept", 179, False),
            ("boundary_deleted", 181, True),
        ]
    )
    def test_cleanup_respects_retention(self, _name: str, age_days: int, should_be_deleted: bool):
        log = self._create_log(age_days)
        cleanup_old_scim_request_logs()
        exists = SCIMRequestLog.objects.filter(id=log.id).exists()
        assert exists != should_be_deleted

    def test_cleanup_batches_deletes(self):
        for _ in range(5):
            self._create_log(200)
        with patch("ee.tasks.scim_request_log_cleanup.CLEANUP_BATCH_SIZE", 2):
            cleanup_old_scim_request_logs()
        assert SCIMRequestLog.objects.filter(organization_domain=self.domain).count() == 0


class TestSCIMLogsEndpoint(APILicensedTest):
    def setUp(self):
        super().setUp()

        if not self.organization.is_feature_available(AvailableFeature.SCIM):
            features = self.organization.available_product_features or []
            if not any(f.get("key") == AvailableFeature.SCIM for f in features):
                features.append({"key": AvailableFeature.SCIM, "name": "SCIM"})
            self.organization.available_product_features = features
            self.organization.save()

        self.domain = OrganizationDomain.objects.create(
            organization=self.organization,
            domain="example.com",
            verified_at="2024-01-01T00:00:00Z",
        )

    def _create_log(self, **kwargs) -> SCIMRequestLog:
        defaults = {
            "organization_domain": self.domain,
            "request_method": "GET",
            "request_path": "/scim/v2/test/Users",
            "request_headers": {},
            "response_status": 200,
            "identity_provider": "other",
        }
        defaults.update(kwargs)
        return SCIMRequestLog.objects.create(**defaults)

    def test_admin_can_access_scim_logs(self):
        OrganizationMembership.objects.filter(user=self.user, organization=self.organization).update(
            level=OrganizationMembership.Level.ADMIN
        )
        self._create_log()
        response = self.client.get(f"/api/organizations/{self.organization.id}/domains/{self.domain.id}/scim/logs")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["count"] == 1

    def test_member_cannot_access_scim_logs(self):
        OrganizationMembership.objects.filter(user=self.user, organization=self.organization).update(
            level=OrganizationMembership.Level.MEMBER
        )
        response = self.client.get(f"/api/organizations/{self.organization.id}/domains/{self.domain.id}/scim/logs")
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_search_by_path(self):
        OrganizationMembership.objects.filter(user=self.user, organization=self.organization).update(
            level=OrganizationMembership.Level.ADMIN
        )
        self._create_log(request_path="/scim/v2/test/Users")
        self._create_log(request_path="/scim/v2/test/Groups")
        response = self.client.get(
            f"/api/organizations/{self.organization.id}/domains/{self.domain.id}/scim/logs?search=Users"
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["count"] == 1

    def test_search_by_email_in_request_body(self):
        OrganizationMembership.objects.filter(user=self.user, organization=self.organization).update(
            level=OrganizationMembership.Level.ADMIN
        )
        self._create_log(request_body={"userName": "john@example.com"})
        self._create_log(request_body={"userName": "jane@example.com"})
        response = self.client.get(
            f"/api/organizations/{self.organization.id}/domains/{self.domain.id}/scim/logs?search=john@example.com"
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["count"] == 1

    def test_search_finds_masked_email(self):
        OrganizationMembership.objects.filter(user=self.user, organization=self.organization).update(
            level=OrganizationMembership.Level.ADMIN
        )
        self._create_log(request_body={"userName": "j***n@example.com"})
        response = self.client.get(
            f"/api/organizations/{self.organization.id}/domains/{self.domain.id}/scim/logs?search=john@example.com"
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["count"] == 1

    def test_search_finds_masked_string(self):
        OrganizationMembership.objects.filter(user=self.user, organization=self.organization).update(
            level=OrganizationMembership.Level.ADMIN
        )
        self._create_log(request_body={"displayName": "J***n"})
        response = self.client.get(
            f"/api/organizations/{self.organization.id}/domains/{self.domain.id}/scim/logs?search=John"
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["count"] == 1
