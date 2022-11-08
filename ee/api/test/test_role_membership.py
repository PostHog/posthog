from rest_framework import status

from ee.api.role import DEFAULT_ROLE_NAME
from ee.api.test.base import APILicensedTest
from ee.models.role import Role, RoleMembership
from posthog.models.organization import Organization, OrganizationMembership
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
            {"user_uuid": user_b.uuid},
        )
        self.assertEqual(add_user_b_res.status_code, status.HTTP_403_FORBIDDEN)
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        add_user_a_res = self.client.post(
            f"/api/organizations/@current/roles/{self.eng_role.id}/role_memberships",
            {"user_uuid": user_a.uuid},
        )
        self.assertEqual(add_user_a_res.status_code, status.HTTP_201_CREATED)

    def test_users_joining_have_default_write_role(self):
        count = RoleMembership.objects.count()
        self.assertEqual(count, 0)
        new_org = Organization.objects.bootstrap(self.user, name="PostHog A")
        user_a = User.objects.create_and_join(new_org[0], "a@x.com", None)
        self.assertEqual(RoleMembership.objects.count(), 1)
        self.assertEqual(RoleMembership.objects.first().user, user_a)  # type: ignore
        self.assertEqual(RoleMembership.objects.first().role.name, DEFAULT_ROLE_NAME)  # type: ignore
