import uuid

from rest_framework import status

from posthog.models import Organization, OrganizationMembership, User
from posthog.models.organization_domain import OrganizationDomain

from ee.api.scim.auth import generate_scim_token
from ee.api.test.base import APILicensedTest
from ee.models.rbac.role import Role, RoleMembership


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

    def test_existing_user_is_added_to_org(self):
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

    def test_repeated_post_does_not_create_duplicate_user(self):
        # In case the IdP failed to match user by id, it can send POST request to create a new user.
        # The user should be merged with existing one by email, not create a duplicate.
        user_data_first = {
            "schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"],
            "userName": "repeat@example.com",
            "name": {"givenName": "First", "familyName": "Time"},
            "emails": [{"value": "repeat@example.com", "primary": True}],
            "active": True,
        }

        response = self.client.post(
            f"/scim/v2/{self.domain.id}/Users", data=user_data_first, format="json", **self.scim_headers
        )

        assert response.status_code == status.HTTP_201_CREATED
        first_user = User.objects.get(email="repeat@example.com")

        # IdP sends POST request again with same email
        user_data_second = {
            "schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"],
            "userName": "repeat@example.com",
            "name": {"givenName": "Second", "familyName": "Time"},
            "emails": [{"value": "repeat@example.com", "primary": True}],
            "active": True,
        }

        response = self.client.post(
            f"/scim/v2/{self.domain.id}/Users", data=user_data_second, format="json", **self.scim_headers
        )

        assert response.status_code == status.HTTP_201_CREATED

        # Should NOT create duplicate user
        assert User.objects.filter(email="repeat@example.com").count() == 1

        # User should be updated with new data from second POST
        first_user.refresh_from_db()
        assert first_user.first_name == "Second"
        assert first_user.last_name == "Time"

        # User should have only one membership
        assert OrganizationMembership.objects.filter(user=first_user, organization=self.organization).count() == 1

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

    def test_patch_replace_user_without_path(self):
        user = User.objects.create_user(
            email="old@example.com", password=None, first_name="Old", last_name="Name", is_email_verified=True
        )
        OrganizationMembership.objects.create(
            user=user, organization=self.organization, level=OrganizationMembership.Level.MEMBER
        )

        patch_data = {
            "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
            "Operations": [
                {
                    "op": "replace",
                    "value": {
                        "name": {"givenName": "New", "familyName": "Name"},
                        "emails": [{"value": "new@example.com", "primary": True}],
                    },
                }
            ],
        }

        response = self.client.patch(
            f"/scim/v2/{self.domain.id}/Users/{user.id}", data=patch_data, format="json", **self.scim_headers
        )

        assert response.status_code == status.HTTP_200_OK
        user.refresh_from_db()
        assert user.first_name == "New"
        assert user.last_name == "Name"
        assert user.email == "new@example.com"

    def test_patch_replace_user_name_with_simple_path(self):
        user = User.objects.create_user(
            email="pathtest@example.com", password=None, first_name="Path", last_name="Test", is_email_verified=True
        )
        OrganizationMembership.objects.create(
            user=user, organization=self.organization, level=OrganizationMembership.Level.MEMBER
        )

        patch_data = {
            "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
            "Operations": [
                {"op": "replace", "path": "name", "value": {"givenName": "NewFirst", "familyName": "NewLast"}}
            ],
        }

        response = self.client.patch(
            f"/scim/v2/{self.domain.id}/Users/{user.id}", data=patch_data, format="json", **self.scim_headers
        )

        assert response.status_code == status.HTTP_200_OK
        user.refresh_from_db()
        assert user.first_name == "NewFirst"
        assert user.last_name == "NewLast"

    def test_patch_replace_user_emails_with_simple_path(self):
        user = User.objects.create_user(
            email="array@example.com", password=None, first_name="Array", last_name="Test", is_email_verified=True
        )
        OrganizationMembership.objects.create(
            user=user, organization=self.organization, level=OrganizationMembership.Level.MEMBER
        )

        patch_data = {
            "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
            "Operations": [
                {
                    "op": "replace",
                    "path": "emails",
                    "value": [{"value": "newarray@example.com", "primary": True}],
                }
            ],
        }

        response = self.client.patch(
            f"/scim/v2/{self.domain.id}/Users/{user.id}", data=patch_data, format="json", **self.scim_headers
        )

        assert response.status_code == status.HTTP_200_OK
        user.refresh_from_db()
        assert user.email == "newarray@example.com"

    def test_patch_replace_user_given_name_with_dotted_path(self):
        user = User.objects.create_user(
            email="dotpath@example.com", password=None, first_name="Dot", last_name="Path", is_email_verified=True
        )
        OrganizationMembership.objects.create(
            user=user, organization=self.organization, level=OrganizationMembership.Level.MEMBER
        )

        patch_data = {
            "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
            "Operations": [{"op": "replace", "path": "name.givenName", "value": "UpdatedFirst"}],
        }

        response = self.client.patch(
            f"/scim/v2/{self.domain.id}/Users/{user.id}", data=patch_data, format="json", **self.scim_headers
        )

        assert response.status_code == status.HTTP_200_OK
        user.refresh_from_db()
        assert user.first_name == "UpdatedFirst"
        assert user.last_name == "Path"

    def test_patch_replace_user_email_with_filtered_path(self):
        user = User.objects.create_user(
            email="primary@example.com", password=None, first_name="Primary", last_name="Email", is_email_verified=True
        )
        OrganizationMembership.objects.create(
            user=user, organization=self.organization, level=OrganizationMembership.Level.MEMBER
        )

        patch_data = {
            "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
            "Operations": [
                {"op": "replace", "path": "emails[primary eq true].value", "value": "primaryemail@example.com"}
            ],
        }

        response = self.client.patch(
            f"/scim/v2/{self.domain.id}/Users/{user.id}", data=patch_data, format="json", **self.scim_headers
        )

        assert response.status_code == status.HTTP_200_OK
        user.refresh_from_db()
        assert user.email == "primaryemail@example.com"

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

    def test_patch_add_user_without_path(self):
        user = User.objects.create_user(
            email="testuser@example.com", password=None, first_name="", last_name="", is_email_verified=True
        )

        patch_data = {
            "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
            "Operations": [
                {
                    "op": "add",
                    "value": {
                        "name": {"givenName": "New", "familyName": "User"},
                        "emails": [{"value": "newuser@example.com", "primary": True}],
                        "active": True,
                    },
                }
            ],
        }

        response = self.client.patch(
            f"/scim/v2/{self.domain.id}/Users/{user.id}", data=patch_data, format="json", **self.scim_headers
        )

        assert response.status_code == status.HTTP_200_OK
        user.refresh_from_db()
        assert user.first_name == "New"
        assert user.last_name == "User"
        assert user.email == "newuser@example.com"
        assert OrganizationMembership.objects.filter(user=user, organization=self.organization).exists()

    def test_patch_add_user_name_with_simple_path(self):
        user = User.objects.create_user(
            email="old@example.com", password=None, first_name="Old", last_name="Name", is_email_verified=True
        )
        OrganizationMembership.objects.create(
            user=user, organization=self.organization, level=OrganizationMembership.Level.MEMBER
        )

        patch_data = {
            "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
            "Operations": [{"op": "add", "path": "name", "value": {"givenName": "New", "familyName": "Name"}}],
        }

        response = self.client.patch(
            f"/scim/v2/{self.domain.id}/Users/{user.id}", data=patch_data, format="json", **self.scim_headers
        )

        assert response.status_code == status.HTTP_200_OK
        user.refresh_from_db()
        assert user.first_name == "New"
        assert user.last_name == "Name"

    def test_patch_add_active_user_with_simple_path(self):
        user = User.objects.create_user(
            email="reactivate@example.com", password=None, first_name="Test", is_email_verified=True
        )
        assert not OrganizationMembership.objects.filter(user=user, organization=self.organization).exists()

        patch_data = {
            "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
            "Operations": [{"op": "add", "path": "active", "value": True}],
        }

        response = self.client.patch(
            f"/scim/v2/{self.domain.id}/Users/{user.id}", data=patch_data, format="json", **self.scim_headers
        )

        assert response.status_code == status.HTTP_200_OK
        assert OrganizationMembership.objects.filter(user=user, organization=self.organization).exists()

    def test_patch_add_user_given_name_with_dotted_path(self):
        user = User.objects.create_user(
            email="addsubattr@example.com", password=None, first_name="", last_name="Existing", is_email_verified=True
        )
        OrganizationMembership.objects.create(
            user=user, organization=self.organization, level=OrganizationMembership.Level.MEMBER
        )

        patch_data = {
            "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
            "Operations": [{"op": "add", "path": "name.givenName", "value": "Ada"}],
        }

        response = self.client.patch(
            f"/scim/v2/{self.domain.id}/Users/{user.id}", data=patch_data, format="json", **self.scim_headers
        )

        assert response.status_code == status.HTTP_200_OK
        user.refresh_from_db()
        assert user.first_name == "Ada"
        assert user.last_name == "Existing"

    def test_patch_add_user_email_with_filtered_path(self):
        user = User.objects.create_user(
            email="old@example.com", password=None, first_name="Test", is_email_verified=True
        )
        OrganizationMembership.objects.create(
            user=user, organization=self.organization, level=OrganizationMembership.Level.MEMBER
        )

        patch_data = {
            "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
            "Operations": [{"op": "add", "path": "emails[primary eq true].value", "value": "primary@example.com"}],
        }

        response = self.client.patch(
            f"/scim/v2/{self.domain.id}/Users/{user.id}", data=patch_data, format="json", **self.scim_headers
        )

        assert response.status_code == status.HTTP_200_OK
        user.refresh_from_db()
        assert user.email == "primary@example.com"

    def test_patch_remove_active_user_with_simple_path(self):
        user = User.objects.create_user(
            email="removeactive@example.com", password=None, first_name="Test", is_email_verified=True
        )
        OrganizationMembership.objects.create(
            user=user, organization=self.organization, level=OrganizationMembership.Level.MEMBER
        )

        patch_data = {
            "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
            "Operations": [{"op": "remove", "path": "active"}],
        }

        response = self.client.patch(
            f"/scim/v2/{self.domain.id}/Users/{user.id}", data=patch_data, format="json", **self.scim_headers
        )

        assert response.status_code == status.HTTP_200_OK
        assert not OrganizationMembership.objects.filter(user=user, organization=self.organization).exists()

    def test_patch_remove_user_family_name_with_dotted_path(self):
        user = User.objects.create_user(
            email="removename@example.com", password=None, first_name="Remove", last_name="Me", is_email_verified=True
        )
        OrganizationMembership.objects.create(
            user=user, organization=self.organization, level=OrganizationMembership.Level.MEMBER
        )

        patch_data = {
            "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
            "Operations": [{"op": "remove", "path": "name.familyName"}],
        }

        response = self.client.patch(
            f"/scim/v2/{self.domain.id}/Users/{user.id}", data=patch_data, format="json", **self.scim_headers
        )

        assert response.status_code == status.HTTP_200_OK
        user.refresh_from_db()
        assert user.first_name == "Remove"
        assert user.last_name == ""

    def test_patch_remove_user_emails_should_fail(self):
        user = User.objects.create_user(
            email="email@example.com", password=None, first_name="Test", is_email_verified=True
        )
        OrganizationMembership.objects.create(
            user=user, organization=self.organization, level=OrganizationMembership.Level.MEMBER
        )

        patch_data = {
            "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
            "Operations": [{"op": "remove", "path": "emails"}],
        }

        response = self.client.patch(
            f"/scim/v2/{self.domain.id}/Users/{user.id}", data=patch_data, format="json", **self.scim_headers
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        user.refresh_from_db()
        assert user.email == "email@example.com"

    def test_patch_remove_user_email_with_filtered_path_should_fail(self):
        user = User.objects.create_user(
            email="primary@example.com", password=None, first_name="Test", is_email_verified=True
        )
        OrganizationMembership.objects.create(
            user=user, organization=self.organization, level=OrganizationMembership.Level.MEMBER
        )

        patch_data = {
            "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
            "Operations": [{"op": "remove", "path": "emails[primary eq true].value"}],
        }

        response = self.client.patch(
            f"/scim/v2/{self.domain.id}/Users/{user.id}", data=patch_data, format="json", **self.scim_headers
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        user.refresh_from_db()
        assert user.email == "primary@example.com"

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
        role = Role.objects.get(name="Engineering", organization=self.organization)
        assert role is not None

    def test_repeated_post_does_not_create_duplicate_group(self):
        # In case the IdP failed to match group by id, it can send POST request to create a new group.
        # The group should be merged with existing one by name, not create a duplicate.

        user = User.objects.create_user(
            email="groupmember@example.com", password=None, first_name="Member", is_email_verified=True
        )
        OrganizationMembership.objects.create(
            user=user, organization=self.organization, level=OrganizationMembership.Level.MEMBER
        )

        # IdP sends POST request to create group (first time)
        group_data_first = {
            "schemas": ["urn:ietf:params:scim:schemas:core:2.0:Group"],
            "displayName": "Developers",
            "members": [{"value": str(user.id)}],
        }

        response = self.client.post(
            f"/scim/v2/{self.domain.id}/Groups", data=group_data_first, format="json", **self.scim_headers
        )

        assert response.status_code == status.HTTP_201_CREATED
        first_role = Role.objects.get(name="Developers", organization=self.organization)
        assert RoleMembership.objects.filter(role=first_role, user=user).exists()

        # IdP sends POST request again with same displayName (second time)
        group_data_second = {
            "schemas": ["urn:ietf:params:scim:schemas:core:2.0:Group"],
            "displayName": "Developers",
            "members": [],
        }

        response = self.client.post(
            f"/scim/v2/{self.domain.id}/Groups", data=group_data_second, format="json", **self.scim_headers
        )

        assert response.status_code == status.HTTP_201_CREATED

        # Should NOT create duplicate group
        assert Role.objects.filter(name="Developers", organization=self.organization).count() == 1

        # Members should be updated (removed in second POST)
        assert not RoleMembership.objects.filter(role=first_role, user=user).exists()

    def test_put_group(self):
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

    def test_patch_replace_group_without_path(self):
        user = User.objects.create_user(
            email="groupreplace@example.com", password=None, first_name="Test", is_email_verified=True
        )
        OrganizationMembership.objects.create(
            user=user, organization=self.organization, level=OrganizationMembership.Level.MEMBER
        )

        role = Role.objects.create(name="OldGroupName", organization=self.organization)

        patch_data = {
            "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
            "Operations": [
                {"op": "replace", "value": {"displayName": "NewGroupName", "members": [{"value": str(user.id)}]}}
            ],
        }

        response = self.client.patch(
            f"/scim/v2/{self.domain.id}/Groups/{role.id}", data=patch_data, format="json", **self.scim_headers
        )

        assert response.status_code == status.HTTP_200_OK
        role.refresh_from_db()
        assert role.name == "NewGroupName"
        assert RoleMembership.objects.filter(role=role, user=user).exists()

    def test_patch_replace_group_display_name_with_simple_path(self):
        role = Role.objects.create(name="OldName", organization=self.organization)

        patch_data = {
            "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
            "Operations": [{"op": "replace", "path": "displayName", "value": "UpdatedName"}],
        }

        response = self.client.patch(
            f"/scim/v2/{self.domain.id}/Groups/{role.id}", data=patch_data, format="json", **self.scim_headers
        )

        assert response.status_code == status.HTTP_200_OK
        role.refresh_from_db()
        assert role.name == "UpdatedName"

    def test_patch_replace_group_members_with_simple_path(self):
        user = User.objects.create_user(
            email="groupmembers@example.com", password=None, first_name="Member", is_email_verified=True
        )
        OrganizationMembership.objects.create(
            user=user, organization=self.organization, level=OrganizationMembership.Level.MEMBER
        )

        role = Role.objects.create(name="TestRole", organization=self.organization)

        patch_data = {
            "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
            "Operations": [{"op": "replace", "path": "members", "value": [{"value": str(user.id)}]}],
        }

        response = self.client.patch(
            f"/scim/v2/{self.domain.id}/Groups/{role.id}", data=patch_data, format="json", **self.scim_headers
        )

        assert response.status_code == status.HTTP_200_OK
        assert RoleMembership.objects.filter(role=role, user=user).exists()

    def test_patch_replace_group_member_with_filtered_path(self):
        user1 = User.objects.create_user(
            email="filteredmember1@example.com", password=None, first_name="Member1", is_email_verified=True
        )
        user2 = User.objects.create_user(
            email="filteredmember2@example.com", password=None, first_name="Member2", is_email_verified=True
        )
        OrganizationMembership.objects.create(
            user=user1, organization=self.organization, level=OrganizationMembership.Level.MEMBER
        )
        OrganizationMembership.objects.create(
            user=user2, organization=self.organization, level=OrganizationMembership.Level.MEMBER
        )

        role = Role.objects.create(name="TestRole", organization=self.organization)
        RoleMembership.objects.create(
            role=role,
            user=user1,
            organization_member=OrganizationMembership.objects.get(user=user1, organization=self.organization),
        )

        patch_data = {
            "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
            "Operations": [{"op": "replace", "path": f'members[value eq "{user1.id}"].value', "value": str(user2.id)}],
        }

        response = self.client.patch(
            f"/scim/v2/{self.domain.id}/Groups/{role.id}", data=patch_data, format="json", **self.scim_headers
        )

        assert response.status_code == status.HTTP_200_OK
        assert not RoleMembership.objects.filter(role=role, user=user1).exists()
        assert RoleMembership.objects.filter(role=role, user=user2).exists()

    def test_patch_add_group_members_without_path(self):
        user = User.objects.create_user(
            email="addgroup@example.com", password=None, first_name="Test", is_email_verified=True
        )
        OrganizationMembership.objects.create(
            user=user, organization=self.organization, level=OrganizationMembership.Level.MEMBER
        )

        role = Role.objects.create(name="InitialName", organization=self.organization)

        patch_data = {
            "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
            "Operations": [{"op": "add", "value": {"members": [{"value": str(user.id)}]}}],
        }

        response = self.client.patch(
            f"/scim/v2/{self.domain.id}/Groups/{role.id}", data=patch_data, format="json", **self.scim_headers
        )

        assert response.status_code == status.HTTP_200_OK
        role.refresh_from_db()
        assert role.name == "InitialName"
        assert RoleMembership.objects.filter(role=role, user=user).exists()

    def test_patch_add_group_display_name_with_simple_path(self):
        role = Role.objects.create(name="OldName", organization=self.organization)

        patch_data = {
            "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
            "Operations": [{"op": "add", "path": "displayName", "value": "AddedName"}],
        }

        response = self.client.patch(
            f"/scim/v2/{self.domain.id}/Groups/{role.id}", data=patch_data, format="json", **self.scim_headers
        )

        assert response.status_code == status.HTTP_200_OK
        role.refresh_from_db()
        assert role.name == "AddedName"

    def test_patch_add_group_members_with_simple_path(self):
        user1 = User.objects.create_user(
            email="addmember1@example.com", password=None, first_name="Member1", is_email_verified=True
        )
        user2 = User.objects.create_user(
            email="addmember2@example.com", password=None, first_name="Member2", is_email_verified=True
        )
        OrganizationMembership.objects.create(
            user=user1, organization=self.organization, level=OrganizationMembership.Level.MEMBER
        )
        OrganizationMembership.objects.create(
            user=user2, organization=self.organization, level=OrganizationMembership.Level.MEMBER
        )

        role = Role.objects.create(name="TestRole", organization=self.organization)

        RoleMembership.objects.create(
            role=role,
            user=user1,
            organization_member=OrganizationMembership.objects.get(user=user1, organization=self.organization),
        )

        patch_data = {
            "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
            "Operations": [{"op": "add", "path": "members", "value": [{"value": str(user2.id)}]}],
        }

        response = self.client.patch(
            f"/scim/v2/{self.domain.id}/Groups/{role.id}", data=patch_data, format="json", **self.scim_headers
        )

        assert response.status_code == status.HTTP_200_OK
        assert RoleMembership.objects.filter(role=role, user=user1).exists()
        assert RoleMembership.objects.filter(role=role, user=user2).exists()

    def test_patch_add_group_member_with_filtered_path(self):
        user1 = User.objects.create_user(
            email="addfiltered1@example.com", password=None, first_name="Member1", is_email_verified=True
        )
        user2 = User.objects.create_user(
            email="addfiltered2@example.com", password=None, first_name="Member2", is_email_verified=True
        )
        OrganizationMembership.objects.create(
            user=user1, organization=self.organization, level=OrganizationMembership.Level.MEMBER
        )
        OrganizationMembership.objects.create(
            user=user2, organization=self.organization, level=OrganizationMembership.Level.MEMBER
        )

        role = Role.objects.create(name="TestRole", organization=self.organization)

        patch_data = {
            "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
            "Operations": [{"op": "add", "path": f'members[value eq "{user1.id}"]', "value": {"value": str(user1.id)}}],
        }

        response = self.client.patch(
            f"/scim/v2/{self.domain.id}/Groups/{role.id}", data=patch_data, format="json", **self.scim_headers
        )

        assert response.status_code == status.HTTP_200_OK
        assert RoleMembership.objects.filter(role=role, user=user1).exists()

    def test_patch_remove_group_display_name_should_fail(self):
        role = Role.objects.create(name="RemoveName", organization=self.organization)

        patch_data = {
            "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
            "Operations": [{"op": "remove", "path": "displayName"}],
        }

        response = self.client.patch(
            f"/scim/v2/{self.domain.id}/Groups/{role.id}", data=patch_data, format="json", **self.scim_headers
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        role.refresh_from_db()
        assert role.name == "RemoveName"

    def test_patch_remove_group_members_with_simple_path(self):
        user = User.objects.create_user(
            email="removeallmembers@example.com", password=None, first_name="Member", is_email_verified=True
        )
        OrganizationMembership.objects.create(
            user=user, organization=self.organization, level=OrganizationMembership.Level.MEMBER
        )

        role = Role.objects.create(name="TestRole", organization=self.organization)
        RoleMembership.objects.create(
            role=role,
            user=user,
            organization_member=OrganizationMembership.objects.get(user=user, organization=self.organization),
        )

        patch_data = {
            "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
            "Operations": [{"op": "remove", "path": "members"}],
        }

        response = self.client.patch(
            f"/scim/v2/{self.domain.id}/Groups/{role.id}", data=patch_data, format="json", **self.scim_headers
        )

        assert response.status_code == status.HTTP_200_OK
        assert not RoleMembership.objects.filter(role=role).exists()

    def test_patch_remove_group_member_with_filtered_path(self):
        user1 = User.objects.create_user(
            email="removefiltered1@example.com", password=None, first_name="Member1", is_email_verified=True
        )
        user2 = User.objects.create_user(
            email="removefiltered2@example.com", password=None, first_name="Member2", is_email_verified=True
        )
        OrganizationMembership.objects.create(
            user=user1, organization=self.organization, level=OrganizationMembership.Level.MEMBER
        )
        OrganizationMembership.objects.create(
            user=user2, organization=self.organization, level=OrganizationMembership.Level.MEMBER
        )

        role = Role.objects.create(name="TestRole", organization=self.organization)
        RoleMembership.objects.create(
            role=role,
            user=user1,
            organization_member=OrganizationMembership.objects.get(user=user1, organization=self.organization),
        )
        RoleMembership.objects.create(
            role=role,
            user=user2,
            organization_member=OrganizationMembership.objects.get(user=user2, organization=self.organization),
        )

        patch_data = {
            "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
            "Operations": [{"op": "remove", "path": f'members[value eq "{user1.id}"]'}],
        }

        response = self.client.patch(
            f"/scim/v2/{self.domain.id}/Groups/{role.id}", data=patch_data, format="json", **self.scim_headers
        )

        assert response.status_code == status.HTTP_200_OK
        assert not RoleMembership.objects.filter(role=role, user=user1).exists()
        assert RoleMembership.objects.filter(role=role, user=user2).exists()

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
