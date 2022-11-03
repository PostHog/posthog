from rest_framework import status

from ee.api.test.base import APILicensedTest
from ee.models.role import Role
from posthog.models.organization import OrganizationMembership


class TestRoleAPI(APILicensedTest):
    test_role: Role

    def setUp(self):
        super().setUp()
        self.test_role = Role.objects.create(name="Marketing", created_by=self.user)

    def test_only_org_admins_and_owner_can_create(self):
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        admin_create_res = self.client.post("/api/roles/", {"name": "Product"})

        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        member_create_res = self.client.post("/api/roles/", {"name": "Product"})
        self.organization_membership.save()

        self.assertEqual(admin_create_res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(member_create_res.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_only_org_admins_and_owner_can_update(self):
        existing_eng_role = Role.objects.create(name="Engineering", created_by=self.user)

        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        admin_update_res = self.client.patch(f"/api/roles/{existing_eng_role.id}", {"name": "on call support"})

        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        member_update_res = self.client.patch(f"/api/roles/{existing_eng_role.id}", {"name": "member eng"})

        self.assertEqual(admin_update_res.status_code, status.HTTP_200_OK)
        self.assertEqual(member_update_res.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_cannot_duplicate_role_name(self):
        count = Role.objects.count()
        res = self.client.post("/api/roles/", {"name": "marketing"})
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            res.json(),
            {
                "type": "validation_error",
                "code": "unique",
                "detail": "There is already a role with this name.",
                "attr": "key",
            },
        )
        self.assertEqual(Role.objects.count(), count)
