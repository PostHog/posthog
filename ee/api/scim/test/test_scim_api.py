from parameterized import parameterized
from rest_framework import status

from posthog.constants import AvailableFeature
from posthog.models import Organization, OrganizationMembership, User
from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.identity_provider_config import IdentityProviderConfig
from posthog.models.linked_identity_provider_config import LinkedIdentityProviderConfig
from posthog.models.organization_domain import OrganizationDomain

from ee.api.scim.auth import generate_scim_token
from ee.api.scim.user import PostHogSCIMUser
from ee.api.scim.utils import get_scim_base_url
from ee.api.test.base import APILicensedTest
from ee.models.rbac.role import Role


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

        # Create organization domain with a linked, SCIM-enabled IdP config (SCIM auth resolves
        # through the linked config, not the domain's own legacy columns).
        self.domain = OrganizationDomain.objects.create(
            organization=self.organization,
            domain="example.com",
            verified_at="2024-01-01T00:00:00Z",
        )

        # Generate SCIM token
        token = generate_scim_token()
        self.plain_token = token.plain
        self.config = IdentityProviderConfig.objects.create(
            organization=self.organization, scim_enabled=True, scim_bearer_token=token.hashed
        )
        LinkedIdentityProviderConfig.objects.create(
            organization_domain=self.domain, identity_provider_config=self.config
        )
        self.config.refresh_from_db()

        self.scim_headers = {"HTTP_AUTHORIZATION": f"Bearer {self.plain_token}"}

    def test_scim_base_url_uses_linked_config_slug(self):
        assert get_scim_base_url(self.config).endswith(f"/scim/v2/{self.config.scim_slug}")

    def test_scim_uses_config_slug(self):
        self.config.scim_slug = "custom-scim-slug"
        self.config.save(update_fields=["scim_slug"])
        second_domain = OrganizationDomain.objects.create(
            organization=self.organization,
            domain="example.co.uk",
            verified_at="2024-01-01T00:00:00Z",
        )
        LinkedIdentityProviderConfig.objects.create(
            organization_domain=second_domain, identity_provider_config=self.config
        )
        self.client.credentials(**self.scim_headers)

        response = self.client.get("/scim/v2/custom-scim-slug/Users")
        assert response.status_code == status.HTTP_200_OK

        response = self.client.get(f"/scim/v2/{self.domain.id}/Users")
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_discovery_and_resource_urls_use_the_same_config_slug(self):
        # The tenant an authenticated SCIM request resolves to is the config, so every URL a
        # response hands back has to carry its slug. An IdP that follows ResourceTypes discovery
        # gets a 403 the moment that endpoint advertises something else, such as a domain UUID.
        self.config.scim_slug = "custom-scim-slug"
        self.config.save(update_fields=["scim_slug"])
        self.client.credentials(**self.scim_headers)

        resource_types = self.client.get("/scim/v2/custom-scim-slug/ResourceTypes").json()
        users = self.client.get("/scim/v2/custom-scim-slug/Users").json()

        assert {resource["endpoint"] for resource in resource_types["Resources"]} == {
            "/scim/v2/custom-scim-slug/Users",
            "/scim/v2/custom-scim-slug/Groups",
        }
        assert users["Resources"][0]["meta"]["location"].startswith("/scim/v2/custom-scim-slug/Users/")

    def test_invalid_token(self):
        self.client.credentials(HTTP_AUTHORIZATION="Bearer invalid_token")
        response = self.client.get(f"/scim/v2/{self.config.scim_slug}/Users")
        assert response.status_code == status.HTTP_403_FORBIDDEN
        data = response.json()
        assert "schemas" in data
        assert "urn:ietf:params:scim:api:messages:2.0:Error" in data["schemas"]
        assert data["status"] == 403
        assert "detail" in data

    def test_domain_without_idp_config_is_rejected(self):
        # A domain with no linked IdP config has no SCIM endpoint of its own: its id is not a config
        # slug, so even a valid token from another config in the same organization is rejected.
        unconfigured = OrganizationDomain.objects.create(
            organization=self.organization,
            domain="no-config.example.com",
            verified_at="2024-01-01T00:00:00Z",
        )
        assert not unconfigured.identity_provider_configs.exists()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.plain_token}")
        response = self.client.get(f"/scim/v2/{unconfigured.id}/Users")
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_config_without_a_verified_domain_is_rejected(self):
        # SCIM can be enabled on a config independently of any domain, so a config whose only domain
        # is unverified must still be rejected — provisioning stays gated behind verification.
        token = generate_scim_token()
        plain_token = token.plain
        unverified = OrganizationDomain.objects.create(
            organization=self.organization,
            domain="unverified.example.com",
            verified_at=None,
        )
        config = IdentityProviderConfig.objects.create(
            organization=self.organization, scim_enabled=True, scim_bearer_token=token.hashed
        )
        LinkedIdentityProviderConfig.objects.create(organization_domain=unverified, identity_provider_config=config)
        assert config.has_scim

        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {plain_token}")
        response = self.client.get(f"/scim/v2/{unverified.id}/Users")
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_no_token(self):
        response = self.client.get(f"/scim/v2/{self.config.scim_slug}/Users")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        data = response.json()
        assert "schemas" in data
        assert "urn:ietf:params:scim:api:messages:2.0:Error" in data["schemas"]
        assert data["status"] == 401
        assert "detail" in data

    def test_malformed_auth_header(self):
        self.client.credentials(HTTP_AUTHORIZATION="Basic invalid_token")
        response = self.client.get(f"/scim/v2/{self.config.scim_slug}/Users")
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
        response = self.client.get(f"/scim/v2/{self.config.scim_slug}/ServiceProviderConfig")

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
        response = self.client.get(f"/scim/v2/{self.config.scim_slug}/Users")
        assert response.status_code == status.HTTP_403_FORBIDDEN
        data = response.json()
        assert "schemas" in data
        assert "urn:ietf:params:scim:api:messages:2.0:Error" in data["schemas"]
        assert data["status"] == 403
        assert "detail" in data

    def test_scim_users_endpoint(self):
        """Test that SCIM Users endpoint works with valid license"""
        self.client.credentials(**self.scim_headers)
        response = self.client.get(f"/scim/v2/{self.config.scim_slug}/Users")
        assert response.status_code == status.HTTP_200_OK
        assert "Resources" in response.json()

    def test_scim_groups_endpoint(self):
        """Test that SCIM Groups endpoint works with valid license"""
        self.client.credentials(**self.scim_headers)
        response = self.client.get(f"/scim/v2/{self.config.scim_slug}/Groups")
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

        url = f"/scim/v2/{self.config.scim_slug}/Users/{other_user.id}"

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

    def _create_group_in_other_org(self):
        other_org = Organization.objects.create(name="OtherCorp")
        other_role = Role.objects.create(
            name="OtherRole",
            organization=other_org,
        )
        return other_role

    @parameterized.expand(["get", "put", "patch", "delete"])
    def test_scim_group_detail_rejects_cross_tenant_access(self, method: str):
        other_role = self._create_group_in_other_org()
        self.client.credentials(**self.scim_headers)

        url = f"/scim/v2/{self.config.scim_slug}/Groups/{other_role.id}"

        if method == "get":
            response = self.client.get(url)
        elif method == "put":
            response = self.client.put(
                url,
                {
                    "schemas": ["urn:ietf:params:scim:schemas:core:2.0:Group"],
                    "displayName": "ChangedName",
                    "members": [],
                },
                format="json",
            )
        elif method == "patch":
            response = self.client.patch(
                url,
                {
                    "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
                    "Operations": [{"op": "replace", "path": "displayName", "value": "ChangedName"}],
                },
                format="json",
            )
        elif method == "delete":
            response = self.client.delete(url)

        assert response.status_code == status.HTTP_404_NOT_FOUND

        other_role.refresh_from_db()
        assert other_role.name == "OtherRole"
        assert Role.objects.filter(id=other_role.id).exists()


class TestSCIMEmailDomainValidation(APILicensedTest):
    """Security tests: SCIM must not adopt users from other orgs or bypass email domain verification."""

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

        token = generate_scim_token()
        self.plain_token = token.plain
        self.config = IdentityProviderConfig.objects.create(
            organization=self.organization, scim_enabled=True, scim_bearer_token=token.hashed
        )
        LinkedIdentityProviderConfig.objects.create(
            organization_domain=self.domain, identity_provider_config=self.config
        )
        self.config.refresh_from_db()

        self.scim_headers = {"HTTP_AUTHORIZATION": f"Bearer {self.plain_token}"}

    def _scim_user_data(self, email: str, first_name: str = "Test", last_name: str = "User") -> dict:
        return {
            "schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"],
            "userName": email,
            "name": {"givenName": first_name, "familyName": last_name},
            "emails": [{"value": email, "primary": True}],
            "active": True,
        }

    def test_from_dict_rejects_adopting_user_from_different_org(self):
        other_org = Organization.objects.create(name="OtherCorp")
        other_user = User.objects.create(email="alice@othercorp.com", first_name="Alice")
        OrganizationMembership.objects.create(user=other_user, organization=other_org)

        with self.assertRaises(ValueError, msg="does not match any verified domain"):
            PostHogSCIMUser.from_dict(
                self._scim_user_data("alice@othercorp.com"),
                self.config,
            )

        assert not OrganizationMembership.objects.filter(user=other_user, organization=self.organization).exists()

    def test_from_dict_allows_adopting_user_with_matching_domain(self):
        other_org = Organization.objects.create(name="OtherCorp")
        existing_user = User.objects.create(email="bob@example.com", first_name="Bob")
        OrganizationMembership.objects.create(user=existing_user, organization=other_org)

        scim_user = PostHogSCIMUser.from_dict(
            self._scim_user_data("bob@example.com"),
            self.config,
        )

        assert scim_user.obj.email == "bob@example.com"
        assert OrganizationMembership.objects.filter(user=existing_user, organization=self.organization).exists()

    def test_from_dict_allows_creating_new_user_with_matching_domain(self):
        scim_user = PostHogSCIMUser.from_dict(
            self._scim_user_data("newuser@example.com"),
            self.config,
        )
        assert scim_user.obj.email == "newuser@example.com"

    def test_from_dict_allows_user_with_different_verified_org_domain(self):
        OrganizationDomain.objects.create(
            organization=self.organization,
            domain="partner.com",
            verified_at="2024-01-01T00:00:00Z",
        )

        scim_user = PostHogSCIMUser.from_dict(
            self._scim_user_data("alice@partner.com"),
            self.config,
        )
        assert scim_user.obj.email == "alice@partner.com"

    def test_from_dict_rejects_user_with_unverified_org_domain(self):
        OrganizationDomain.objects.create(
            organization=self.organization,
            domain="unverified.com",
            verified_at=None,
        )

        with self.assertRaises(ValueError, msg="does not match any verified domain"):
            PostHogSCIMUser.from_dict(
                self._scim_user_data("alice@unverified.com"),
                self.config,
            )
        assert not User.objects.filter(email="alice@unverified.com").exists()

    def test_from_dict_rejects_creating_new_user_with_non_matching_domain(self):
        with self.assertRaises(ValueError, msg="does not match any verified domain"):
            PostHogSCIMUser.from_dict(
                self._scim_user_data("newuser@evil.com"),
                self.config,
            )
        assert not User.objects.filter(email="newuser@evil.com").exists()

    def test_put_allows_email_change_to_different_verified_org_domain(self):
        self.client.credentials(**self.scim_headers)
        OrganizationDomain.objects.create(
            organization=self.organization,
            domain="partner.com",
            verified_at="2024-01-01T00:00:00Z",
        )

        response = self.client.post(
            f"/scim/v2/{self.config.scim_slug}/Users",
            self._scim_user_data("valid@example.com"),
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED
        user_id = response.json()["id"]

        response = self.client.put(
            f"/scim/v2/{self.config.scim_slug}/Users/{user_id}",
            self._scim_user_data("valid@partner.com"),
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK

        user = User.objects.get(id=user_id)
        assert user.email == "valid@partner.com"

    @parameterized.expand(
        [
            ("put",),
            ("patch_replace",),
            ("patch_add",),
        ]
    )
    def test_rejects_email_change_to_non_matching_domain(self, method: str):
        self.client.credentials(**self.scim_headers)

        response = self.client.post(
            f"/scim/v2/{self.config.scim_slug}/Users",
            self._scim_user_data("valid@example.com"),
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED
        user_id = response.json()["id"]

        response = self._change_email(method, user_id, "hijacked@evil.com")
        assert response.status_code == status.HTTP_400_BAD_REQUEST

        user = User.objects.get(id=user_id)
        assert user.email == "valid@example.com"

    def _change_email(self, method: str, user_id: str, new_email: str):
        if method == "put":
            return self.client.put(
                f"/scim/v2/{self.config.scim_slug}/Users/{user_id}",
                self._scim_user_data(new_email),
                format="json",
            )
        elif method == "patch_replace":
            return self.client.patch(
                f"/scim/v2/{self.config.scim_slug}/Users/{user_id}",
                {
                    "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
                    "Operations": [{"op": "replace", "path": "emails", "value": [{"value": new_email}]}],
                },
                format="json",
            )
        elif method == "patch_add":
            return self.client.patch(
                f"/scim/v2/{self.config.scim_slug}/Users/{user_id}",
                {
                    "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
                    "Operations": [{"op": "add", "path": "emails", "value": [{"value": new_email}]}],
                },
                format="json",
            )

    def _create_user_with_unowned_email(self) -> str:
        """Create a user whose current email domain is not owned by the SCIM org."""
        user = User.objects.create(email="victim@external.com", first_name="Victim")
        OrganizationMembership.objects.create(user=user, organization=self.organization)
        from ee.models.scim_provisioned_user import SCIMProvisionedUser

        SCIMProvisionedUser.objects.create(
            user=user,
            identity_provider_config=self.config,
            username="victim@external.com",
            active=True,
        )
        return str(user.id)

    @parameterized.expand(
        [
            ("put",),
            ("patch_replace",),
            ("patch_add",),
        ]
    )
    def test_rejects_email_change_when_org_does_not_own_current_domain(self, method: str):
        self.client.credentials(**self.scim_headers)
        user_id = self._create_user_with_unowned_email()

        response = self._change_email(method, user_id, "attacker@example.com")
        assert response.status_code == status.HTTP_400_BAD_REQUEST

        user = User.objects.get(id=user_id)
        assert user.email == "victim@external.com"

    def test_put_allows_email_change_when_org_owns_both_domains(self):
        self.client.credentials(**self.scim_headers)
        OrganizationDomain.objects.create(
            organization=self.organization,
            domain="partner.com",
            verified_at="2024-01-01T00:00:00Z",
        )

        response = self.client.post(
            f"/scim/v2/{self.config.scim_slug}/Users",
            self._scim_user_data("user@example.com"),
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED
        user_id = response.json()["id"]

        response = self.client.put(
            f"/scim/v2/{self.config.scim_slug}/Users/{user_id}",
            self._scim_user_data("user@partner.com"),
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK

        user = User.objects.get(id=user_id)
        assert user.email == "user@partner.com"


class TestSCIMAuditLogging(APILicensedTest):
    """Verify that SCIM mutations create activity log entries."""

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

        token = generate_scim_token()
        self.plain_token = token.plain
        self.config = IdentityProviderConfig.objects.create(
            organization=self.organization, scim_enabled=True, scim_bearer_token=token.hashed
        )
        LinkedIdentityProviderConfig.objects.create(
            organization_domain=self.domain, identity_provider_config=self.config
        )
        self.config.refresh_from_db()

        self.scim_headers = {"HTTP_AUTHORIZATION": f"Bearer {self.plain_token}"}

    def _scim_user_data(self, email: str, first_name: str = "Test", last_name: str = "User") -> dict:
        return {
            "schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"],
            "userName": email,
            "name": {"givenName": first_name, "familyName": last_name},
            "emails": [{"value": email, "primary": True}],
            "active": True,
        }

    def _create_scim_user(self, email: str = "testuser@example.com") -> str:
        self.client.credentials(**self.scim_headers)
        response = self.client.post(
            f"/scim/v2/{self.config.scim_slug}/Users",
            self._scim_user_data(email),
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED
        return response.json()["id"]

    @parameterized.expand(
        [
            ("post", "scim_provisioned"),
            ("put", "scim_replaced"),
            ("patch", "scim_updated"),
            ("delete", "scim_deprovisioned"),
        ]
    )
    def test_scim_mutation_creates_activity_log(self, method: str, expected_activity: str):
        user_id = self._create_scim_user()
        # Clear logs from creation so we can isolate the mutation under test
        if method != "post":
            ActivityLog.objects.filter(scope="User", activity="scim_provisioned").delete()

        self.client.credentials(**self.scim_headers)

        if method == "post":
            # Already created above, just check the log
            pass
        elif method == "put":
            self.client.put(
                f"/scim/v2/{self.config.scim_slug}/Users/{user_id}",
                self._scim_user_data("testuser@example.com", "Updated", "Name"),
                format="json",
            )
        elif method == "patch":
            self.client.patch(
                f"/scim/v2/{self.config.scim_slug}/Users/{user_id}",
                {
                    "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
                    "Operations": [{"op": "replace", "path": "name", "value": {"givenName": "Patched"}}],
                },
                format="json",
            )
        elif method == "delete":
            self.client.delete(f"/scim/v2/{self.config.scim_slug}/Users/{user_id}")

        log = ActivityLog.objects.filter(
            scope="User",
            activity=expected_activity,
            item_id=str(user_id),
        ).first()

        assert log is not None, f"Expected activity log with activity='{expected_activity}'"
        assert log.is_system is True
        assert log.user is None
        assert log.organization_id == self.organization.id
        assert log.detail is not None
        assert log.detail.get("context", {}).get("identity_provider_config_id") == str(self.config.id)


class TestSCIMGroupAuditLogging(APILicensedTest):
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

        token = generate_scim_token()
        self.plain_token = token.plain
        self.config = IdentityProviderConfig.objects.create(
            organization=self.organization, scim_enabled=True, scim_bearer_token=token.hashed
        )
        LinkedIdentityProviderConfig.objects.create(
            organization_domain=self.domain, identity_provider_config=self.config
        )
        self.config.refresh_from_db()

        self.scim_headers = {"HTTP_AUTHORIZATION": f"Bearer {self.plain_token}"}

    def _scim_group_data(self, name: str = "Engineering") -> dict:
        return {
            "schemas": ["urn:ietf:params:scim:schemas:core:2.0:Group"],
            "displayName": name,
            "members": [],
        }

    def _create_scim_group(self, name: str = "Engineering") -> str:
        self.client.credentials(**self.scim_headers)
        response = self.client.post(
            f"/scim/v2/{self.config.scim_slug}/Groups",
            self._scim_group_data(name),
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED
        return response.json()["id"]

    @parameterized.expand(
        [
            ("post", "scim_provisioned"),
            ("put", "scim_replaced"),
            ("patch", "scim_updated"),
            ("delete", "scim_deprovisioned"),
        ]
    )
    def test_scim_group_mutation_creates_activity_log(self, method: str, expected_activity: str):
        group_id = self._create_scim_group()
        if method != "post":
            ActivityLog.objects.filter(scope="Role", activity="scim_provisioned").delete()

        self.client.credentials(**self.scim_headers)

        if method == "post":
            pass
        elif method == "put":
            self.client.put(
                f"/scim/v2/{self.config.scim_slug}/Groups/{group_id}",
                self._scim_group_data("Updated Engineering"),
                format="json",
            )
        elif method == "patch":
            self.client.patch(
                f"/scim/v2/{self.config.scim_slug}/Groups/{group_id}",
                {
                    "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
                    "Operations": [{"op": "replace", "path": "displayName", "value": "Patched Engineering"}],
                },
                format="json",
            )
        elif method == "delete":
            self.client.delete(f"/scim/v2/{self.config.scim_slug}/Groups/{group_id}")

        log = ActivityLog.objects.filter(
            scope="Role",
            activity=expected_activity,
            item_id=str(group_id),
        ).first()

        assert log is not None, f"Expected activity log with activity='{expected_activity}'"
        assert log.is_system is True
        assert log.user is None
        assert log.organization_id == self.organization.id
        assert log.detail is not None
        assert log.detail.get("context", {}).get("identity_provider_config_id") == str(self.config.id)
