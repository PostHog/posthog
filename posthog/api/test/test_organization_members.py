from typing import Optional, Type

from posthog.models import Organization
from posthog.models.organization import OrganizationMembership
from posthog.models.user import User

from .base import TransactionBaseTest


class TestOrganizationMembersAPI(TransactionBaseTest):
    TESTS_API = True

    def test_add_organization_member(self):
        user = User.objects.create_user("test@x.com")
        response = self.client.put(f"/api/organization/members/{user.id}")
        self.assertEqual(response.status_code, 201)
        membership_queryset = OrganizationMembership.objects.filter(user=user, organization=self.organization)
        self.assertTrue(membership_queryset.exists())
        response_data = response.json()
        response_data.pop("joined_at")
        response_data.pop("update_at")
        self.assertDictEqual(
            response_data,
            {
                "membership_id": membership_queryset.get().id,
                "user_id": user.id,
                "user_first_name": user.first_name,
                "user_email": user.email,
                "level": OrganizationMembership.Level.MEMBER,
            },
        )

    def test_delete_organization_member(self):
        user = User.objects.create_user("test@x.com")
        OrganizationMembership.objects.create(user=user, organization=self.organization)
        response = self.client.delete(f"/api/organization/members/{user.id}/")
        self.assertEqual(response.status_code, 201)
        membership_queryset = OrganizationMembership.objects.filter(user=user, organization=self.organization)
        self.assertFalse(membership_queryset.exists())

    def test_change_organization_member_level(self):
        user = User.objects.create_user("test@x.com")
        membership = OrganizationMembership.objects.create(user=user, organization=self.organization)
        self.assertEqual(membership.level, OrganizationMembership.Level.MEMBER)
        response = self.client.patch(
            f"/api/organization/members/{user.id}", {"level": OrganizationMembership.Level.ADMIN}
        )
        self.assertEqual(response.status_code, 200)
        updated_membership = OrganizationMembership.objects.get(user=user, organization=self.organization)
        self.assertEqual(updated_membership.level, OrganizationMembership.Level.ADMIN)
        response_data = response.json()
        response_data.pop("joined_at")
        response_data.pop("update_at")
        self.assertDictEqual(
            response_data,
            {
                "membership_id": updated_membership.id,
                "user_id": user.id,
                "user_first_name": user.first_name,
                "user_email": user.email,
                "level": OrganizationMembership.Level.ADMIN,
            },
        )

    def test_change_organization_member_level_requires_admin(self):
        self.organization_membership_admin.level = OrganizationMembership.Level.MEMBER
        user = User.objects.create_user("test@x.com")
        membership = OrganizationMembership.objects.create(user=user, organization=self.organization)
        self.assertEqual(membership.level, OrganizationMembership.Level.MEMBER)
        response = self.client.patch(
            f"/api/organization/members/{user.id}/", {"level": OrganizationMembership.Level.ADMIN}
        )
        self.assertEqual(response.status_code, 403)
        updated_membership = OrganizationMembership.objects.get(user=user, organization=self.organization)
        self.assertEqual(updated_membership.level, OrganizationMembership.Level.MEMBER)
        response_data = response.json()
        self.assertDictEqual(response_data, {"status": 403, "detail": "You are not permitted to elevate member level."})
