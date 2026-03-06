from rest_framework import status

from posthog.constants import AvailableFeature
from posthog.models.organization_domain import OrganizationDomain

from ee.api.scim.auth import generate_scim_token
from ee.api.test.base import APILicensedTest
from ee.models.scim_request_log import SCIMRequestLog


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
            f"/scim/v2/{self.domain.id}/Users",
            HTTP_AUTHORIZATION=f"Bearer {self.plain_token}",
        )
        assert response.status_code == status.HTTP_200_OK

        logs = SCIMRequestLog.objects.filter(organization_domain=self.domain)
        assert logs.count() == 1

        log = logs.first()
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
            HTTP_AUTHORIZATION=f"Bearer {self.plain_token}",
        )

        log = SCIMRequestLog.objects.filter(organization_domain=self.domain).first()
        assert log is not None
        assert log.request_body is not None
        assert "test@example.com" not in str(log.request_body)

    def test_authorization_header_is_masked(self):
        self.client.get(
            f"/scim/v2/{self.domain.id}/Users",
            HTTP_AUTHORIZATION=f"Bearer {self.plain_token}",
        )
        log = SCIMRequestLog.objects.filter(organization_domain=self.domain).first()
        auth_header = log.request_headers.get("Authorization", "")
        assert self.plain_token not in auth_header
        assert auth_header.startswith("Bearer ...")

    def test_response_body_stored(self):
        self.client.get(
            f"/scim/v2/{self.domain.id}/ServiceProviderConfig",
            HTTP_AUTHORIZATION=f"Bearer {self.plain_token}",
        )
        log = SCIMRequestLog.objects.filter(organization_domain=self.domain).first()
        assert log.response_body is not None
        assert "schemas" in log.response_body

    def test_duration_is_tracked(self):
        self.client.get(
            f"/scim/v2/{self.domain.id}/Users",
            HTTP_AUTHORIZATION=f"Bearer {self.plain_token}",
        )
        log = SCIMRequestLog.objects.filter(organization_domain=self.domain).first()
        assert log.duration_ms is not None
        assert isinstance(log.duration_ms, int)
        assert log.duration_ms >= 0
