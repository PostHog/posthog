import random
from unittest.mock import ANY, patch

from django.core import mail
from freezegun import freeze_time
from rest_framework import status

from ee.models.explicit_team_membership import ExplicitTeamMembership
from posthog.models.instance_setting import set_instance_setting
from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.organization_invite import OrganizationInvite
from posthog.models.team.team import Team
from posthog.test.base import APIBaseTest
from posthog.constants import AvailableFeature

NAME_SEEDS = ["John", "Jane", "Alice", "Bob", ""]


class TestOrganizationInvitesAPI(APIBaseTest):
    def helper_generate_bulk_invite_payload(self, count: int):
        payload = []

        for i in range(0, count):
            payload.append(
                {
                    "target_email": f"test+{random.randint(1000000, 9999999)}@posthog.com",
                    "first_name": NAME_SEEDS[i % len(NAME_SEEDS)],
                }
            )

        return payload

    # Listing invites

    def test_cant_list_invites_for_an_alien_organization(self):
        org = Organization.objects.create(name="Alien Org")
        invite = OrganizationInvite.objects.create(target_email="siloed@posthog.com", organization=org)

        response = self.client.get(f"/api/organizations/{org.id}/invites/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.json(), self.permission_denied_response())

        # Even though there's no retrieve for invites, permissions are validated first
        response = self.client.get(f"/api/organizations/{org.id}/invites/{invite.id}")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.json(), self.permission_denied_response())

    # Creating invites

    @patch("posthoganalytics.capture")
    def test_add_organization_invite_email_required(self, mock_capture):
        response = self.client.post("/api/organizations/@current/invites/")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        response_data = response.json()
        self.assertDictEqual(
            response_data,
            {
                "type": "validation_error",
                "code": "required",
                "detail": "This field is required.",
                "attr": "target_email",
            },
        )

        mock_capture.assert_not_called()

    @patch("posthoganalytics.capture")
    def test_add_organization_invite_with_email(self, mock_capture):
        set_instance_setting("EMAIL_HOST", "localhost")
        email = "x@x.com"

        with self.settings(EMAIL_ENABLED=True, SITE_URL="http://test.posthog.com"):
            response = self.client.post(
                "/api/organizations/@current/invites/",
                {"target_email": email},
            )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(OrganizationInvite.objects.exists())
        response_data = response.json()
        invite_id = response_data.pop("id")
        response_data.pop("created_at")
        response_data.pop("updated_at")
        self.assertDictEqual(
            response_data,
            {
                "target_email": email,
                "first_name": "",
                "created_by": {
                    "id": self.user.id,
                    "uuid": str(self.user.uuid),
                    "distinct_id": self.user.distinct_id,
                    "email": self.user.email,
                    "first_name": self.user.first_name,
                    "last_name": self.user.last_name,
                    "is_email_verified": self.user.is_email_verified,
                    "hedgehog_config": None,
                    "role_at_organization": None,
                },
                "is_expired": False,
                "level": 1,
                "emailing_attempt_made": True,
                "message": None,
                "private_project_access": [],
            },
        )

        capture_props = {
            "name_provided": False,
            "current_invite_count": 1,
            "current_member_count": 1,
            "email_available": True,
            "is_bulk": False,
        }

        # Assert capture call for invitee
        mock_capture.assert_any_call(
            event="user invited",
            distinct_id=f"invite_{invite_id}",
            properties=capture_props,
            groups={"instance": ANY, "organization": str(self.team.organization_id)},
        )

        # Assert capture call for inviting party
        mock_capture.assert_any_call(
            event="team member invited",
            distinct_id=self.user.distinct_id,
            properties={**capture_props, "$current_url": None, "$session_id": None},
            groups={
                "instance": ANY,
                "organization": str(self.team.organization_id),
                "project": str(self.team.uuid),
            },
        )

        self.assertEqual(mock_capture.call_count, 2)

        # Assert invite email is sent
        self.assertEqual(len(mail.outbox), 1)
        self.assertListEqual(mail.outbox[0].to, [email])
        self.assertEqual(mail.outbox[0].reply_to, [self.user.email])  # Reply-To is set to the inviting user

    @patch("posthoganalytics.capture")
    def test_add_organization_invite_with_email_on_instance_but_send_email_prop_false(self, mock_capture):
        """
        Email is available on the instance, but the user creating the invite does not want to send an email to the invitee.
        """
        set_instance_setting("EMAIL_HOST", "localhost")
        email = "x@x.com"

        with self.settings(EMAIL_ENABLED=True, SITE_URL="http://test.posthog.com"):
            response = self.client.post(
                "/api/organizations/@current/invites/", {"target_email": email, "send_email": False}
            )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(OrganizationInvite.objects.exists())

        # Assert invite email is not sent
        self.assertEqual(len(mail.outbox), 0)

    def test_create_invites_for_the_same_email_multiple_times_deletes_older_invites(self):
        email = "x@posthog.com"
        count = OrganizationInvite.objects.count()

        for _ in range(0, 3):
            response = self.client.post("/api/organizations/@current/invites/", {"target_email": email})
            self.assertEqual(response.status_code, status.HTTP_201_CREATED)
            obj = OrganizationInvite.objects.get(id=response.json()["id"])
            self.assertEqual(obj.target_email, email)
            self.assertEqual(obj.created_by, self.user)

        self.assertEqual(OrganizationInvite.objects.count(), count + 1)

    def test_can_specify_private_project_access_in_invite(self):
        email = "x@posthog.com"
        count = OrganizationInvite.objects.count()
        private_team = Team.objects.create(organization=self.organization, name="Private Team", access_control=True)
        ExplicitTeamMembership.objects.create(
            team=private_team,
            parent_membership=self.organization_membership,
            level=ExplicitTeamMembership.Level.ADMIN,
        )
        response = self.client.post(
            "/api/organizations/@current/invites/",
            {
                "target_email": email,
                "level": OrganizationMembership.Level.MEMBER,
                "private_project_access": [{"id": private_team.id, "level": ExplicitTeamMembership.Level.ADMIN}],
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        obj = OrganizationInvite.objects.get(id=response.json()["id"])
        self.assertEqual(obj.level, OrganizationMembership.Level.MEMBER)
        self.assertEqual(
            obj.private_project_access, [{"id": private_team.id, "level": ExplicitTeamMembership.Level.ADMIN}]
        )
        self.assertEqual(OrganizationInvite.objects.count(), count + 1)

        # if member of org but admin of team, should be able to invite new project admins to private project
        org_membership = OrganizationMembership.objects.get(user=self.user, organization=self.organization)
        org_membership.level = OrganizationMembership.Level.MEMBER
        org_membership.save()
        email = "y@posthog.com"
        count = OrganizationInvite.objects.count()
        response = self.client.post(
            "/api/organizations/@current/invites/",
            {
                "target_email": email,
                "level": OrganizationMembership.Level.MEMBER,
                "private_project_access": [{"id": private_team.id, "level": ExplicitTeamMembership.Level.ADMIN}],
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        obj = OrganizationInvite.objects.get(id=response.json()["id"])
        self.assertEqual(obj.level, OrganizationMembership.Level.MEMBER)
        self.assertEqual(
            obj.private_project_access, [{"id": private_team.id, "level": ExplicitTeamMembership.Level.ADMIN}]
        )
        self.assertEqual(OrganizationInvite.objects.count(), count + 1)

    def test_can_invite_to_private_project_if_user_has_implicit_access_to_team(self):
        """
        Org admins and owners can invite to any private project, even if they're not an explicit admin of the team
        because they have implicit access due to their org membership level.
        """
        org_membership = OrganizationMembership.objects.get(user=self.user, organization=self.organization)
        org_membership.level = OrganizationMembership.Level.ADMIN
        org_membership.save()

        email = "x@posthog.com"
        count = OrganizationInvite.objects.count()
        private_team = Team.objects.create(organization=self.organization, name="Private Team", access_control=True)
        response = self.client.post(
            "/api/organizations/@current/invites/",
            {
                "target_email": email,
                "level": OrganizationMembership.Level.MEMBER,
                "private_project_access": [{"id": private_team.id, "level": ExplicitTeamMembership.Level.ADMIN}],
            },
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        obj = OrganizationInvite.objects.get(id=response.json()["id"])
        self.assertEqual(obj.level, OrganizationMembership.Level.MEMBER)
        self.assertEqual(
            obj.private_project_access, [{"id": private_team.id, "level": ExplicitTeamMembership.Level.ADMIN}]
        )
        self.assertEqual(OrganizationInvite.objects.count(), count + 1)
        # reset the org membership level in case it's used in other tests
        org_membership.level = OrganizationMembership.Level.MEMBER
        org_membership.save()

    def test_invite_fails_if_team_in_private_project_access_not_in_org(self):
        email = "x@posthog.com"
        count = OrganizationInvite.objects.count()
        other_org = Organization.objects.create(name="Other Org")
        team_in_other_org = Team.objects.create(organization=other_org, name="Private Team", access_control=True)
        response = self.client.post(
            "/api/organizations/@current/invites/",
            {
                "target_email": email,
                "level": OrganizationMembership.Level.MEMBER,
                "private_project_access": [{"id": team_in_other_org.id, "level": ExplicitTeamMembership.Level.ADMIN}],
            },
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        response_data = response.json()
        self.assertDictEqual(
            {
                "type": "validation_error",
                "code": "invalid_input",
                "detail": "Project does not exist on this organization, or it is private and you do not have access to it.",
                "attr": "private_project_access",
            },
            response_data,
        )
        self.assertEqual(OrganizationInvite.objects.count(), count)

    def test_invite_fails_if_inviter_does_not_have_access_to_team(self):
        email = "xx@posthog.com"
        count = OrganizationInvite.objects.count()
        private_team = Team.objects.create(organization=self.organization, name="Private Team", access_control=True)
        response = self.client.post(
            "/api/organizations/@current/invites/",
            {
                "target_email": email,
                "level": OrganizationMembership.Level.MEMBER,
                "private_project_access": [{"id": private_team.id, "level": ExplicitTeamMembership.Level.ADMIN}],
            },
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        response_data = response.json()
        self.assertDictEqual(
            {
                "type": "validation_error",
                "code": "invalid_input",
                "detail": "Project does not exist on this organization, or it is private and you do not have access to it.",
                "attr": "private_project_access",
            },
            response_data,
        )
        self.assertEqual(OrganizationInvite.objects.count(), count)

    def test_invite_fails_if_inviter_level_is_lower_than_requested_level(self):
        email = "x@posthog.com"
        count = OrganizationInvite.objects.count()
        private_team = Team.objects.create(organization=self.organization, name="Private Team", access_control=True)
        organization_membership = OrganizationMembership.objects.get(user=self.user, organization=self.organization)
        organization_membership.level = OrganizationMembership.Level.MEMBER
        organization_membership.save()
        ExplicitTeamMembership.objects.create(
            team=private_team,
            parent_membership=self.organization_membership,
            level=ExplicitTeamMembership.Level.MEMBER,
        )
        response = self.client.post(
            "/api/organizations/@current/invites/",
            {
                "target_email": email,
                "level": OrganizationMembership.Level.MEMBER,
                "private_project_access": [{"id": private_team.id, "level": ExplicitTeamMembership.Level.ADMIN}],
            },
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        response_data = response.json()
        self.assertDictEqual(
            {
                "type": "validation_error",
                "code": "invalid_input",
                "detail": "You cannot invite to a private project with a higher level than your own.",
                "attr": "private_project_access",
            },
            response_data,
        )
        self.assertEqual(OrganizationInvite.objects.count(), count)

    def test_cannot_create_invite_for_another_org(self):
        another_org = Organization.objects.create(name="Another Org")

        count = OrganizationInvite.objects.count()
        email = "x@posthog.com"
        response = self.client.post(f"/api/organizations/{another_org.id}/invites/", {"target_email": email})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.json(), self.permission_denied_response())

        self.assertEqual(OrganizationInvite.objects.count(), count)

    # Bulk create invites

    @patch("posthoganalytics.capture")
    def test_allow_bulk_creating_invites(self, mock_capture):
        set_instance_setting("EMAIL_HOST", "localhost")

        count = OrganizationInvite.objects.count()
        payload = self.helper_generate_bulk_invite_payload(7)

        with self.settings(EMAIL_ENABLED=True, SITE_URL="http://test.posthog.com"):
            response = self.client.post(
                "/api/organizations/@current/invites/bulk/",
                payload,
                format="json",
                headers={"X-Posthog-Session-Id": "123", "Referer": "http://test.posthog.com/my-url"},
            )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        response_data = response.json()

        self.assertEqual(OrganizationInvite.objects.count(), count + 7)

        self.assertEqual(len(response_data), 7)

        # Check objects are properly saved and response matches
        for i, item in enumerate(response_data):
            instance = OrganizationInvite.objects.get(id=item["id"])
            self.assertEqual(instance.target_email, payload[i]["target_email"])
            self.assertEqual(instance.target_email, item["target_email"])
            self.assertEqual(instance.first_name, payload[i]["first_name"])
            self.assertEqual(instance.first_name, item["first_name"])

        # Emails should be sent
        self.assertEqual(len(mail.outbox), 7)

        # Assert capture was called
        mock_capture.assert_any_call(
            event="bulk invite executed",
            distinct_id=self.user.distinct_id,
            properties={
                "invitee_count": 7,
                "name_count": sum(1 for user in payload if user["first_name"]),
                "current_invite_count": 7,
                "current_member_count": 1,
                "email_available": True,
                "$session_id": "123",
                "$current_url": "http://test.posthog.com/my-url",
            },
            groups={
                "instance": ANY,
                "organization": str(self.team.organization_id),
                "project": str(self.team.uuid),
            },
        )

        # Assert capture call for invitee
        mock_capture.assert_any_call(
            event="user invited",
            distinct_id=f"invite_{OrganizationInvite.objects.last().id}",  # type: ignore
            properties={
                "name_provided": True,
                "current_invite_count": 7,
                "current_member_count": 1,
                "email_available": True,
                "is_bulk": True,
            },
            groups={"instance": ANY, "organization": str(self.team.organization_id)},
        )

    def test_maximum_20_invites_per_request(self):
        count = OrganizationInvite.objects.count()
        payload = self.helper_generate_bulk_invite_payload(21)

        with self.settings(
            EMAIL_ENABLED=True,
            EMAIL_HOST="localhost",
            SITE_URL="http://test.posthog.com",
        ):
            response = self.client.post("/api/organizations/@current/invites/bulk/", payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json(),
            {
                "type": "validation_error",
                "code": "max_length",
                "detail": "A maximum of 20 invites can be sent in a single request.",
                "attr": None,
            },
        )

        # No invites created
        self.assertEqual(OrganizationInvite.objects.count(), count)

        # No emails should be sent
        self.assertEqual(len(mail.outbox), 0)

    def test_invites_are_created_atomically(self):
        count = OrganizationInvite.objects.count()
        payload = self.helper_generate_bulk_invite_payload(5)
        payload[4]["target_email"] = None

        with self.settings(
            EMAIL_ENABLED=True,
            EMAIL_HOST="localhost",
            SITE_URL="http://test.posthog.com",
        ):
            response = self.client.post("/api/organizations/@current/invites/bulk/", payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        # No invites created
        self.assertEqual(OrganizationInvite.objects.count(), count)

        # No emails should be sent
        self.assertEqual(len(mail.outbox), 0)

    def test_cannot_bulk_create_invites_for_another_organization(self):
        another_org = Organization.objects.create()

        count = OrganizationInvite.objects.count()
        payload = self.helper_generate_bulk_invite_payload(3)

        with self.settings(
            EMAIL_ENABLED=True,
            EMAIL_HOST="localhost",
            SITE_URL="http://test.posthog.com",
        ):
            response = self.client.post(
                f"/api/organizations/{another_org.id}/invites/bulk/",
                payload,
                format="json",
            )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.json(), self.permission_denied_response())

        # No invites created
        self.assertEqual(OrganizationInvite.objects.count(), count)

        # No emails should be sent
        self.assertEqual(len(mail.outbox), 0)

    # Deleting invites

    def test_delete_organization_invite_if_plain_member(self):
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        invite = OrganizationInvite.objects.create(organization=self.organization)
        response = self.client.delete(f"/api/organizations/@current/invites/{invite.id}")
        self.assertEqual(response.content, b"")  # Empty response
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(OrganizationInvite.objects.exists())

    # Combine pending invites

    def test_combine_pending_invites_combines_levels_and_project_access(self):
        admin_user = self._create_user("admin@posthog.com", level=OrganizationMembership.Level.ADMIN)
        self.client.force_login(admin_user)

        email = "x@posthog.com"
        private_team_1 = Team.objects.create(organization=self.organization, name="Private Team 1", access_control=True)
        private_team_2 = Team.objects.create(organization=self.organization, name="Private Team 2", access_control=True)

        ExplicitTeamMembership.objects.create(
            team=private_team_1,
            parent_membership=self.organization_membership,
            level=ExplicitTeamMembership.Level.ADMIN,
        )
        ExplicitTeamMembership.objects.create(
            team=private_team_2,
            parent_membership=self.organization_membership,
            level=ExplicitTeamMembership.Level.ADMIN,
        )

        # Create first invite with member access to team 1
        first_invite = self.client.post(
            "/api/organizations/@current/invites/",
            {
                "target_email": email,
                "level": OrganizationMembership.Level.MEMBER,
                "private_project_access": [{"id": private_team_1.id, "level": ExplicitTeamMembership.Level.MEMBER}],
            },
        ).json()

        # Create second invite with admin access to team 2
        second_invite = self.client.post(
            "/api/organizations/@current/invites/",
            {
                "target_email": email,
                "level": OrganizationMembership.Level.ADMIN,
                "private_project_access": [{"id": private_team_2.id, "level": ExplicitTeamMembership.Level.ADMIN}],
            },
        ).json()

        # Create third invite combining previous invites
        response = self.client.post(
            "/api/organizations/@current/invites/",
            {
                "target_email": email,
                "level": OrganizationMembership.Level.MEMBER,
                "private_project_access": [{"id": private_team_1.id, "level": ExplicitTeamMembership.Level.ADMIN}],
                "combine_pending_invites": True,
            },
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        combined_invite = response.json()

        # Check that previous invites are deleted
        self.assertFalse(OrganizationInvite.objects.filter(id=first_invite["id"]).exists())
        self.assertFalse(OrganizationInvite.objects.filter(id=second_invite["id"]).exists())

        # Check that the new invite has the highest level (ADMIN)
        self.assertEqual(combined_invite["level"], OrganizationMembership.Level.ADMIN)

        # Check that private project access is combined with highest levels
        expected_access = [
            {"id": private_team_1.id, "level": ExplicitTeamMembership.Level.ADMIN},
            {"id": private_team_2.id, "level": ExplicitTeamMembership.Level.ADMIN},
        ]
        self.assertEqual(len(combined_invite["private_project_access"]), 2)
        for access in expected_access:
            self.assertIn(access, combined_invite["private_project_access"])

    def test_combine_pending_invites_with_no_existing_invites(self):
        email = "x@posthog.com"
        response = self.client.post(
            "/api/organizations/@current/invites/",
            {
                "target_email": email,
                "level": OrganizationMembership.Level.MEMBER,
                "combine_pending_invites": True,
            },
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        invite = response.json()
        self.assertEqual(invite["level"], OrganizationMembership.Level.MEMBER)
        self.assertEqual(invite["target_email"], email)
        self.assertEqual(invite["private_project_access"], [])

    @freeze_time("2024-01-10")
    def test_combine_pending_invites_with_expired_invites(self):
        email = "xyz@posthog.com"

        # Create an expired invite
        with freeze_time("2023-01-05"):
            OrganizationInvite.objects.create(
                organization=self.organization,
                target_email=email,
                level=OrganizationMembership.Level.ADMIN,
            )

        response = self.client.post(
            "/api/organizations/@current/invites/",
            {
                "target_email": email,
                "level": OrganizationMembership.Level.MEMBER,
                "combine_pending_invites": True,
            },
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        invite = response.json()

        # Check that the new invite uses its own level, not the expired invite's level
        self.assertEqual(invite["level"], OrganizationMembership.Level.MEMBER)
        self.assertEqual(invite["target_email"], email)
        self.assertEqual(invite["private_project_access"], [])

    def test_combine_pending_invites_false_expires_existing_invites(self):
        admin_user = self._create_user("admin@posthog.com", level=OrganizationMembership.Level.ADMIN)
        self.client.force_login(admin_user)

        email = "x@posthog.com"

        # Create first invite
        first_invite = self.client.post(
            "/api/organizations/@current/invites/",
            {
                "target_email": email,
                "level": OrganizationMembership.Level.ADMIN,
            },
        ).json()

        # Create second invite with combine_pending_invites=False
        response = self.client.post(
            "/api/organizations/@current/invites/",
            {
                "target_email": email,
                "level": OrganizationMembership.Level.MEMBER,
                "combine_pending_invites": False,
            },
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        new_invite = response.json()

        # Check that previous invite is deleted
        self.assertFalse(OrganizationInvite.objects.filter(id=first_invite["id"]).exists())

        # Check that new invite uses its own level
        self.assertEqual(new_invite["level"], OrganizationMembership.Level.MEMBER)

    def test_member_cannot_invite_admin(self):
        # Create a member user
        member_user = self._create_user("member@posthog.com")

        # Login as the member
        self.client.force_login(member_user)

        # Try to invite an admin as an member
        response = self.client.post(
            f"/api/organizations/{self.organization.id}/invites/",
            {
                "target_email": "new_admin@posthog.com",
                "level": OrganizationMembership.Level.ADMIN,
            },
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(
            response.json()["detail"],
            "You cannot invite a user with a higher permission level than your own.",
        )

        self.assertEqual(OrganizationInvite.objects.filter(target_email="new_admin@posthog.com").count(), 0)

    def test_admin_cannot_invite_owner(self):
        # Create an admin user
        admin_user = self._create_user("admin@posthog.com", level=OrganizationMembership.Level.ADMIN)

        # Login as the admin
        self.client.force_login(admin_user)

        # Try to invite an owner as an admin
        response = self.client.post(
            f"/api/organizations/{self.organization.id}/invites/",
            {
                "target_email": "new_owner@posthog.com",
                "level": OrganizationMembership.Level.OWNER,
            },
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(
            response.json()["detail"],
            "You cannot invite a user with a higher permission level than your own.",
        )

        # Verify no invite was created
        self.assertEqual(OrganizationInvite.objects.filter(target_email="new_owner@posthog.com").count(), 0)

    def test_member_can_invite_member(self):
        # Create a member user
        member_user = self._create_user("member@posthog.com")

        # Login as the member
        self.client.force_login(member_user)

        # Try to invite a member as a member (same level)
        response = self.client.post(
            f"/api/organizations/{self.organization.id}/invites/",
            {
                "target_email": "new_member@posthog.com",
                "level": OrganizationMembership.Level.MEMBER,
            },
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # Verify invite was created
        self.assertEqual(OrganizationInvite.objects.filter(target_email="new_member@posthog.com").count(), 1)
        invite = OrganizationInvite.objects.get(target_email="new_member@posthog.com")
        self.assertEqual(invite.level, OrganizationMembership.Level.MEMBER)

    def test_admin_can_invite_admin(self):
        # Create an admin user
        admin_user = self._create_user("admin@posthog.com", level=OrganizationMembership.Level.ADMIN)

        # Login as the admin
        self.client.force_login(admin_user)

        # Try to invite an admin as an admin (same level)
        response = self.client.post(
            f"/api/organizations/{self.organization.id}/invites/",
            {
                "target_email": "new_admin@posthog.com",
                "level": OrganizationMembership.Level.ADMIN,
            },
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # Verify invite was created
        self.assertEqual(OrganizationInvite.objects.filter(target_email="new_admin@posthog.com").count(), 1)
        invite = OrganizationInvite.objects.get(target_email="new_admin@posthog.com")
        self.assertEqual(invite.level, OrganizationMembership.Level.ADMIN)

    def test_bulk_invite_with_higher_permission_level(self):
        # Create a member user
        member_user = self._create_user("member@posthog.com")

        # Login as the member
        self.client.force_login(member_user)

        # Try to bulk invite users with mixed permission levels
        payload = [
            {
                "target_email": "new_member@posthog.com",
                "level": OrganizationMembership.Level.MEMBER,
            },
            {
                "target_email": "new_admin@posthog.com",
                "level": OrganizationMembership.Level.ADMIN,
            },
            {
                "target_email": "another_member@posthog.com",
                "level": OrganizationMembership.Level.MEMBER,
            },
        ]

        response = self.client.post(f"/api/organizations/{self.organization.id}/invites/bulk/", payload)

        # Should be forbidden due to the admin invite
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(
            response.json()["detail"],
            "You cannot invite a user with a higher permission level than your own.",
        )

        # Verify no invites were created
        self.assertEqual(
            OrganizationInvite.objects.filter(
                target_email__in=["new_member@posthog.com", "new_admin@posthog.com", "another_member@posthog.com"]
            ).count(),
            0,
        )

    def test_bulk_invite_with_same_permission_level(self):
        # Create a member user
        member_user = self._create_user("member@posthog.com")

        # Login as the member
        self.client.force_login(member_user)

        # Try to bulk invite users with same permission level
        payload = [
            {
                "target_email": "new_member1@posthog.com",
                "level": OrganizationMembership.Level.MEMBER,
            },
            {
                "target_email": "new_member2@posthog.com",
                "level": OrganizationMembership.Level.MEMBER,
            },
        ]

        response = self.client.post(f"/api/organizations/{self.organization.id}/invites/bulk/", payload)

        # Should be successful
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # Verify invites were created
        self.assertEqual(
            OrganizationInvite.objects.filter(
                target_email__in=["new_member1@posthog.com", "new_member2@posthog.com"]
            ).count(),
            2,
        )

    def test_member_cannot_invite_when_members_can_invite_false_and_feature_available(self):
        """Test that members cannot invite when members_can_invite is False and ORGANIZATION_INVITE_SETTINGS is available."""
        # Create a member user
        member_user = self._create_user("member@posthog.com")
        self.client.force_login(member_user)

        # Enable ORGANIZATION_INVITE_SETTINGS feature and set members_can_invite to False
        self.organization.available_product_features = [{"key": AvailableFeature.ORGANIZATION_INVITE_SETTINGS}]
        self.organization.members_can_invite = False
        self.organization.save()

        # Try to create a single invite
        response = self.client.post(
            f"/api/organizations/{self.organization.id}/invites/",
            {
                "target_email": "test@posthog.com",
                "level": OrganizationMembership.Level.MEMBER,
            },
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        # Try to create bulk invites
        response = self.client.post(
            f"/api/organizations/{self.organization.id}/invites/bulk/",
            [
                {
                    "target_email": "test1@posthog.com",
                    "level": OrganizationMembership.Level.MEMBER,
                }
            ],
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_member_can_invite_when_members_can_invite_true_and_feature_available(self):
        """Test that members can invite when members_can_invite is True and ORGANIZATION_INVITE_SETTINGS is available."""
        # Create a member user
        member_user = self._create_user("member@posthog.com")
        self.client.force_login(member_user)

        # Enable ORGANIZATION_INVITE_SETTINGS feature and set members_can_invite to True
        self.organization.available_product_features = [{"key": AvailableFeature.ORGANIZATION_INVITE_SETTINGS}]
        self.organization.members_can_invite = True
        self.organization.save()

        # Try to create a single invite
        response = self.client.post(
            f"/api/organizations/{self.organization.id}/invites/",
            {
                "target_email": "test@posthog.com",
                "level": OrganizationMembership.Level.MEMBER,
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # Try to create bulk invites
        response = self.client.post(
            f"/api/organizations/{self.organization.id}/invites/bulk/",
            [
                {
                    "target_email": "test1@posthog.com",
                    "level": OrganizationMembership.Level.MEMBER,
                }
            ],
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_admin_can_always_invite_regardless_of_members_can_invite(self):
        """Test that admins can always invite regardless of members_can_invite setting."""
        # Create an admin user
        admin_user = self._create_user("admin@posthog.com", level=OrganizationMembership.Level.ADMIN)
        self.client.force_login(admin_user)

        # Enable ORGANIZATION_INVITE_SETTINGS feature and set members_can_invite to False
        self.organization.available_product_features = [{"key": AvailableFeature.ORGANIZATION_INVITE_SETTINGS}]
        self.organization.members_can_invite = False
        self.organization.save()

        # Try to create a single invite
        response = self.client.post(
            f"/api/organizations/{self.organization.id}/invites/",
            {
                "target_email": "test@posthog.com",
                "level": OrganizationMembership.Level.MEMBER,
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # Try to create bulk invites
        response = self.client.post(
            f"/api/organizations/{self.organization.id}/invites/bulk/",
            [
                {
                    "target_email": "test1@posthog.com",
                    "level": OrganizationMembership.Level.MEMBER,
                }
            ],
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_member_can_invite_when_feature_not_available(self):
        """Test that members can invite when ORGANIZATION_INVITE_SETTINGS feature is not available."""
        # Create a member user
        member_user = self._create_user("member@posthog.com")
        self.client.force_login(member_user)

        # Ensure ORGANIZATION_INVITE_SETTINGS feature is not available
        self.organization.available_product_features = []
        self.organization.members_can_invite = False  # This should be ignored since feature is not available
        self.organization.save()

        # Try to create a single invite
        response = self.client.post(
            f"/api/organizations/{self.organization.id}/invites/",
            {
                "target_email": "test@posthog.com",
                "level": OrganizationMembership.Level.MEMBER,
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # Try to create bulk invites
        response = self.client.post(
            f"/api/organizations/{self.organization.id}/invites/bulk/",
            [
                {
                    "target_email": "test1@posthog.com",
                    "level": OrganizationMembership.Level.MEMBER,
                }
            ],
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_can_invite_with_new_access_control_as_org_admin(self):
        """
        Test that organization admins can invite users to teams with the new access control system
        """
        # Create a team with access_control=False (using new access control system)
        team = Team.objects.create(organization=self.organization, name="New Team", access_control=False)

        # Import AccessControl

        # Create an admin user
        admin_user = self._create_user("admin@posthog.com", level=OrganizationMembership.Level.ADMIN)
        OrganizationMembership.objects.get(organization=self.organization, user=admin_user)

        # Login as the admin
        self.client.force_login(admin_user)

        # Try to invite a user to the team
        response = self.client.post(
            f"/api/organizations/{self.organization.id}/invites/",
            {
                "target_email": "test@posthog.com",
                "private_project_access": [{"id": team.id, "level": OrganizationMembership.Level.MEMBER}],
            },
        )

        # Should be successful
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # Verify the invite was created with the correct private project access
        invite = OrganizationInvite.objects.get(target_email="test@posthog.com")
        self.assertEqual(len(invite.private_project_access), 1)
        self.assertEqual(invite.private_project_access[0]["id"], team.id)
        self.assertEqual(invite.private_project_access[0]["level"], OrganizationMembership.Level.MEMBER)

    def test_can_invite_with_new_access_control_as_org_member_to_non_private_team(self):
        """
        Test that organization members can invite users to non-private teams with the new access control system
        """
        # Create a team with access_control=False (using new access control system)
        team = Team.objects.create(organization=self.organization, name="New Team", access_control=False)

        # Import AccessControl

        # Create a member user
        member_user = self._create_user("member@posthog.com", level=OrganizationMembership.Level.MEMBER)
        OrganizationMembership.objects.get(organization=self.organization, user=member_user)

        # Login as the member
        self.client.force_login(member_user)

        # Try to invite a user to the team
        response = self.client.post(
            f"/api/organizations/{self.organization.id}/invites/",
            {
                "target_email": "test@posthog.com",
                "private_project_access": [{"id": team.id, "level": OrganizationMembership.Level.MEMBER}],
            },
        )

        # Should be successful since the team is not private
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # Verify the invite was created with the correct private project access
        invite = OrganizationInvite.objects.get(target_email="test@posthog.com")
        self.assertEqual(len(invite.private_project_access), 1)
        self.assertEqual(invite.private_project_access[0]["id"], team.id)
        self.assertEqual(invite.private_project_access[0]["level"], OrganizationMembership.Level.MEMBER)

    def test_cannot_invite_with_new_access_control_as_org_member_to_private_team(self):
        """
        Test that organization members cannot invite users to private teams with the new access control system
        """
        # Create a team with access_control=False (using new access control system)
        team = Team.objects.create(organization=self.organization, name="New Team", access_control=False)

        # Import AccessControl
        from ee.models.rbac.access_control import AccessControl

        # Create a member user
        member_user = self._create_user("member@posthog.com", level=OrganizationMembership.Level.MEMBER)
        OrganizationMembership.objects.get(organization=self.organization, user=member_user)

        # Login as the member
        self.client.force_login(member_user)

        # Make the team private by creating an access control with level 'none'
        AccessControl.objects.create(team=team, resource="team", resource_id=str(team.id), access_level="none")

        # Try to invite a user to the private team
        response = self.client.post(
            f"/api/organizations/{self.organization.id}/invites/",
            {
                "target_email": "test@posthog.com",
                "private_project_access": [{"id": team.id, "level": OrganizationMembership.Level.MEMBER}],
            },
        )

        # Should fail because the team is private and the user doesn't have access
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn(
            "Project does not exist on this organization, or it is private and you do not have access to it",
            response.json()["detail"],
        )

    def test_can_invite_with_new_access_control_as_team_admin(self):
        """
        Test that team admins can invite users to private teams with the new access control system
        """
        # Create a team with access_control=False (using new access control system)
        team = Team.objects.create(organization=self.organization, name="New Team", access_control=False)

        # Import AccessControl
        from ee.models.rbac.access_control import AccessControl

        # Create a member user
        member_user = self._create_user("member@posthog.com", level=OrganizationMembership.Level.MEMBER)
        member_membership = OrganizationMembership.objects.get(organization=self.organization, user=member_user)

        # Login as the member
        self.client.force_login(member_user)

        # Make the team private by creating an access control with level 'none'
        AccessControl.objects.create(team=team, resource="team", resource_id=str(team.id), access_level="none")

        # Give the member admin access to the team
        AccessControl.objects.create(
            team=team,
            resource="team",
            resource_id=str(team.id),
            organization_member=member_membership,
            access_level="admin",
        )

        # Try to invite a user to the private team
        response = self.client.post(
            f"/api/organizations/{self.organization.id}/invites/",
            {
                "target_email": "test@posthog.com",
                "private_project_access": [{"id": team.id, "level": OrganizationMembership.Level.MEMBER}],
            },
        )

        # Should be successful because the user has admin access to the team
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # Verify the invite was created with the correct private project access
        invite = OrganizationInvite.objects.get(target_email="test@posthog.com")
        self.assertEqual(len(invite.private_project_access), 1)
        self.assertEqual(invite.private_project_access[0]["id"], team.id)
        self.assertEqual(invite.private_project_access[0]["level"], OrganizationMembership.Level.MEMBER)
