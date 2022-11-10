from rest_framework import status

from ee.api.test.base import APILicensedTest
from ee.models.role import Role, RoleMembership
from posthog.models.organization import OrganizationMembership
from posthog.models.user import User


class TestRoleMembershipAPI(APILicensedTest):
    def setUp(self):
        super().setUp()
        self.eng_role = Role.objects.create(name="Engineering", organization=self.organization)
        self.marketing_role = Role.objects.create(name="Marketing", organization=self.organization)

    def test_only_organization_admins_and_higher_can_add_users(self):
        user_a = User.objects.create_and_join(self.organization, "a@x.com", None)
        user_b = User.objects.create_and_join(self.organization, "b@x.com", None)
        self.assertEqual(self.organization_membership.level, OrganizationMembership.Level.MEMBER)

        add_user_b_res = self.client.post(
            f"/api/organizations/@current/roles/{self.eng_role.id}/role_memberships",
            {"user_uuids": [user_b.uuid]},
        )
        self.assertEqual(add_user_b_res.status_code, status.HTTP_403_FORBIDDEN)

        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        add_user_a_res = self.client.post(
            f"/api/organizations/@current/roles/{self.eng_role.id}/role_memberships",
            {"user_uuids": [user_a.uuid]},
        )
        self.assertEqual(add_user_a_res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(RoleMembership.objects.count(), 1)
        self.assertEqual(RoleMembership.objects.first().user, user_a)  # type: ignore

    def test_user_can_belong_to_multiple_roles(self):
        user_a = User.objects.create_and_join(self.organization, "a@potato.com", None)
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        self.assertEqual(RoleMembership.objects.count(), 0)

        self.client.post(
            f"/api/organizations/@current/roles/{self.eng_role.id}/role_memberships",
            {"user_uuids": [user_a.uuid]},
        )
        self.client.post(
            f"/api/organizations/@current/roles/{self.marketing_role.id}/role_memberships",
            {"user_uuids": [user_a.uuid]},
        )
        self.assertEqual(RoleMembership.objects.count(), 2)

    def test_bulk_add_multiple_memberships_to_role(self):
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        user_a = User.objects.create_and_join(self.organization, "a@potato.com", None)
        user_b = User.objects.create_and_join(self.organization, "b@potato.com", None)
        user_c = User.objects.create_and_join(self.organization, "c@potato.com", None)
        self.assertEqual(RoleMembership.objects.count(), 0)
        self.client.post(
            f"/api/organizations/@current/roles/{self.eng_role.id}/role_memberships",
            {"user_uuids": [user_a.uuid, user_b.uuid, user_c.uuid]},
        )
        self.assertEqual(RoleMembership.objects.count(), 3)
        # TODO: test for post response json
