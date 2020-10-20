from typing import Optional, Type

from posthog.models import Organization
from posthog.models.organization import OrganizationMembership
from posthog.models.user import User

from .base import TransactionBaseTest


class TestOrganizationMembersAPI(TransactionBaseTest):
    TESTS_API = True

    def test_delete_organization_member(self):
        user = User.objects.create_user("test@x.com", None, "X")
        OrganizationMembership.objects.create(user=user, organization=self.organization)
        membership_queryset = OrganizationMembership.objects.filter(user=user, organization=self.organization)
        self.assertEqual(membership_queryset.count(), 1)
        response = self.client.delete(f"/api/organizations/@current/members/{user.id}/")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(membership_queryset.count(), 1)
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        response = self.client.delete(f"/api/organizations/@current/members/{user.id}/")
        self.assertEqual(response.status_code, 204)
        self.assertEqual(membership_queryset.count(), 0)

    def test_leave_organization(self):
        membership_queryset = OrganizationMembership.objects.filter(user=self.user, organization=self.organization)
        self.assertEqual(membership_queryset.count(), 1)
        response = self.client.delete(f"/api/organizations/@current/members/{self.user.id}/")
        self.assertEqual(response.status_code, 204)
        self.assertEqual(membership_queryset.count(), 0)

    def test_change_organization_member_level(self):
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
                "detail": "Your cannot edit other organization members or remove anyone but yourself.",
                "type": "authentication_error",
            },
        )
        self.assertEqual(response.status_code, 403)
