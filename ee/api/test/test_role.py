from rest_framework import status

from ee.api.test.base import APILicensedTest
from ee.models.role import Role
from posthog.models.organization import OrganizationMembership


class TestRoleAPI(APILicensedTest):
    def setUp(self):
        super().setUp()

    def test_only_organization_admins_and_higher_can_create(self):
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        admin_create_res = self.client.post(
            "/api/organizations/@current/roles",
            {
                "name": "Product",
            },
        )

        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        member_create_res = self.client.post(
            "/api/organizations/@current/roles",
            {
                "name": "Product 2",
            },
        )
        self.assertEqual(admin_create_res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(member_create_res.status_code, status.HTTP_403_FORBIDDEN)

    def test_only_organization_admins_and_higher_can_update(self):
        existing_eng_role = Role.objects.create(
            name="Engineering",
            organization=self.organization,
            created_by=self.user,
        )
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        admin_update_res = self.client.patch(
            f"/api/organizations/@current/roles/{existing_eng_role.id}",
            {"name": "on call support"},
        )

        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        member_update_res = self.client.patch(
            f"/api/organizations/@current/roles/{existing_eng_role.id}",
            {"name": "member eng"},
        )

        self.assertEqual(admin_update_res.status_code, status.HTTP_200_OK)
        self.assertEqual(member_update_res.status_code, status.HTTP_403_FORBIDDEN)

    def test_cannot_duplicate_role_name(self):
        Role.objects.create(name="Marketing", organization=self.organization)
        count = Role.objects.count()
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        res = self.client.post(
            "/api/organizations/@current/roles",
            {
                "name": "marketing",
            },
        )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            res.json(),
            {
                "type": "validation_error",
                "code": "unique",
                "detail": "There is already a role with this name.",
                "attr": "name",
            },
        )
        self.assertEqual(Role.objects.count(), count)

    # def test_default_feature_flag_access(self):
    #     Role.objects.create(organization=self.organization, name="Engineering")
    #     self.assert
    # def test_default_role_created_upon_new_organization(self):
    #     self.assertEqual(Role.objects.count(), 0)
    #     new_org = Organization.objects.bootstrap(self.user, name="PostHog A")
    #     self.assertEqual(Role.objects.count(), 1)
    #     self.assertEqual(Role.objects.first().name, DEFAULT_ROLE_NAME)  # type: ignore
    #     self.assertEqual(Role.objects.first().organization, new_org[0])  # type: ignore
