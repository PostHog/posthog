from django.db import IntegrityError

from rest_framework import status

from posthog.models.organization import Organization, OrganizationMembership

from ee.api.test.base import APILicensedTest
from ee.models.rbac.role import Role


class TestRoleCrossOrgAuthorization(APILicensedTest):
    """Tests for cross-organization authorization bypass on role endpoints."""

    CLASS_DATA_LEVEL_SETUP = False

    def setUp(self):
        super().setUp()
        self.org_a = self.organization
        self.org_b = Organization.objects.create(name="Org B")
        self.org_b.update_available_product_features()
        self.org_b.save()

        # User is admin in org_a, member in org_b
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        self.org_b_membership = OrganizationMembership.objects.create(
            user=self.user, organization=self.org_b, level=OrganizationMembership.Level.MEMBER
        )

    def _switch_active_org(self, org):
        self.user.current_organization = org
        self.user.save()

    def test_cross_org_admin_cannot_create_roles_in_other_org(self):
        self._switch_active_org(self.org_a)
        res = self.client.post(f"/api/organizations/{self.org_b.id}/roles", {"name": "Hacked Role"})
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_cross_org_admin_cannot_update_roles_in_other_org(self):
        role = Role.objects.create(name="Engineering", organization=self.org_b)
        self._switch_active_org(self.org_a)
        res = self.client.patch(f"/api/organizations/{self.org_b.id}/roles/{role.id}", {"name": "Hacked"})
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_cross_org_admin_cannot_delete_roles_in_other_org(self):
        role = Role.objects.create(name="Engineering", organization=self.org_b)
        self._switch_active_org(self.org_a)
        res = self.client.delete(f"/api/organizations/{self.org_b.id}/roles/{role.id}")
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_cross_org_role_creation_uses_correct_org(self):
        """Admin in both orgs, active=A, POST to B URL → role.organization == B"""
        self.org_b_membership.level = OrganizationMembership.Level.ADMIN
        self.org_b_membership.save()
        self._switch_active_org(self.org_a)
        res = self.client.post(f"/api/organizations/{self.org_b.id}/roles", {"name": "New Role"})
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        role = Role.objects.get(id=res.json()["id"])
        self.assertEqual(role.organization_id, self.org_b.id)

    def test_cross_org_role_name_uniqueness_checks_correct_org(self):
        """'Engineering' exists in A. Admin in both, active=A, POST to B → 201"""
        Role.objects.create(name="Engineering", organization=self.org_a)
        self.org_b_membership.level = OrganizationMembership.Level.ADMIN
        self.org_b_membership.save()
        self._switch_active_org(self.org_a)
        res = self.client.post(f"/api/organizations/{self.org_b.id}/roles", {"name": "Engineering"})
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)

    def test_member_cannot_modify_roles_after_fix(self):
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        res = self.client.post(f"/api/organizations/{self.org_a.id}/roles", {"name": "Blocked"})
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_admin_can_modify_roles_with_explicit_org_id(self):
        res = self.client.post(f"/api/organizations/{self.org_a.id}/roles", {"name": "Allowed"})
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)


class TestRoleAPI(APILicensedTest):
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
        other_org = Organization.objects.create(name="other org")
        Role.objects.create(name="Marketing", organization=other_org)
        self.assertEqual(Role.objects.count(), 2)
        self.assertEqual(Role.objects.filter(organization=other_org).exists(), True)
        with self.assertRaises(IntegrityError):
            Role.objects.create(name="Marketing", organization=self.organization)

    def test_can_rename_role_with_case_change(self):
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        role = Role.objects.create(name="engineering", organization=self.organization, created_by=self.user)
        res = self.client.patch(
            f"/api/organizations/@current/roles/{role.id}",
            {"name": "Engineering"},
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        role.refresh_from_db()
        self.assertEqual(role.name, "Engineering")

    def test_cannot_rename_role_to_existing_name(self):
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        Role.objects.create(name="Marketing", organization=self.organization, created_by=self.user)
        eng_role = Role.objects.create(name="Engineering", organization=self.organization, created_by=self.user)
        res = self.client.patch(
            f"/api/organizations/@current/roles/{eng_role.id}",
            {"name": "marketing"},
        )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(res.json()["code"], "unique")

    def test_returns_correct_results_by_organization(self):
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        self.client.post(
            "/api/organizations/@current/roles",
            {
                "name": "Product",
            },
        )
        self.client.post(
            "/api/organizations/@current/roles",
            {
                "name": "Customer Success",
            },
        )
        other_org = Organization.objects.create(name="other org")
        Role.objects.create(name="Product", organization=other_org)
        self.assertEqual(Role.objects.count(), 3)
        res = self.client.get("/api/organizations/@current/roles")
        results = res.json()
        self.assertEqual(results["count"], 2)
        self.assertNotContains(res, str(other_org.id))
