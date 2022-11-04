from rest_framework import status
from ee.api.role import DEFAULT_ROLE_NAME

from ee.api.test.base import APILicensedTest
from ee.models.role import Role
from posthog.models import organization
from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.team import Team
import pdb


class TestRoleAPI(APILicensedTest):
    test_role: Role

    def setUp(self):
        super().setUp()
        # self.test_role = Role.objects.create(name="Marketing", organization=self.organization, created_by=self.user)

    # def test_only_org_admins_and_owner_can_create(self):
    #     self.organization_membership.level = OrganizationMembership.Level.ADMIN
    #     self.organization_membership.save()

    #     admin_create_res = self.client.post(
    #         "/api/roles",
    #         {
    #             "name": "Product",
    #             "organization": str(self.organization.id),
    #         },
    #     )
    #     pdb.set_trace()

    #     self.organization_membership.level = OrganizationMembership.Level.MEMBER
    #     self.organization_membership.save()
    #     member_create_res = self.client.post(
    #         "/api/roles/",
    #         {
    #             "name": "Product",
    #             "organization": str(self.organization.id),
    #         },
    #     )
    #     self.assertEqual(admin_create_res.status_code, status.HTTP_201_CREATED)
    #     self.assertEqual(member_create_res.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_only_org_admins_and_owner_can_update(self):
        pdb.set_trace()
        existing_eng_role = Role.objects.create(
            name="Engineering", organization=self.organization, created_by=self.user
        )
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        admin_update_res = self.client.patch(f"/api/roles/{existing_eng_role.id}", {"name": "on call support"})

        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        member_update_res = self.client.patch(f"/api/roles/{existing_eng_role.id}", {"name": "member eng"})

        self.assertEqual(admin_update_res.status_code, status.HTTP_200_OK)
        self.assertEqual(member_update_res.status_code, status.HTTP_401_UNAUTHORIZED)

    # def test_cannot_duplicate_role_name(self):
    #     count = Role.objects.count()
    #     Role.objects.create(name="Marketing", organization=self.organization)
    #     res = self.client.post(
    #         "/api/roles/",
    #         {
    #             "name": "marketing",
    #             "organization": str(self.organization.id),
    #         },
    #     )
    #     self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
    #     self.assertEqual(
    #         res.json(),
    #         {
    #             "type": "validation_error",
    #             "code": "unique",
    #             "detail": "There is already a role with this name.",
    #             "attr": "key",
    #         },
    #     )
    #     self.assertEqual(Role.objects.count(), count)

    def test_default_role_created_upon_new_organization(self):
        self.assertEqual(Role.objects.count(), 0)
        new_org = Organization.objects.bootstrap(self.user, name="PostHog A")
        self.assertEqual(Role.objects.count(), 1)
        self.assertEqual(Role.objects.first().name, DEFAULT_ROLE_NAME)
        self.assertEqual(Role.objects.first().organization, new_org[0])
