from rest_framework import status

from posthog.constants import AvailableFeature
from posthog.models.organization import OrganizationMembership
from posthog.models.organization_domain import OrganizationDomain

from ee.api.scim.auth import generate_scim_token
from ee.api.test.base import APILicensedTest


class TestSCIMAPI(APILicensedTest):
    def setUp(self):
        super().setUp()

        # Ensure SCIM is in available features
        if not self.organization.is_feature_available(AvailableFeature.SCIM):
            features = self.organization.available_product_features or []
            if not any(f.get("key") == AvailableFeature.SCIM for f in features):
                features.append({"key": AvailableFeature.SCIM, "name": "SCIM"})
            self.organization.available_product_features = features
            self.organization.save()

        # Create organization domain with SCIM enabled
        self.domain = OrganizationDomain.objects.create(
            organization=self.organization,
            domain="example.com",
            verified_at="2024-01-01T00:00:00Z",
        )

        # Generate SCIM token
        self.plain_token, hashed_token = generate_scim_token()
        self.domain.scim_enabled = True
        self.domain.scim_bearer_token = hashed_token
        self.domain.save()

        self.scim_headers = {"HTTP_AUTHORIZATION": f"Bearer {self.plain_token}"}

    def test_invalid_token(self):
        invalid_headers = {"HTTP_AUTHORIZATION": "Bearer invalid_token"}
        response = self.client.get(f"/scim/v2/{self.domain.id}/Users", **invalid_headers)
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_no_token(self):
        response = self.client.get(f"/scim/v2/{self.domain.id}/Users")
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_service_provider_config(self):
        response = self.client.get(f"/scim/v2/{self.domain.id}/ServiceProviderConfig", **self.scim_headers)

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["patch"]["supported"] is True
        assert "authenticationSchemes" in data

    def test_scim_requires_license(self):
        """Test that SCIM endpoints check for the SCIM feature license"""
        # Remove SCIM from available features
        self.organization.available_product_features = [{"key": AvailableFeature.SAML, "name": AvailableFeature.SAML}]
        self.organization.save()

        response = self.client.get(f"/scim/v2/{self.domain.id}/Users", **self.scim_headers)
        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert "license" in response.json()["detail"].lower()

    def test_scim_users_endpoint_with_license(self):
        """Test that SCIM Users endpoint works with valid license"""
        response = self.client.get(f"/scim/v2/{self.domain.id}/Users", **self.scim_headers)
        assert response.status_code == status.HTTP_200_OK
        assert "Resources" in response.json()

    def test_scim_groups_endpoint_with_license(self):
        """Test that SCIM Groups endpoint works with valid license"""
        response = self.client.get(f"/scim/v2/{self.domain.id}/Groups", **self.scim_headers)
        assert response.status_code == status.HTTP_200_OK
        assert "Resources" in response.json()


class TestSCIMManagementAPI(APILicensedTest):
    """Test SCIM management endpoints (enabling/disabling SCIM)"""

    def setUp(self):
        super().setUp()

        # Ensure SCIM is in available features
        if not self.organization.is_feature_available(AvailableFeature.SCIM):
            features = self.organization.available_product_features or []
            if not any(f.get("key") == AvailableFeature.SCIM for f in features):
                features.append({"key": AvailableFeature.SCIM, "name": "SCIM"})
            self.organization.available_product_features = features
            self.organization.save()

        # Make user an admin (required to change domain settings)
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        self.domain = OrganizationDomain.objects.create(
            organization=self.organization,
            domain="example.com",
            verified_at="2024-01-01T00:00:00Z",
        )

    def test_enable_scim_requires_license(self):
        """Test that enabling SCIM requires the SCIM feature"""
        # Remove SCIM from available features
        self.organization.available_product_features = [{"key": AvailableFeature.SAML, "name": AvailableFeature.SAML}]
        self.organization.save()

        response = self.client.post(f"/api/organizations/{self.organization.id}/domains/{self.domain.id}/scim")
        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert "not available" in response.json()["detail"].lower()

    def test_enable_scim_with_license(self):
        """Test that enabling SCIM works with valid license"""
        response = self.client.post(f"/api/organizations/{self.organization.id}/domains/{self.domain.id}/scim")
        assert response.status_code == status.HTTP_201_CREATED
        assert response.json()["scim_enabled"] is True
        assert "scim_bearer_token" in response.json()
        assert "scim_base_url" in response.json()

    def test_regenerate_token_requires_license(self):
        """Test that regenerating SCIM token requires the SCIM feature"""
        # First enable SCIM
        plain_token, hashed_token = generate_scim_token()
        self.domain.scim_enabled = True
        self.domain.scim_bearer_token = hashed_token
        self.domain.save()

        # Remove license
        self.organization.available_product_features = []
        self.organization.save()

        response = self.client.post(
            f"/api/organizations/{self.organization.id}/domains/{self.domain.id}/scim/regenerate"
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN
