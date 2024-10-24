from rest_framework import status

from ee.api.test.base import APILicensedTest
from ee.models.rbac.role import Role, RoleMembership
from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.user import User


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
