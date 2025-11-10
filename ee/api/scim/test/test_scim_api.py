from rest_framework import status

from posthog.constants import AvailableFeature
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
        self.client.credentials(HTTP_AUTHORIZATION="Bearer invalid_token")
        response = self.client.get(f"/scim/v2/{self.domain.id}/Users")
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_no_token(self):
        response = self.client.get(f"/scim/v2/{self.domain.id}/Users")
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_service_provider_config(self):
        self.client.credentials(**self.scim_headers)
        response = self.client.get(f"/scim/v2/{self.domain.id}/ServiceProviderConfig")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["patch"]["supported"] is True
        assert "authenticationSchemes" in data

    def test_scim_requires_license(self):
        """Test that SCIM endpoints check for the SCIM feature license"""
        # Remove SCIM from available features
        self.organization.available_product_features = [{"key": AvailableFeature.SAML, "name": AvailableFeature.SAML}]
        self.organization.save()

        self.client.credentials(**self.scim_headers)
        response = self.client.get(f"/scim/v2/{self.domain.id}/Users")
        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert "license" in response.json()["detail"].lower()

    def test_scim_users_endpoint(self):
        """Test that SCIM Users endpoint works with valid license"""
        self.client.credentials(**self.scim_headers)
        response = self.client.get(f"/scim/v2/{self.domain.id}/Users")
        assert response.status_code == status.HTTP_200_OK
        assert "Resources" in response.json()

    def test_scim_groups_endpoint(self):
        """Test that SCIM Groups endpoint works with valid license"""
        self.client.credentials(**self.scim_headers)
        response = self.client.get(f"/scim/v2/{self.domain.id}/Groups")
        assert response.status_code == status.HTTP_200_OK
        assert "Resources" in response.json()
