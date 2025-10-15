from rest_framework import status

from posthog.models import Organization, OrganizationMembership, User
from posthog.models.organization_domain import OrganizationDomain

from ee.api.scim.auth import generate_scim_token
from ee.api.test.base import APILicensedTest


class TestSCIMAPI(APILicensedTest):
    def setUp(self):
        super().setUp()

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

    def test_users_list(self):
        response = self.client.get(f"/scim/v2/{self.domain.id}/Users", **self.scim_headers)

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "Resources" in data
        assert data["totalResults"] >= 1  # At least the test user

    def test_create_user(self):
        user_data = {
            "schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"],
            "userName": "newuser@example.com",
            "name": {"givenName": "New", "familyName": "User"},
            "emails": [{"value": "newuser@example.com", "primary": True}],
            "active": True,
        }

        response = self.client.post(
            f"/scim/v2/{self.domain.id}/Users", data=user_data, format="json", **self.scim_headers
        )

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data["userName"] == "newuser@example.com"
        assert data["name"]["givenName"] == "New"
        assert data["name"]["familyName"] == "User"

        # Verify user was created
        user = User.objects.get(email="newuser@example.com")
        assert user.first_name == "New"
        assert user.last_name == "User"
        assert user.is_email_verified is True

        # Verify organization membership
        membership = OrganizationMembership.objects.get(user=user, organization=self.organization)
        assert membership.level == OrganizationMembership.Level.MEMBER

    def test_get_user(self):
        user = User.objects.create_user(
            email="test@example.com", password=None, first_name="Test", last_name="User", is_email_verified=True
        )
        OrganizationMembership.objects.create(
            user=user, organization=self.organization, level=OrganizationMembership.Level.MEMBER
        )

        response = self.client.get(f"/scim/v2/{self.domain.id}/Users/{user.id}", **self.scim_headers)

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["userName"] == "test@example.com"
        assert data["name"]["givenName"] == "Test"
        assert data["active"] is True

    def test_patch_user(self):
        user = User.objects.create_user(
            email="update@example.com", password=None, first_name="Old", last_name="Name", is_email_verified=True
        )
        OrganizationMembership.objects.create(
            user=user, organization=self.organization, level=OrganizationMembership.Level.MEMBER
        )

        patch_data = {
            "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
            "Operations": [{"op": "replace", "value": {"name": {"givenName": "Updated", "familyName": "User"}}}],
        }

        response = self.client.patch(
            f"/scim/v2/{self.domain.id}/Users/{user.id}", data=patch_data, format="json", **self.scim_headers
        )

        assert response.status_code == status.HTTP_200_OK
        user.refresh_from_db()
        assert user.first_name == "Updated"
        assert user.last_name == "User"

    def test_patch_user_not_found(self):
        patch_data = {
            "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
            "Operations": [{"op": "replace", "value": {"name": {"givenName": "Should", "familyName": "Fail"}}}],
        }

        fake_user_id = 999999999
        response = self.client.patch(
            f"/scim/v2/{self.domain.id}/Users/{fake_user_id}", data=patch_data, format="json", **self.scim_headers
        )

        assert (
            response.status_code == status.HTTP_404_NOT_FOUND
        ), f"Expected 404, got {response.status_code}: {response.content}"

    def test_put_user(self):
        user = User.objects.create_user(
            email="old@example.com", password=None, first_name="Old", last_name="Name", is_email_verified=True
        )
        OrganizationMembership.objects.create(
            user=user, organization=self.organization, level=OrganizationMembership.Level.MEMBER
        )

        put_data = {
            "schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"],
            "userName": "put@example.com",
            "name": {"givenName": "Replaced", "familyName": "User"},
            "emails": [{"value": "put@example.com", "primary": True}],
            "active": True,
        }

        response = self.client.put(
            f"/scim/v2/{self.domain.id}/Users/{user.id}", data=put_data, format="json", **self.scim_headers
        )

        assert response.status_code == status.HTTP_200_OK
        user.refresh_from_db()
        assert user.first_name == "Replaced"
        assert user.last_name == "User"
        assert user.email == "put@example.com"

    def test_put_user_not_found(self):
        put_data = {
            "schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"],
            "userName": "nonexistent@example.com",
            "name": {"givenName": "Should", "familyName": "Fail"},
            "emails": [{"value": "nonexistent@example.com", "primary": True}],
            "active": True,
        }

        fake_user_id = 999999999
        response = self.client.put(
            f"/scim/v2/{self.domain.id}/Users/{fake_user_id}", data=put_data, format="json", **self.scim_headers
        )

        assert (
            response.status_code == status.HTTP_404_NOT_FOUND
        ), f"Expected 404, got {response.status_code}: {response.content}"
        assert not User.objects.filter(email="nonexistent@example.com").exists()

    def test_deactivate_user(self):
        user = User.objects.create_user(
            email="deactivate@example.com", password=None, first_name="Test", is_email_verified=True
        )
        OrganizationMembership.objects.create(
            user=user, organization=self.organization, level=OrganizationMembership.Level.MEMBER
        )

        patch_data = {
            "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
            "Operations": [{"op": "replace", "value": {"active": False}}],
        }

        response = self.client.patch(
            f"/scim/v2/{self.domain.id}/Users/{user.id}", data=patch_data, format="json", **self.scim_headers
        )

        assert response.status_code == status.HTTP_200_OK

        # Verify membership was removed
        assert not OrganizationMembership.objects.filter(user=user, organization=self.organization).exists()

        # User still exists
        user.refresh_from_db()
        assert user.is_active is True  # User is still active globally

    def test_delete_user(self):
        user = User.objects.create_user(
            email="delete@example.com", password=None, first_name="Delete", is_email_verified=True
        )
        OrganizationMembership.objects.create(
            user=user, organization=self.organization, level=OrganizationMembership.Level.MEMBER
        )

        response = self.client.delete(f"/scim/v2/{self.domain.id}/Users/{user.id}", **self.scim_headers)

        assert response.status_code == status.HTTP_204_NO_CONTENT

        # Verify membership was removed
        assert not OrganizationMembership.objects.filter(user=user, organization=self.organization).exists()

    def test_groups_list(self):
        response = self.client.get(f"/scim/v2/{self.domain.id}/Groups", **self.scim_headers)

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "Resources" in data

    def test_create_group(self):
        group_data = {
            "schemas": ["urn:ietf:params:scim:schemas:core:2.0:Group"],
            "displayName": "Engineering",
            "members": [],
        }

        response = self.client.post(
            f"/scim/v2/{self.domain.id}/Groups", data=group_data, format="json", **self.scim_headers
        )

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data["displayName"] == "Engineering"

        # Verify role was created
        from ee.models.rbac.role import Role

        role = Role.objects.get(name="Engineering", organization=self.organization)
        assert role is not None

    def test_add_user_to_group(self):
        from ee.models.rbac.role import Role

        user = User.objects.create_user(
            email="member@example.com", password=None, first_name="Member", is_email_verified=True
        )
        OrganizationMembership.objects.create(
            user=user, organization=self.organization, level=OrganizationMembership.Level.MEMBER
        )

        role = Role.objects.create(name="Developers", organization=self.organization)

        patch_data = {
            "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
            "Operations": [{"op": "replace", "value": {"members": [{"value": str(user.id)}]}}],
        }

        response = self.client.patch(
            f"/scim/v2/{self.domain.id}/Groups/{role.id}", data=patch_data, format="json", **self.scim_headers
        )

        assert response.status_code == status.HTTP_200_OK

        # Verify role membership
        from ee.models.rbac.role import RoleMembership

        assert RoleMembership.objects.filter(role=role, user=user).exists()

    def test_put_group(self):
        from ee.models.rbac.role import Role, RoleMembership

        user = User.objects.create_user(
            email="groupmember@example.com", password=None, first_name="Member", is_email_verified=True
        )
        OrganizationMembership.objects.create(
            user=user, organization=self.organization, level=OrganizationMembership.Level.MEMBER
        )

        role = Role.objects.create(name="OldName", organization=self.organization)

        put_data = {
            "schemas": ["urn:ietf:params:scim:schemas:core:2.0:Group"],
            "displayName": "NewName",
            "members": [{"value": str(user.id)}],
        }

        response = self.client.put(
            f"/scim/v2/{self.domain.id}/Groups/{role.id}", data=put_data, format="json", **self.scim_headers
        )

        assert response.status_code == status.HTTP_200_OK
        role.refresh_from_db()
        assert role.name == "NewName"
        assert RoleMembership.objects.filter(role=role, user=user).exists()

    def test_put_group_not_found(self):
        import uuid

        from ee.models.rbac.role import Role

        put_data = {
            "schemas": ["urn:ietf:params:scim:schemas:core:2.0:Group"],
            "displayName": "ShouldFail",
            "members": [],
        }

        fake_group_id = str(uuid.uuid4())
        response = self.client.put(
            f"/scim/v2/{self.domain.id}/Groups/{fake_group_id}", data=put_data, format="json", **self.scim_headers
        )

        assert (
            response.status_code == status.HTTP_404_NOT_FOUND
        ), f"Expected 404, got {response.status_code}: {response.content}"
        assert not Role.objects.filter(name="ShouldFail", organization=self.organization).exists()

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

    def test_existing_user_added_to_org(self):
        # Create user in different org
        other_org = Organization.objects.create(name="Other Org")
        existing_user = User.objects.create_user(
            email="existing@example.com", password=None, first_name="Existing", is_email_verified=True
        )
        OrganizationMembership.objects.create(
            user=existing_user, organization=other_org, level=OrganizationMembership.Level.MEMBER
        )

        # Try to provision same user via SCIM
        user_data = {
            "schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"],
            "userName": "existing@example.com",
            "name": {"givenName": "Existing", "familyName": "User"},
            "emails": [{"value": "existing@example.com", "primary": True}],
            "active": True,
        }

        response = self.client.post(
            f"/scim/v2/{self.domain.id}/Users", data=user_data, format="json", **self.scim_headers
        )

        assert response.status_code == status.HTTP_201_CREATED

        # User should now be member of both orgs
        assert OrganizationMembership.objects.filter(user=existing_user, organization=self.organization).exists()
        assert OrganizationMembership.objects.filter(user=existing_user, organization=other_org).exists()
