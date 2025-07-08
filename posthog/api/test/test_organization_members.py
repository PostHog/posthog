from unittest.mock import call, patch, ANY

from rest_framework import status
from datetime import timedelta

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

    @patch("posthoganalytics.capture")
    @patch("posthog.models.user.User.update_billing_organization_users")
    def test_delete_organization_member(self, mock_update_billing_organization_users, mock_capture):
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

        mock_capture.assert_called_with(
            distinct_id=self.user.distinct_id,  # requesting user
            event="organization member removed",
            properties={
                "removed_member_id": user.distinct_id,
                "removed_by_id": self.user.distinct_id,
                "organization_id": self.organization.id,
                "organization_name": self.organization.name,
                "removal_type": "removed_by_other",
                "removed_email": user.email,
                "removed_user_id": user.id,
            },
            groups={"instance": "http://localhost:8010", "organization": str(self.organization.id)},
        )
        assert mock_update_billing_organization_users.call_count == 2
        assert mock_update_billing_organization_users.call_args_list == [
            call(self.organization),
            call(self.organization),
        ]

    def test_scoped_api_keys_endpoint(self):
        # Create a user who is a member of the organization
        user = User.objects.create_and_join(self.organization, "test@x.com", None, "X")

        # Initially, the user has no scoped API keys
        response = self.client.get(f"/api/organizations/@current/members/{user.uuid}/scoped_api_keys/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data = response.json()
        self.assertEqual(response_data["has_keys"], False)
        self.assertEqual(response_data["has_keys_active_last_week"], False)
        self.assertEqual(response_data["keys"], [])

        # Create a personal API key with scoped organizations
        from posthog.models.personal_api_key import PersonalAPIKey
        from django.utils import timezone
        from posthog.models.team.team import Team

        # Create a key that hasn't been used recently - scoped to organization
        old_key = PersonalAPIKey.objects.create(
            user=user,
            label="Old Org Key",
            scoped_organizations=[str(self.organization.id)],
            last_used_at=timezone.now() - timedelta(days=14),
        )

        # Check response with one inactive key
        response = self.client.get(f"/api/organizations/@current/members/{user.uuid}/scoped_api_keys/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data = response.json()
        self.assertEqual(response_data["has_keys"], True)
        self.assertEqual(response_data["has_keys_active_last_week"], False)
        self.assertEqual(len(response_data["keys"]), 1)
        self.assertEqual(response_data["keys"][0]["name"], "Old Org Key")
        self.assertEqual(
            response_data["keys"][0]["last_used_at"],
            old_key.last_used_at.isoformat().replace("+00:00", "Z") if old_key.last_used_at else None,
        )

        # Create a key that has been used recently - scoped to team
        team_key = PersonalAPIKey.objects.create(
            user=user,
            label="Team Key",
            scoped_teams=[self.team.id],
            last_used_at=timezone.now() - timedelta(days=2),
        )

        # Create a key with no scoped teams or organizations (applies to all orgs/teams)
        global_key = PersonalAPIKey.objects.create(
            user=user,
            label="Global Key",
            scoped_teams=[],
            scoped_organizations=[],
            last_used_at=timezone.now() - timedelta(days=1),
        )

        # Check response with all keys (one org-scoped, one team-scoped, one global)
        response = self.client.get(f"/api/organizations/@current/members/{user.uuid}/scoped_api_keys/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data = response.json()
        self.assertEqual(response_data["has_keys"], True)
        self.assertEqual(response_data["has_keys_active_last_week"], True)
        self.assertEqual(len(response_data["keys"]), 3)

        # Verify all keys are in the response with correct data
        key_names = [k["name"] for k in response_data["keys"]]
        self.assertIn("Old Org Key", key_names)
        self.assertIn("Team Key", key_names)
        self.assertIn("Global Key", key_names)

        # Find each key in the response and verify its last_used_at
        for key_data in response_data["keys"]:
            if key_data["name"] == "Old Org Key":
                self.assertEqual(
                    key_data["last_used_at"],
                    old_key.last_used_at.isoformat().replace("+00:00", "Z") if old_key.last_used_at else None,
                )
            elif key_data["name"] == "Team Key":
                self.assertEqual(
                    key_data["last_used_at"],
                    team_key.last_used_at.isoformat().replace("+00:00", "Z") if team_key.last_used_at else None,
                )
            elif key_data["name"] == "Global Key":
                self.assertEqual(
                    key_data["last_used_at"],
                    global_key.last_used_at.isoformat().replace("+00:00", "Z") if global_key.last_used_at else None,
                )

        # Create a key with null scoped teams and organizations (also applies to all orgs/teams)
        PersonalAPIKey.objects.create(
            user=user,
            label="Null Scoped Key",
            scoped_teams=None,
            scoped_organizations=None,
            last_used_at=timezone.now() - timedelta(days=3),
        )

        # Check response with all keys including the null scoped key
        response = self.client.get(f"/api/organizations/@current/members/{user.uuid}/scoped_api_keys/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data = response.json()
        self.assertEqual(len(response_data["keys"]), 4)
        key_names = [k["name"] for k in response_data["keys"]]
        self.assertIn("Null Scoped Key", key_names)

        # Test with a user who doesn't have scoped API keys for this organization or its teams
        other_org = Organization.objects.create(name="Other Org")
        other_user = User.objects.create_and_join(other_org, "other@x.com", None, "Other")
        other_team = Team.objects.create(organization=other_org, name="Other Team", project=self.team.project)

        # Create a key scoped to the other organization
        PersonalAPIKey.objects.create(user=other_user, label="Other Org Key", scoped_organizations=[str(other_org.id)])

        # Create a key scoped to the other team
        PersonalAPIKey.objects.create(user=other_user, label="Other Team Key", scoped_teams=[other_team.id])

        # Add the other user to our organization
        other_user.join(organization=self.organization)

        # The endpoint should return empty data since the API keys are not scoped to our organization or its teams
        response = self.client.get(f"/api/organizations/@current/members/{other_user.uuid}/scoped_api_keys/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data = response.json()
        self.assertEqual(response_data["has_keys"], False)
        self.assertEqual(response_data["has_keys_active_last_week"], False)
        self.assertEqual(response_data["keys"], [])

    @patch("posthoganalytics.capture")
    @patch("posthog.models.user.User.update_billing_organization_users")
    def test_leave_organization(self, mock_update_billing_organization_users, mock_capture):
        membership_queryset = OrganizationMembership.objects.filter(user=self.user, organization=self.organization)
        self.assertEqual(membership_queryset.count(), 1)
        response = self.client.delete(f"/api/organizations/@current/members/{self.user.uuid}/")
        self.assertEqual(response.status_code, 204)
        self.assertEqual(membership_queryset.count(), 0)

        mock_capture.assert_called_with(
            distinct_id=self.user.distinct_id,
            event="organization member removed",
            properties={
                "removed_member_id": self.user.distinct_id,
                "removed_by_id": self.user.distinct_id,
                "organization_id": self.organization.id,
                "organization_name": self.organization.name,
                "removal_type": "self_removal",
                "removed_email": self.user.email,
                "removed_user_id": self.user.id,
            },
            groups={"instance": ANY, "organization": str(self.organization.id)},
        )

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
        response_data.pop("last_login")
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
                    "role_at_organization": None,
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

    def test_list_organization_members_filter_by_email(self):
        # Create additional users
        user1 = User.objects.create_and_join(self.organization, "specific@posthog.com", None)
        User.objects.create_and_join(self.organization, "another@posthog.com", None)

        # Test filtering by email
        response = self.client.get("/api/organizations/@current/members/?email=specific@posthog.com")
        response_data = response.json()["results"]

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response_data), 1)
        self.assertEqual(response_data[0]["user"]["email"], "specific@posthog.com")
        self.assertEqual(response_data[0]["user"]["uuid"], str(user1.uuid))
