from rest_framework import status

from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.user import User
from posthog.test.base import APIBaseTest


class TestOrganizationMembersAPI(APIBaseTest):
    def test_list_organization_members(self):

        response = self.client.get("/api/organizations/@current/members/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        response_data = response.json()["results"]
        self.assertEqual(len(response_data), self.organization.members.count())
        instance = OrganizationMembership.objects.get(id=response_data[0]["id"])
        self.assertEqual(response_data[0]["user"]["uuid"], str(instance.user.uuid))
        self.assertEqual(response_data[0]["user"]["first_name"], instance.user.first_name)

    def test_cant_list_members_for_an_alien_organization(self):
        org = Organization.objects.create(name="Alien Org")
        user = User.objects.create(email="another_user@posthog.com")
        user.join(organization=org)

        response = self.client.get(f"/api/organizations/{org.id}/members/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.json(), self.permission_denied_response())

        # Even though there's no retrieve for invites, permissions are validated first
        response = self.client.get(f"/api/organizations/{org.id}/members/{user.uuid}")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.json(), self.permission_denied_response())

    def test_delete_organization_member(self):
        user = User.objects.create_and_join(self.organization, "test@x.com", None, "X")
        membership_queryset = OrganizationMembership.objects.filter(user=user, organization=self.organization)
        self.assertTrue(membership_queryset.exists())
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        response = self.client.delete(f"/api/organizations/@current/members/{user.uuid}/")
        self.assertEqual(response.status_code, 403)
        self.assertTrue(membership_queryset.exists())
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        response = self.client.delete(f"/api/organizations/@current/members/{user.uuid}/")
        self.assertEqual(response.status_code, 204)
        self.assertFalse(membership_queryset.exists(), False)

    def test_leave_organization(self):
        membership_queryset = OrganizationMembership.objects.filter(user=self.user, organization=self.organization)
        self.assertEqual(membership_queryset.count(), 1)
        response = self.client.delete(f"/api/organizations/@current/members/{self.user.uuid}/")
        self.assertEqual(response.status_code, 204)
        self.assertEqual(membership_queryset.count(), 0)

    def test_change_organization_member_level(self):
        self.organization_membership.level = OrganizationMembership.Level.OWNER
        self.organization_membership.save()
        user = User.objects.create_user("test@x.com", None, "X")
        membership = OrganizationMembership.objects.create(user=user, organization=self.organization)
        self.assertEqual(membership.level, OrganizationMembership.Level.MEMBER)
        response = self.client.patch(
            f"/api/organizations/@current/members/{user.uuid}", {"level": OrganizationMembership.Level.ADMIN},
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
                "id": str(updated_membership.id),
                "user": {
                    "id": user.id,
                    "uuid": str(user.uuid),
                    "distinct_id": str(user.distinct_id),
                    "first_name": user.first_name,
                    "email": user.email,
                },
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
            f"/api/organizations/@current/members/{user.uuid}", {"level": OrganizationMembership.Level.ADMIN},
        )
        self.assertEqual(response.status_code, 200)
        updated_membership = OrganizationMembership.objects.get(user=user, organization=self.organization)
        self.assertEqual(updated_membership.level, OrganizationMembership.Level.ADMIN)

    def test_change_organization_member_level_requires_admin(self):
        user = User.objects.create_user("test@x.com", None, "X")
        membership = OrganizationMembership.objects.create(user=user, organization=self.organization)
        self.assertEqual(membership.level, OrganizationMembership.Level.MEMBER)
        response = self.client.patch(
            f"/api/organizations/@current/members/{user.uuid}/", {"level": OrganizationMembership.Level.ADMIN},
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
            f"/api/organizations/@current/members/{self.user.uuid}", {"level": OrganizationMembership.Level.MEMBER},
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
            f"/api/organizations/@current/members/{user.uuid}/", {"level": OrganizationMembership.Level.OWNER},
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
            f"/api/organizations/@current/members/{user.uuid}/", {"level": OrganizationMembership.Level.OWNER},
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
