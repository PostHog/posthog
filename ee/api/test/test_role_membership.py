from rest_framework import status

from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.user import User

from ee.api.test.base import APILicensedTest
from ee.models.rbac.role import Role, RoleMembership


class TestRoleMembershipAPI(APILicensedTest):
    def setUp(self):
        super().setUp()
        self.eng_role = Role.objects.create(name="Engineering", organization=self.organization)
        self.marketing_role = Role.objects.create(name="Marketing", organization=self.organization)

    def test_adds_member_to_a_role(self):
        user = User.objects.create_and_join(self.organization, "a@x.com", None)

        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        assert RoleMembership.objects.count() == 0

        res = self.client.post(
            f"/api/organizations/@current/roles/{self.eng_role.id}/role_memberships",
            {"user_uuid": user.uuid},
        )

        assert res.status_code == status.HTTP_201_CREATED
        assert res.json()["id"] == str(RoleMembership.objects.first().id)
        assert res.json()["role_id"] == str(self.eng_role.id)
        assert res.json()["organization_member"]["user"]["id"] == user.id
        assert res.json()["user"]["id"] == user.id

    def test_only_organization_admins_and_higher_can_add_users(self):
        user_a = User.objects.create_and_join(self.organization, "a@x.com", None)
        user_b = User.objects.create_and_join(self.organization, "b@x.com", None)
        assert self.organization_membership.level == OrganizationMembership.Level.MEMBER

        add_user_b_res = self.client.post(
            f"/api/organizations/@current/roles/{self.eng_role.id}/role_memberships",
            {"user_uuid": user_b.uuid},
        )
        assert add_user_b_res.status_code == status.HTTP_403_FORBIDDEN

        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        add_user_a_res = self.client.post(
            f"/api/organizations/@current/roles/{self.eng_role.id}/role_memberships",
            {"user_uuid": user_a.uuid},
        )
        assert add_user_a_res.status_code == status.HTTP_201_CREATED
        assert RoleMembership.objects.count() == 1
        assert RoleMembership.objects.first().user == user_a

    def test_user_can_belong_to_multiple_roles(self):
        user_a = User.objects.create_and_join(self.organization, "a@potato.com", None)
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        assert RoleMembership.objects.count() == 0

        self.client.post(
            f"/api/organizations/@current/roles/{self.eng_role.id}/role_memberships",
            {"user_uuid": user_a.uuid},
        )
        self.client.post(
            f"/api/organizations/@current/roles/{self.marketing_role.id}/role_memberships",
            {"user_uuid": user_a.uuid},
        )
        assert RoleMembership.objects.count() == 2

    def test_user_can_be_removed_from_role(self):
        user_a = User.objects.create_and_join(self.organization, "a@potato.com", None)
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        assert RoleMembership.objects.count() == 0

        res = self.client.post(
            f"/api/organizations/@current/roles/{self.eng_role.id}/role_memberships",
            {"user_uuid": user_a.uuid},
        )
        assert RoleMembership.objects.count() == 1
        delete_response = self.client.delete(
            f"/api/organizations/@current/roles/{self.eng_role.id}/role_memberships/{res.json()['id']}",
        )
        assert delete_response.status_code == status.HTTP_204_NO_CONTENT
        assert RoleMembership.objects.count() == 0

    def test_returns_correct_results_by_organization(self):
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        other_org = Organization.objects.create(name="other org")
        user_a = User.objects.create_and_join(self.organization, "a@x.com", None)
        user_b = User.objects.create_and_join(other_org, "b@other_org.com", None)

        self.client.post(
            f"/api/organizations/@current/roles/{self.eng_role.id}/role_memberships",
            {"user_uuid": user_a.uuid},
        )
        other_org_same_name_role = Role.objects.create(organization=other_org, name="Engineering")
        RoleMembership.objects.create(role=other_org_same_name_role, user=user_b)
        assert RoleMembership.objects.count() == 2
        get_res = self.client.get(
            f"/api/organizations/@current/roles/{self.eng_role.id}/role_memberships",
        )
        assert get_res.json()["count"] == 1
        assert get_res.json()["results"][0]["user"]["distinct_id"] == user_a.distinct_id
        assert str(user_b.email) not in get_res.content.decode()

    def test_cannot_add_user_to_role_in_different_organization_vulnerability(self):
        """
        Test case to reproduce RBAC vulnerability:
        - user A is owner of org A and org B
        - user B is member of org A but NOT org B
        - user A should NOT be able to add user B to a role in org B
        """
        # Set up organizations
        org_a = self.organization  # This is the default org from the test base
        org_b = Organization.objects.create(name="Organization B")

        # Create users
        user_a = self.user  # This is the default user from the test base
        user_b = User.objects.create_and_join(org_a, "userb@example.com", None)

        # Make user A owner of both orgs
        self.organization_membership.level = OrganizationMembership.Level.OWNER
        self.organization_membership.save()
        OrganizationMembership.objects.create(user=user_a, organization=org_b, level=OrganizationMembership.Level.OWNER)

        # Create a role in org B
        role_in_org_b = Role.objects.create(name="Engineering", organization=org_b)

        # Verify user B is NOT a member of org B
        assert not OrganizationMembership.objects.filter(user=user_b, organization=org_b).exists()

        # Attempt to add user B to a role in org B by changing the org context
        # This should fail but currently succeeds due to the vulnerability
        self.client.force_login(user_a)

        # The vulnerability: by manipulating the URL to use org_a's ID but role from org_b,
        # the system checks user membership against org_a but assigns role from org_b
        res = self.client.post(
            f"/api/organizations/{org_a.id}/roles/{role_in_org_b.id}/role_memberships",
            {"user_uuid": user_b.uuid},
        )

        assert res.status_code in [status.HTTP_400_BAD_REQUEST, status.HTTP_403_FORBIDDEN]
        assert not RoleMembership.objects.filter(role=role_in_org_b, user=user_b).exists()

    def test_create_role_membership_with_explicit_org_uuid(self):
        """
        Creating role membership with explicit org UUID should work the same as @current.
        Regression test for: role_id not passed to serializer context when using explicit org UUID.
        """
        user_a = User.objects.create_and_join(self.organization, "a@example.com", None)
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        # First test with @current (should work)
        current_res = self.client.post(
            f"/api/organizations/@current/roles/{self.eng_role.id}/role_memberships",
            {"user_uuid": user_a.uuid},
        )
        assert current_res.status_code == status.HTTP_201_CREATED, f"@current failed: {current_res.json()}"

        # Clean up for next test
        RoleMembership.objects.all().delete()

        # Now test with explicit org UUID (this is the bug)
        res = self.client.post(
            f"/api/organizations/{self.organization.id}/roles/{self.eng_role.id}/role_memberships",
            {"user_uuid": user_a.uuid},
        )

        assert res.status_code == status.HTTP_201_CREATED, f"Expected 201, got {res.status_code}: {res.json()}"
        assert res.json()["role_id"] == str(self.eng_role.id)
        assert res.json()["user"]["id"] == user_a.id

    def test_list_role_memberships_with_explicit_org_uuid(self):
        """
        Listing role memberships with explicit org UUID should work the same as @current.
        """
        user_a = User.objects.create_and_join(self.organization, "a@example.com", None)
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        # Create a membership using @current (known to work)
        res = self.client.post(
            f"/api/organizations/@current/roles/{self.eng_role.id}/role_memberships",
            {"user_uuid": user_a.uuid},
        )
        assert res.status_code == status.HTTP_201_CREATED, f"creation failed: {res.json()}"

        # List using explicit org UUID
        res = self.client.get(
            f"/api/organizations/{self.organization.id}/roles/{self.eng_role.id}/role_memberships",
        )

        assert res.status_code == status.HTTP_200_OK
        assert res.json()["count"] == 1

    def test_delete_role_membership_with_explicit_org_uuid(self):
        """
        Deleting role membership with explicit org UUID should work the same as @current.
        """
        user_a = User.objects.create_and_join(self.organization, "a@example.com", None)
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        # Create a membership
        create_res = self.client.post(
            f"/api/organizations/@current/roles/{self.eng_role.id}/role_memberships",
            {"user_uuid": user_a.uuid},
        )
        membership_id = create_res.json()["id"]

        # Delete using explicit org UUID
        delete_res = self.client.delete(
            f"/api/organizations/{self.organization.id}/roles/{self.eng_role.id}/role_memberships/{membership_id}",
        )

        assert delete_res.status_code == status.HTTP_204_NO_CONTENT
        assert RoleMembership.objects.count() == 0

    def test_retrieve_role_membership_with_explicit_org_uuid(self):
        """Retrieving a single role membership by ID should work with explicit org UUID."""
        user_a = User.objects.create_and_join(self.organization, "a@example.com", None)
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        # Create a membership
        membership = RoleMembership.objects.create(
            role=self.eng_role,
            user=user_a,
            organization_member=OrganizationMembership.objects.get(user=user_a, organization=self.organization),
        )

        # Retrieve using explicit org UUID
        res = self.client.get(
            f"/api/organizations/{self.organization.id}/roles/{self.eng_role.id}/role_memberships/{membership.id}/",
        )

        assert res.status_code == status.HTTP_200_OK
        assert res.json()["id"] == str(membership.id)
        assert res.json()["role_id"] == str(self.eng_role.id)
        assert res.json()["user"]["id"] == user_a.id

    def test_invalid_organization_id_returns_not_found(self):
        """Using an invalid/nonsensical organization ID should return 404."""
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        # Test with completely invalid UUID format
        res = self.client.get(
            f"/api/organizations/not-a-valid-uuid/roles/{self.eng_role.id}/role_memberships",
        )
        assert res.status_code == status.HTTP_404_NOT_FOUND

    def test_nonexistent_organization_id_returns_not_found(self):
        """Using a valid UUID format but nonexistent organization should return 404."""
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        # Test with valid UUID format but nonexistent organization
        fake_org_id = "00000000-0000-0000-0000-000000000000"
        res = self.client.get(
            f"/api/organizations/{fake_org_id}/roles/{self.eng_role.id}/role_memberships",
        )
        assert res.status_code == status.HTTP_404_NOT_FOUND

    def test_cannot_retrieve_role_membership_from_different_organization(self):
        """
        IDOR test: User from org A should not be able to retrieve a role membership
        from org B, even if they know the membership ID and org B's ID.
        """
        # Set up two organizations
        org_a = self.organization
        org_b = Organization.objects.create(name="Organization B")

        # User A is admin of org A (but NOT a member of org B)
        user_a = self.user
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        # User B is member of org B
        user_b = User.objects.create_and_join(org_b, "userb@example.com", None)

        # Create a role and membership in org B
        role_in_org_b = Role.objects.create(name="Engineering", organization=org_b)
        membership_in_org_b = RoleMembership.objects.create(
            role=role_in_org_b,
            user=user_b,
            organization_member=OrganizationMembership.objects.get(user=user_b, organization=org_b),
        )

        # User A tries to retrieve membership from org B using org A's ID in URL
        self.client.force_login(user_a)
        res = self.client.get(
            f"/api/organizations/{org_a.id}/roles/{role_in_org_b.id}/role_memberships/{membership_in_org_b.id}/",
        )

        # Should return 404 because the membership is filtered by organization
        assert res.status_code == status.HTTP_404_NOT_FOUND

        # User A tries to list memberships from org B's role using org A's ID in URL
        list_res = self.client.get(
            f"/api/organizations/{org_a.id}/roles/{role_in_org_b.id}/role_memberships",
        )
        # The role doesn't belong to org A, so queryset returns empty (200 with count=0)
        assert list_res.status_code == status.HTTP_200_OK
        assert list_res.json()["count"] == 0

        # User A tries to retrieve membership using org B's ID in URL (different failure mode)
        res_with_org_b = self.client.get(
            f"/api/organizations/{org_b.id}/roles/{role_in_org_b.id}/role_memberships/{membership_in_org_b.id}/",
        )
        # Should return 403 because user A is not a member of org B (permission layer catches this first)
        assert res_with_org_b.status_code == status.HTTP_403_FORBIDDEN

        # User A tries to list memberships using org B's ID in URL
        list_res_with_org_b = self.client.get(
            f"/api/organizations/{org_b.id}/roles/{role_in_org_b.id}/role_memberships",
        )
        # Should return 403 because user A is not a member of org B (permission layer)
        assert list_res_with_org_b.status_code == status.HTTP_403_FORBIDDEN
