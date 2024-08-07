from unittest.mock import call, patch

from rest_framework import status

from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.user import User
from posthog.test.base import APIBaseTest, QueryMatchingTest


class TestOrganizationMembersAPI(APIBaseTest, QueryMatchingTest):
    def test_list_organization_members(self):
        User.objects.create_and_join(self.organization, "1@posthog.com", None)
        User.objects.create_and_join(self.organization, "2@posthog.com", None, is_active=False)

        response = self.client.get("/api/organizations/@current/members/")
        response_data = response.json()["results"]

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        instance = OrganizationMembership.objects.get(id=response_data[0]["id"])
        # self.user + first created user should be counted, second created user shouldn't as they're deactivated
        self.assertEqual(len(response_data), 2)
        self.assertEqual(response_data[0]["user"]["uuid"], str(instance.user.uuid))
        self.assertEqual(response_data[0]["user"]["first_name"], instance.user.first_name)

    # def test_list_organization_members_is_not_nplus1(self):
    #     self.user.totpdevice_set.create(name="default", key=random_hex(), digits=6)  # type: ignore
    #     with self.assertNumQueries(9), snapshot_postgres_queries_context(self):
    #         response = self.client.get("/api/organizations/@current/members/")

    #     assert len(response.json()["results"]) == 1

    #     User.objects.create_and_join(self.organization, "1@posthog.com", None)

    #     with self.assertNumQueries(9), snapshot_postgres_queries_context(self):
    #         response = self.client.get("/api/organizations/@current/members/")

    #     assert len(response.json()["results"]) == 2

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

    @patch("posthog.models.user.User.update_billing_organization_users")
    def test_delete_organization_member(self, mock_update_billing_organization_users):
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

        assert mock_update_billing_organization_users.call_count == 2
        assert mock_update_billing_organization_users.call_args_list == [
            call(self.organization),
            call(self.organization),
        ]

    @patch("posthog.models.user.User.update_billing_organization_users")
    def test_leave_organization(self, mock_update_billing_organization_users):
        membership_queryset = OrganizationMembership.objects.filter(user=self.user, organization=self.organization)
        self.assertEqual(membership_queryset.count(), 1)
        response = self.client.delete(f"/api/organizations/@current/members/{self.user.uuid}/")
        self.assertEqual(response.status_code, 204)
        self.assertEqual(membership_queryset.count(), 0)

        assert mock_update_billing_organization_users.call_count == 1
        assert mock_update_billing_organization_users.call_args_list == [
            call(self.organization),
        ]

    @patch("posthog.models.user.User.update_billing_organization_users")
    def test_change_organization_member_level(self, mock_update_billing_organization_users):
        self.organization_membership.level = OrganizationMembership.Level.OWNER
        self.organization_membership.save()
        user = User.objects.create_user("test@x.com", None, "X")
        membership = OrganizationMembership.objects.create(user=user, organization=self.organization)
        self.assertEqual(membership.level, OrganizationMembership.Level.MEMBER)
        response = self.client.patch(
            f"/api/organizations/@current/members/{user.uuid}",
            {"level": OrganizationMembership.Level.ADMIN},
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
                "is_2fa_enabled": False,
                "has_social_auth": False,
                "user": {
                    "id": user.id,
                    "uuid": str(user.uuid),
                    "distinct_id": str(user.distinct_id),
                    "first_name": user.first_name,
                    "last_name": user.last_name,
                    "email": user.email,
                    "is_email_verified": None,
                    "hedgehog_config": None,
                },
                "level": OrganizationMembership.Level.ADMIN.value,
            },
        )
        assert mock_update_billing_organization_users.call_count == 1
        assert mock_update_billing_organization_users.call_args_list == [
            call(self.organization),
        ]

    @patch("posthog.models.user.User.update_billing_organization_users")
    def test_admin_can_promote_to_admin(self, mock_update_billing_organization_users):
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        user = User.objects.create_user("test@x.com", None, "X")
        membership = OrganizationMembership.objects.create(user=user, organization=self.organization)
        self.assertEqual(membership.level, OrganizationMembership.Level.MEMBER)
        response = self.client.patch(
            f"/api/organizations/@current/members/{user.uuid}",
            {"level": OrganizationMembership.Level.ADMIN},
        )
        self.assertEqual(response.status_code, 200)
        updated_membership = OrganizationMembership.objects.get(user=user, organization=self.organization)
        self.assertEqual(updated_membership.level, OrganizationMembership.Level.ADMIN)

        assert mock_update_billing_organization_users.call_count == 1
        assert mock_update_billing_organization_users.call_args_list == [
            call(self.organization),
        ]

    @patch("posthog.models.user.User.update_billing_organization_users")
    def test_change_organization_member_level_requires_admin(self, mock_update_billing_organization_users):
        user = User.objects.create_user("test@x.com", None, "X")
        membership = OrganizationMembership.objects.create(user=user, organization=self.organization)
        self.assertEqual(membership.level, OrganizationMembership.Level.MEMBER)
        response = self.client.patch(
            f"/api/organizations/@current/members/{user.uuid}/",
            {"level": OrganizationMembership.Level.ADMIN},
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

        assert mock_update_billing_organization_users.call_count == 0

    def test_cannot_change_own_organization_member_level(self):
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        response = self.client.patch(
            f"/api/organizations/@current/members/{self.user.uuid}",
            {"level": OrganizationMembership.Level.MEMBER},
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

    def test_add_another_owner(self):
        user = User.objects.create_user("test@x.com", None, "X")
        membership: OrganizationMembership = OrganizationMembership.objects.create(
            user=user, organization=self.organization
        )
        self.organization_membership.level = OrganizationMembership.Level.OWNER
        self.organization_membership.save()
        response = self.client.patch(
            f"/api/organizations/@current/members/{user.uuid}/",
            {"level": OrganizationMembership.Level.OWNER},
        )
        self.organization_membership.refresh_from_db()
        membership.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.organization_membership.level, OrganizationMembership.Level.OWNER)
        self.assertEqual(membership.level, OrganizationMembership.Level.OWNER)
        self.assertEqual(
            OrganizationMembership.objects.filter(
                organization=self.organization, level=OrganizationMembership.Level.OWNER
            ).count(),
            2,
        )

    def test_add_owner_only_if_owner(self):
        user = User.objects.create_user("test@x.com", None, "X")
        membership: OrganizationMembership = OrganizationMembership.objects.create(
            user=user, organization=self.organization
        )
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        response = self.client.patch(
            f"/api/organizations/@current/members/{user.uuid}/",
            {"level": OrganizationMembership.Level.OWNER},
        )
        self.organization_membership.refresh_from_db()
        membership.refresh_from_db()
        self.assertDictEqual(
            response.json(),
            {
                "attr": None,
                "code": "permission_denied",
                "detail": "You can only make another member owner if you're this organization's owner.",
                "type": "authentication_error",
            },
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.organization_membership.level, OrganizationMembership.Level.ADMIN)
        self.assertEqual(membership.level, OrganizationMembership.Level.MEMBER)
