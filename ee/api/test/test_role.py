from rest_framework import status

from ee.api.test.base import APILicensedTest
from ee.models.role import Role
from posthog.models.organization import Organization, OrganizationMembership


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
        self.assertEqual(Role.objects.all().count(), 1)
        self.assertEqual(Role.objects.first().name, "Product")  # type: ignore
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
        self.assertEqual(Role.objects.all().count(), 1)
        self.assertEqual(Role.objects.first().name, "on call support")  # type: ignore

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

    def test_updating_feature_flags_access_level(self):
        role = Role.objects.create(organization=self.organization, name="Engineering")
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        self.assertEqual(self.organization_membership.level, OrganizationMembership.Level.ADMIN)
        self.assertEqual(role.feature_flags_access_level, Organization.FeatureFlagsAccessLevel.CAN_ALWAYS_EDIT)
        self.client.patch(
            f"/api/organizations/@current/roles/{role.id}",
            {"feature_flags_access_level": Organization.FeatureFlagsAccessLevel.CAN_ONLY_VIEW},
        )
        self.assertEqual(
            Role.objects.first().feature_flags_access_level, Organization.FeatureFlagsAccessLevel.CAN_ONLY_VIEW  # type: ignore
        )
        self.client.patch(
            f"/api/organizations/@current/roles/{role.id}",
            {"feature_flags_access_level": Organization.FeatureFlagsAccessLevel.DEFAULT_VIEW_ALLOW_EDIT_BASED_ON_ROLE},
        )
        self.assertEqual(
            Role.objects.first().feature_flags_access_level,  # type: ignore
            Organization.FeatureFlagsAccessLevel.DEFAULT_VIEW_ALLOW_EDIT_BASED_ON_ROLE,
        )
