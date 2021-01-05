from typing import cast

from posthog.models.organization import OrganizationMembership
from posthog.models.user import User

from .base import TransactionBaseTest


class TestOrganizationMembersAPI(TransactionBaseTest):
    TESTS_API = True

    def test_delete_organization_member(self):
        user = User.objects.create_and_join(self.organization, "test@x.com", None, "X")
        membership_queryset = OrganizationMembership.objects.filter(user=user, organization=self.organization)
        self.assertTrue(membership_queryset.exists())
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        response = self.client.delete(f"/api/organizations/@current/members/{user.id}/")
        self.assertEqual(response.status_code, 403)
        self.assertTrue(membership_queryset.exists())
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        response = self.client.delete(f"/api/organizations/@current/members/{user.id}/")
        self.assertEqual(response.status_code, 204)
        self.assertFalse(membership_queryset.exists(), False)

    def test_leave_organization(self):
        membership_queryset = OrganizationMembership.objects.filter(user=self.user, organization=self.organization)
        self.assertEqual(membership_queryset.count(), 1)
        response = self.client.delete(f"/api/organizations/@current/members/{self.user.id}/")
        self.assertEqual(response.status_code, 204)
        self.assertEqual(membership_queryset.count(), 0)

    def test_change_organization_member_level(self):
        self.organization_membership.level = OrganizationMembership.Level.OWNER
        self.organization_membership.save()
        user = User.objects.create_user("test@x.com", None, "X")
        membership = OrganizationMembership.objects.create(user=user, organization=self.organization)
        self.assertEqual(membership.level, OrganizationMembership.Level.MEMBER)
        response = self.client.patch(
            f"/api/organizations/@current/members/{user.id}",
            {"level": OrganizationMembership.Level.ADMIN},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        updated_membership = OrganizationMembership.objects.get(user=user, organization=self.organization)
        self.assertEqual(updated_membership.level, OrganizationMembership.Level.ADMIN)
        response_data = response.json()
        response_data.pop("joined_at")
        response_data.pop("updated_at")
        self.assertDictEqual(
            response_data,
            {
                "membership_id": str(updated_membership.id),
                "user_id": user.id,
                "user_first_name": user.first_name,
                "user_email": user.email,
                "level": OrganizationMembership.Level.ADMIN.value,
            },
        )

    def test_admin_can_promote_to_admin(self):
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        user = User.objects.create_user("test@x.com", None, "X")
        membership = OrganizationMembership.objects.create(user=user, organization=self.organization)
        self.assertEqual(membership.level, OrganizationMembership.Level.MEMBER)
        response = self.client.patch(
            f"/api/organizations/@current/members/{user.id}",
            {"level": OrganizationMembership.Level.ADMIN},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        updated_membership = OrganizationMembership.objects.get(user=user, organization=self.organization)
        self.assertEqual(updated_membership.level, OrganizationMembership.Level.ADMIN)

    def test_change_organization_member_level_requires_admin(self):
        user = User.objects.create_user("test@x.com", None, "X")
        membership = OrganizationMembership.objects.create(user=user, organization=self.organization)
        self.assertEqual(membership.level, OrganizationMembership.Level.MEMBER)
        response = self.client.patch(
            f"/api/organizations/@current/members/{user.id}/",
            {"level": OrganizationMembership.Level.ADMIN},
            content_type="application/json",
        )

        updated_membership = OrganizationMembership.objects.get(user=user, organization=self.organization)
        self.assertEqual(updated_membership.level, OrganizationMembership.Level.MEMBER)
        self.assertDictEqual(
            response.json(),
            {
                "attr": None,
                "code": "permission_denied",
                "detail": "You can only edit others if you are an admin.",
                "type": "authentication_error",
            },
        )
        self.assertEqual(response.status_code, 403)

    def test_cannot_change_own_organization_member_level(self):
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        response = self.client.patch(
            f"/api/organizations/@current/members/{self.user.id}",
            {"level": OrganizationMembership.Level.MEMBER},
            content_type="application/json",
        )
        self.organization_membership.refresh_from_db()
        self.assertEqual(self.organization_membership.level, OrganizationMembership.Level.ADMIN)
        self.assertDictEqual(
            response.json(),
            {
                "attr": None,
                "code": "permission_denied",
                "detail": "You can't change your own access level.",
                "type": "authentication_error",
            },
        )
        self.assertEqual(response.status_code, 403)

    def test_pass_ownership(self):
        user = User.objects.create_user("test@x.com", None, "X")
        membership: OrganizationMembership = OrganizationMembership.objects.create(
            user=user, organization=self.organization
        )
        self.organization_membership.level = OrganizationMembership.Level.OWNER
        self.organization_membership.save()
        response = self.client.patch(
            f"/api/organizations/@current/members/{user.id}/",
            {"level": OrganizationMembership.Level.OWNER},
            content_type="application/json",
        )
        self.organization_membership.refresh_from_db()
        membership.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.organization_membership.level, OrganizationMembership.Level.ADMIN)
        self.assertEqual(membership.level, OrganizationMembership.Level.OWNER)
        self.assertEqual(
            OrganizationMembership.objects.filter(
                organization=self.organization, level=OrganizationMembership.Level.OWNER
            ).count(),
            1,
        )

    def test_pass_ownership_only_if_owner(self):
        user = User.objects.create_user("test@x.com", None, "X")
        membership: OrganizationMembership = OrganizationMembership.objects.create(
            user=user, organization=self.organization
        )
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        response = self.client.patch(
            f"/api/organizations/@current/members/{user.id}/",
            {"level": OrganizationMembership.Level.OWNER},
            content_type="application/json",
        )
        self.organization_membership.refresh_from_db()
        membership.refresh_from_db()
        self.assertDictEqual(
            response.json(),
            {
                "attr": None,
                "code": "permission_denied",
                "detail": "You can only pass on organization ownership if you're its owner.",
                "type": "authentication_error",
            },
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.organization_membership.level, OrganizationMembership.Level.ADMIN)
        self.assertEqual(membership.level, OrganizationMembership.Level.MEMBER)
