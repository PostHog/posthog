import uuid

from parameterized import parameterized
from rest_framework import status

from posthog.constants import AvailableFeature
from posthog.models import Organization, OrganizationMembership, User
from posthog.models.organization_domain import OrganizationDomain

from ee.api.scim.auth import generate_scim_token
from ee.api.scim.group import PostHogSCIMGroup
from ee.api.scim.views import MAX_ITEMS_PER_PAGE
from ee.api.test.base import APILicensedTest
from ee.models.rbac.role import Role, RoleMembership


class TestSCIMGroupsAPI(APILicensedTest):
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
        self.client.credentials(**self.scim_headers)

    def test_groups_list(self):
        response = self.client.get(f"/scim/v2/{self.domain.id}/Groups")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "Resources" in data

    def test_groups_list_filter_exact_match(self):
        Role.objects.create(name="Engineering", organization=self.organization)
        Role.objects.create(name="engineering", organization=self.organization)
        Role.objects.create(name="Marketing", organization=self.organization)
        Role.objects.create(name="Sales", organization=self.organization)

        # Filter for exact match on displayName
        response = self.client.get(
            f"/scim/v2/{self.domain.id}/Groups",
            {"filter": 'displayName eq "Engineering"'},
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["totalResults"] == 1
        assert data["itemsPerPage"] == 1
        assert data["Resources"][0]["displayName"] == "Engineering"

    def test_groups_list_filter_excludes_groups_from_other_orgs(self):
        # Create role with same name in different organization
        other_org = Organization.objects.create(name="Other Org")
        Role.objects.create(name="Engineering", organization=other_org)

        # Filter for role from other org should return nothing
        response = self.client.get(
            f"/scim/v2/{self.domain.id}/Groups",
            {"filter": 'displayName eq "Engineering"'},
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["totalResults"] == 0
        assert data["Resources"] == []

    def test_groups_list_filter_no_match_returns_empty_list(self):
        Role.objects.create(name="Engineering", organization=self.organization)

        # Filter for non-existent group
        response = self.client.get(
            f"/scim/v2/{self.domain.id}/Groups",
            {"filter": 'displayName eq "NonExistent"'},
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["totalResults"] == 0
        assert data["itemsPerPage"] == 0
        assert data["Resources"] == []

    def test_create_group(self):
        group_data = {
            "schemas": ["urn:ietf:params:scim:schemas:core:2.0:Group"],
            "displayName": "Engineering",
            "members": [],
        }

        response = self.client.post(
            f"/scim/v2/{self.domain.id}/Groups", data=group_data, content_type="application/scim+json"
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
            f"/scim/v2/{self.domain.id}/Groups", data=group_data_first, content_type="application/scim+json"
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
            f"/scim/v2/{self.domain.id}/Groups", data=group_data_second, content_type="application/scim+json"
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
            f"/scim/v2/{self.domain.id}/Groups/{role.id}", data=put_data, content_type="application/scim+json"
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
            f"/scim/v2/{self.domain.id}/Groups/{fake_group_id}", data=put_data, content_type="application/scim+json"
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND, (
            f"Expected 404, got {response.status_code}: {response.content}"
        )
        assert not Role.objects.filter(name="ShouldFail", organization=self.organization).exists()

    def test_patch_group_not_found(self):
        patch_data = {
            "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
            "Operations": [{"op": "replace", "value": {"displayName": "ShouldFail"}}],
        }

        fake_group_id = str(uuid.uuid4())
        response = self.client.patch(
            f"/scim/v2/{self.domain.id}/Groups/{fake_group_id}", data=patch_data, content_type="application/scim+json"
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND, (
            f"Expected 404, got {response.status_code}: {response.content}"
        )

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
            f"/scim/v2/{self.domain.id}/Groups/{role.id}", data=patch_data, content_type="application/scim+json"
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
            f"/scim/v2/{self.domain.id}/Groups/{role.id}", data=patch_data, content_type="application/scim+json"
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
            f"/scim/v2/{self.domain.id}/Groups/{role.id}", data=patch_data, content_type="application/scim+json"
        )

        assert response.status_code == status.HTTP_200_OK
        assert RoleMembership.objects.filter(role=role, user=user).exists()

    def test_patch_replace_group_member_with_filtered_path_not_supported(self):
        # Swapping members within a group with a filtered path is not supported
        # Most IdPs send remove and add operations separately in this case
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
            f"/scim/v2/{self.domain.id}/Groups/{role.id}", data=patch_data, content_type="application/scim+json"
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert RoleMembership.objects.filter(role=role, user=user1).exists()
        assert not RoleMembership.objects.filter(role=role, user=user2).exists()

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
            f"/scim/v2/{self.domain.id}/Groups/{role.id}", data=patch_data, content_type="application/scim+json"
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
            f"/scim/v2/{self.domain.id}/Groups/{role.id}", data=patch_data, content_type="application/scim+json"
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
            f"/scim/v2/{self.domain.id}/Groups/{role.id}", data=patch_data, content_type="application/scim+json"
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
            "Operations": [{"op": "add", "path": f'members[value eq "{user1.id}"]'}],
        }

        response = self.client.patch(
            f"/scim/v2/{self.domain.id}/Groups/{role.id}", data=patch_data, content_type="application/scim+json"
        )

        assert response.status_code == status.HTTP_200_OK
        assert RoleMembership.objects.filter(role=role, user=user1).exists()

    def test_patch_add_does_not_create_membership_for_non_member(self):
        other_org = Organization.objects.create(name="Other Org")
        external_user = User.objects.create_user(
            email="external@other.com", password=None, first_name="External", is_email_verified=True
        )
        OrganizationMembership.objects.create(
            user=external_user, organization=other_org, level=OrganizationMembership.Level.MEMBER
        )

        role = Role.objects.create(name="TestRole", organization=self.organization)

        for op, description in [
            ({"op": "add", "value": {"members": [{"value": str(external_user.id)}]}}, "without path"),
            ({"op": "add", "path": "members", "value": [{"value": str(external_user.id)}]}, "simple path"),
            ({"op": "add", "path": f'members[value eq "{external_user.id}"]'}, "filtered path"),
        ]:
            with self.subTest(description):
                patch_data = {
                    "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
                    "Operations": [op],
                }
                response = self.client.patch(
                    f"/scim/v2/{self.domain.id}/Groups/{role.id}",
                    data=patch_data,
                    content_type="application/scim+json",
                )

                assert response.status_code == status.HTTP_200_OK
                assert not RoleMembership.objects.filter(role=role, user=external_user).exists()
                assert not OrganizationMembership.objects.filter(
                    user=external_user, organization=self.organization
                ).exists()

    def test_patch_remove_group_display_name_should_fail(self):
        role = Role.objects.create(name="RemoveName", organization=self.organization)

        patch_data = {
            "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
            "Operations": [{"op": "remove", "path": "displayName"}],
        }

        response = self.client.patch(
            f"/scim/v2/{self.domain.id}/Groups/{role.id}", data=patch_data, content_type="application/scim+json"
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
            f"/scim/v2/{self.domain.id}/Groups/{role.id}", data=patch_data, content_type="application/scim+json"
        )

        assert response.status_code == status.HTTP_200_OK
        assert not RoleMembership.objects.filter(role=role).exists()

    def test_patch_remove_group_member_with_simple_path_and_value_only_removes_specified_member(self):
        """Entra ID sends Remove with simple path "members" + value array instead of
        filtered path like members[value eq "id"]. This must only remove the specified
        member, not all members."""
        user1 = User.objects.create_user(
            email="removesimple1@example.com", password=None, first_name="Member1", is_email_verified=True
        )
        user2 = User.objects.create_user(
            email="removesimple2@example.com", password=None, first_name="Member2", is_email_verified=True
        )
        user3 = User.objects.create_user(
            email="removesimple3@example.com", password=None, first_name="Member3", is_email_verified=True
        )
        OrganizationMembership.objects.create(
            user=user1, organization=self.organization, level=OrganizationMembership.Level.MEMBER
        )
        OrganizationMembership.objects.create(
            user=user2, organization=self.organization, level=OrganizationMembership.Level.MEMBER
        )
        OrganizationMembership.objects.create(
            user=user3, organization=self.organization, level=OrganizationMembership.Level.MEMBER
        )

        role = Role.objects.create(name="TestRole", organization=self.organization)
        for user in [user1, user2, user3]:
            RoleMembership.objects.create(
                role=role,
                user=user,
                organization_member=OrganizationMembership.objects.get(user=user, organization=self.organization),
            )

        patch_data = {
            "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
            "Operations": [{"op": "remove", "path": "members", "value": [{"value": str(user1.id)}]}],
        }

        response = self.client.patch(
            f"/scim/v2/{self.domain.id}/Groups/{role.id}", data=patch_data, content_type="application/scim+json"
        )

        assert response.status_code == status.HTTP_200_OK
        assert not RoleMembership.objects.filter(role=role, user=user1).exists()
        assert RoleMembership.objects.filter(role=role, user=user2).exists()
        assert RoleMembership.objects.filter(role=role, user=user3).exists()

    def test_patch_remove_group_member_with_empty_value_list_does_not_remove_all(self):
        user = User.objects.create_user(
            email="removeemptylist@example.com", password=None, first_name="Member", is_email_verified=True
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
            "Operations": [{"op": "remove", "path": "members", "value": []}],
        }

        response = self.client.patch(
            f"/scim/v2/{self.domain.id}/Groups/{role.id}", data=patch_data, content_type="application/scim+json"
        )

        assert response.status_code == status.HTTP_200_OK
        assert RoleMembership.objects.filter(role=role, user=user).exists()

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
            f"/scim/v2/{self.domain.id}/Groups/{role.id}", data=patch_data, content_type="application/scim+json"
        )

        assert response.status_code == status.HTTP_200_OK
        assert not RoleMembership.objects.filter(role=role, user=user1).exists()
        assert RoleMembership.objects.filter(role=role, user=user2).exists()

    # ── Nested group (non-user member) tests ──

    def test_patch_add_silently_skips_non_user_member_ids(self):
        """Entra ID sends nested group UUIDs as member values — these should be silently skipped."""
        user = User.objects.create_user(
            email="realuser@example.com", password=None, first_name="Real", is_email_verified=True
        )
        OrganizationMembership.objects.create(
            user=user, organization=self.organization, level=OrganizationMembership.Level.MEMBER
        )
        role = Role.objects.create(name="TestRole", organization=self.organization)
        nested_group_id = str(uuid.uuid4())

        patch_data = {
            "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
            "Operations": [
                {"op": "add", "path": "members", "value": [{"value": nested_group_id}, {"value": str(user.id)}]}
            ],
        }

        response = self.client.patch(
            f"/scim/v2/{self.domain.id}/Groups/{role.id}", data=patch_data, content_type="application/scim+json"
        )

        assert response.status_code == status.HTTP_200_OK
        assert RoleMembership.objects.filter(role=role, user=user).exists()
        assert RoleMembership.objects.filter(role=role).count() == 1

    def test_put_silently_skips_non_user_member_ids(self):
        """PUT with a members list containing a nested group UUID should succeed and only add valid users."""
        user = User.objects.create_user(
            email="putuser@example.com", password=None, first_name="Put", is_email_verified=True
        )
        OrganizationMembership.objects.create(
            user=user, organization=self.organization, level=OrganizationMembership.Level.MEMBER
        )
        role = Role.objects.create(name="TestRole", organization=self.organization)
        nested_group_id = str(uuid.uuid4())

        put_data = {
            "schemas": ["urn:ietf:params:scim:api:messages:2.0:Group"],
            "displayName": "TestRole",
            "members": [{"value": nested_group_id}, {"value": str(user.id)}],
        }

        response = self.client.put(
            f"/scim/v2/{self.domain.id}/Groups/{role.id}", data=put_data, content_type="application/scim+json"
        )

        assert response.status_code == status.HTTP_200_OK
        assert RoleMembership.objects.filter(role=role, user=user).exists()
        assert RoleMembership.objects.filter(role=role).count() == 1

    def test_put_preserves_member_when_value_is_integer(self):
        # Some IdPs send `members[].value` as a JSON number rather than a string. The
        # set-diff in `_update_members` previously compared int IDs against the
        # always-string `current_user_ids`, so the membership the IdP asked to keep
        # ended up in `to_remove` and was silently deleted.
        user = User.objects.create_user(
            email="intvalue@example.com", password=None, first_name="Int", is_email_verified=True
        )
        OrganizationMembership.objects.create(
            user=user, organization=self.organization, level=OrganizationMembership.Level.MEMBER
        )
        role = Role.objects.create(name="IntValueRole", organization=self.organization)
        membership = RoleMembership.objects.create(role=role, user=user)

        put_data = {
            "schemas": ["urn:ietf:params:scim:schemas:core:2.0:Group"],
            "displayName": "IntValueRole",
            "members": [{"value": user.id}],  # int, not str
        }

        response = self.client.put(
            f"/scim/v2/{self.domain.id}/Groups/{role.id}", data=put_data, content_type="application/scim+json"
        )

        assert response.status_code == status.HTTP_200_OK
        assert RoleMembership.objects.filter(pk=membership.pk).exists(), (
            "RoleMembership for the user the IdP asked to keep was incorrectly deleted"
        )

    def test_put_with_mixed_int_and_string_member_values(self):
        # Mixed payload: keep one user (int value), keep another (str value), remove a third.
        # Verifies the int-value path doesn't bleed into a spurious removal of a string-value member.
        user_int = User.objects.create_user(
            email="mixedint@example.com", password=None, first_name="MixedInt", is_email_verified=True
        )
        user_str = User.objects.create_user(
            email="mixedstr@example.com", password=None, first_name="MixedStr", is_email_verified=True
        )
        user_removed = User.objects.create_user(
            email="mixedrm@example.com", password=None, first_name="MixedRm", is_email_verified=True
        )
        for u in (user_int, user_str, user_removed):
            OrganizationMembership.objects.create(
                user=u, organization=self.organization, level=OrganizationMembership.Level.MEMBER
            )
        role = Role.objects.create(name="MixedRole", organization=self.organization)
        for u in (user_int, user_str, user_removed):
            RoleMembership.objects.create(role=role, user=u)

        put_data = {
            "schemas": ["urn:ietf:params:scim:schemas:core:2.0:Group"],
            "displayName": "MixedRole",
            "members": [{"value": user_int.id}, {"value": str(user_str.id)}],
        }

        response = self.client.put(
            f"/scim/v2/{self.domain.id}/Groups/{role.id}", data=put_data, content_type="application/scim+json"
        )

        assert response.status_code == status.HTTP_200_OK
        assert RoleMembership.objects.filter(role=role, user=user_int).exists()
        assert RoleMembership.objects.filter(role=role, user=user_str).exists()
        assert not RoleMembership.objects.filter(role=role, user=user_removed).exists()
        assert RoleMembership.objects.filter(role=role).count() == 2

    # ── Helper contract tests ──

    @parameterized.expand(
        [
            ("none_returns_none", None, None),
            ("string_int_passes_through", "123", "123"),
            ("raw_int_normalized_to_str", 123, "123"),
            ("non_numeric_string_returns_none", "abc", None),
            ("uuid_string_returns_none", "550e8400-e29b-41d4-a716-446655440000", None),
        ]
    )
    def test_parse_member_id(self, _name: str, raw, expected: str | None):
        assert PostHogSCIMGroup._parse_member_id(raw) == expected

    def test_put_silently_skips_member_not_in_org(self):
        # User exists but belongs to a different org — _assign_role_member should
        # return early on the missing org_membership, leaving the role empty.
        other_org = Organization.objects.create(name="Other Org")
        external_user = User.objects.create_user(
            email="external_put@other.com", password=None, first_name="External", is_email_verified=True
        )
        OrganizationMembership.objects.create(
            user=external_user, organization=other_org, level=OrganizationMembership.Level.MEMBER
        )
        role = Role.objects.create(name="ExternalPutRole", organization=self.organization)

        put_data = {
            "schemas": ["urn:ietf:params:scim:schemas:core:2.0:Group"],
            "displayName": "ExternalPutRole",
            "members": [{"value": str(external_user.id)}],
        }

        response = self.client.put(
            f"/scim/v2/{self.domain.id}/Groups/{role.id}", data=put_data, content_type="application/scim+json"
        )

        assert response.status_code == status.HTTP_200_OK
        assert not RoleMembership.objects.filter(role=role, user=external_user).exists()
        assert RoleMembership.objects.filter(role=role).count() == 0

    def test_put_silently_skips_nonexistent_member(self):
        # Stale user id from the IdP — _assign_role_member should swallow
        # User.DoesNotExist and continue.
        role = Role.objects.create(name="GhostRole", organization=self.organization)

        put_data = {
            "schemas": ["urn:ietf:params:scim:schemas:core:2.0:Group"],
            "displayName": "GhostRole",
            "members": [{"value": "999999999"}],
        }

        response = self.client.put(
            f"/scim/v2/{self.domain.id}/Groups/{role.id}", data=put_data, content_type="application/scim+json"
        )

        assert response.status_code == status.HTTP_200_OK
        assert RoleMembership.objects.filter(role=role).count() == 0

    # ── Pagination tests ──

    def _create_groups(self, count: int) -> list[Role]:
        return [Role.objects.create(name=f"PagGroup{i}", organization=self.organization) for i in range(count)]

    def test_groups_list_pagination_with_count(self):
        self._create_groups(5)

        response = self.client.get(f"/scim/v2/{self.domain.id}/Groups", {"count": "2"})

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["totalResults"] == 5
        assert data["itemsPerPage"] == 2
        assert data["startIndex"] == 1
        assert len(data["Resources"]) == 2

    def test_groups_list_pagination_with_start_index(self):
        self._create_groups(5)

        response = self.client.get(f"/scim/v2/{self.domain.id}/Groups", {"startIndex": "3", "count": "2"})

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["totalResults"] == 5
        assert data["itemsPerPage"] == 2
        assert data["startIndex"] == 3
        assert len(data["Resources"]) == 2

    def test_groups_list_pagination_count_zero(self):
        self._create_groups(3)

        response = self.client.get(f"/scim/v2/{self.domain.id}/Groups", {"count": "0"})

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["totalResults"] == 3
        assert data["itemsPerPage"] == 0
        assert data["Resources"] == []

    def test_groups_list_pagination_start_index_beyond_total(self):
        self._create_groups(2)

        response = self.client.get(f"/scim/v2/{self.domain.id}/Groups", {"startIndex": "999"})

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["totalResults"] == 2
        assert data["itemsPerPage"] == 0
        assert data["Resources"] == []
        assert data["startIndex"] == 999

    def test_groups_list_pagination_count_capped_at_max(self):
        response = self.client.get(f"/scim/v2/{self.domain.id}/Groups", {"count": "500"})

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["itemsPerPage"] <= MAX_ITEMS_PER_PAGE

    @parameterized.expand(
        [
            ("start_index_zero", {"startIndex": "0"}, status.HTTP_400_BAD_REQUEST),
            ("start_index_negative", {"startIndex": "-1"}, status.HTTP_400_BAD_REQUEST),
            ("start_index_non_integer", {"startIndex": "abc"}, status.HTTP_400_BAD_REQUEST),
            ("count_negative", {"count": "-1"}, status.HTTP_400_BAD_REQUEST),
            ("count_non_integer", {"count": "abc"}, status.HTTP_400_BAD_REQUEST),
        ]
    )
    def test_groups_list_pagination_invalid_values(self, _name: str, params: dict, expected_status: int):
        response = self.client.get(f"/scim/v2/{self.domain.id}/Groups", params)
        assert response.status_code == expected_status

    def test_groups_list_pagination_with_filter(self):
        self._create_groups(3)

        response = self.client.get(
            f"/scim/v2/{self.domain.id}/Groups",
            {"filter": 'displayName eq "PagGroup0"', "count": "1"},
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["totalResults"] == 1
        assert data["itemsPerPage"] == 1
        assert data["Resources"][0]["displayName"] == "PagGroup0"

    def test_groups_list_pagination_page_through_all(self):
        self._create_groups(5)
        total = 5

        all_ids: list[str] = []
        start_index = 1
        page_size = 2
        while True:
            response = self.client.get(
                f"/scim/v2/{self.domain.id}/Groups",
                {"startIndex": str(start_index), "count": str(page_size)},
            )
            assert response.status_code == status.HTTP_200_OK
            data = response.json()
            assert data["totalResults"] == total
            if not data["Resources"]:
                break
            all_ids.extend(r["id"] for r in data["Resources"])
            start_index += len(data["Resources"])

        assert len(all_ids) == total
        assert len(set(all_ids)) == total
