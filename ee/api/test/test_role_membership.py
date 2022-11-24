from rest_framework import status

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
        self.assertEqual(RoleMembership.objects.count(), 1)
        self.assertEqual(RoleMembership.objects.first().user, user_a)  # type: ignore

    def test_user_can_belong_to_multiple_roles(self):
        user_a = User.objects.create_and_join(self.organization, "a@potato.com", None)
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        self.assertEqual(RoleMembership.objects.count(), 0)

        self.client.post(
            f"/api/organizations/@current/roles/{self.eng_role.id}/role_memberships",
            {"user_uuid": user_a.uuid},
        )
        self.client.post(
            f"/api/organizations/@current/roles/{self.marketing_role.id}/role_memberships",
            {"user_uuid": user_a.uuid},
        )
        self.assertEqual(RoleMembership.objects.count(), 2)

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
        self.assertEqual(RoleMembership.objects.count(), 2)
        get_res = self.client.get(
            f"/api/organizations/@current/roles/{self.eng_role.id}/role_memberships",
        )
        self.assertEqual(get_res.json()["count"], 1)
        self.assertEqual(get_res.json()["results"][0]["user"]["distinct_id"], user_a.distinct_id)
        self.assertNotContains(get_res, str(user_b.email))
