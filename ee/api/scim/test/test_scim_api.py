from parameterized import parameterized
from rest_framework import status

from posthog.constants import AvailableFeature
from posthog.models import Organization, OrganizationMembership, User
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
        data = response.json()
        assert "schemas" in data
        assert "urn:ietf:params:scim:api:messages:2.0:Error" in data["schemas"]
        assert data["status"] == 403
        assert "detail" in data

    def test_no_token(self):
        response = self.client.get(f"/scim/v2/{self.domain.id}/Users")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        data = response.json()
        assert "schemas" in data
        assert "urn:ietf:params:scim:api:messages:2.0:Error" in data["schemas"]
        assert data["status"] == 401
        assert "detail" in data

    def test_malformed_auth_header(self):
        self.client.credentials(HTTP_AUTHORIZATION="Basic invalid_token")
        response = self.client.get(f"/scim/v2/{self.domain.id}/Users")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        data = response.json()
        assert "schemas" in data
        assert "urn:ietf:params:scim:api:messages:2.0:Error" in data["schemas"]
        assert data["status"] == 401
        assert "detail" in data

    def test_invalid_domain(self):
        self.client.credentials(**self.scim_headers)
        response = self.client.get("/scim/v2/00000000-0000-0000-0000-000000000000/Users")
        assert response.status_code == status.HTTP_403_FORBIDDEN
        data = response.json()
        assert "schemas" in data
        assert "urn:ietf:params:scim:api:messages:2.0:Error" in data["schemas"]
        assert data["status"] == 403
        assert "detail" in data

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
        data = response.json()
        assert "schemas" in data
        assert "urn:ietf:params:scim:api:messages:2.0:Error" in data["schemas"]
        assert data["status"] == 403
        assert "detail" in data

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

    def _create_user_in_other_org(self):
        other_org = Organization.objects.create(name="OtherCorp")
        other_user = User.objects.create(
            email="alice@othercorp.com",
            first_name="Alice",
            last_name="Original",
        )
        OrganizationMembership.objects.create(
            user=other_user,
            organization=other_org,
            level=OrganizationMembership.Level.MEMBER,
        )
        return other_user

    @parameterized.expand(["get", "put", "patch", "delete"])
    def test_scim_user_detail_rejects_cross_tenant_access(self, method: str):
        other_user = self._create_user_in_other_org()
        self.client.credentials(**self.scim_headers)

        url = f"/scim/v2/{self.domain.id}/Users/{other_user.id}"

        if method == "get":
            response = self.client.get(url)
        elif method == "put":
            response = self.client.put(
                url,
                {
                    "schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"],
                    "userName": "changed@example.com",
                    "name": {"givenName": "Changed", "familyName": "User"},
                    "emails": [{"value": "changed@example.com", "primary": True}],
                    "active": True,
                },
                format="json",
            )
        elif method == "patch":
            response = self.client.patch(
                url,
                {
                    "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
                    "Operations": [{"op": "replace", "path": "emails", "value": [{"value": "changed@example.com"}]}],
                },
                format="json",
            )
        elif method == "delete":
            response = self.client.delete(url)

        assert response.status_code == status.HTTP_404_NOT_FOUND

        other_user.refresh_from_db()
        assert other_user.email == "alice@othercorp.com"
        assert other_user.first_name == "Alice"
        assert User.objects.filter(id=other_user.id).exists()
