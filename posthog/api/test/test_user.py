import datetime
import uuid
from typing import cast
from unittest import mock
from unittest.mock import ANY, Mock, patch
from urllib.parse import quote

from django.contrib.auth.tokens import default_token_generator
from django.core import mail
from django.core.cache import cache
from django.utils import timezone
from django.utils.text import slugify
from freezegun.api import freeze_time
from rest_framework import status

from posthog.api.email_verification import email_verification_token_generator
from posthog.models import Dashboard, Team, User
from posthog.models.instance_setting import set_instance_setting
from posthog.models.organization import Organization, OrganizationMembership
from posthog.test.base import APIBaseTest


def create_user(email: str, password: str, organization: Organization):
    """
    Helper that just creates a user. It currently uses the orm, but we
    could use either the api, or django admin to create, to get better parity
    with real world scenarios.
    """
    return User.objects.create_and_join(organization, email, password)


class TestUserAPI(APIBaseTest):
    new_org: Organization = None  # type: ignore
    new_project: Team = None  # type: ignore
    CONFIG_PASSWORD = "testpassword12345"

    def _assert_current_org_and_team_unchanged(self):
        self.user.refresh_from_db()
        self.assertEqual(self.user.current_team, self.team)
        self.assertEqual(self.user.current_organization, self.organization)

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.new_org = Organization.objects.create(name="New Organization")
        cls.new_project = Team.objects.create(name="New Project", organization=cls.new_org)
        cls.user.join(organization=cls.new_org)
        cls.user.current_organization = cls.organization
        cls.user.current_team = cls.team
        cls.user.save()

    def setUp(self):
        # prevent throttling of user requests to pass on from one test
        # to the next
        cache.clear()
        return super().setUp()

    # RETRIEVING USER

    def test_retrieve_current_user(self):
        response = self.client.get("/api/users/@me/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data = response.json()

        self.assertEqual(response_data["uuid"], str(self.user.uuid))
        self.assertEqual(response_data["distinct_id"], self.user.distinct_id)
        self.assertEqual(response_data["first_name"], self.user.first_name)
        self.assertEqual(response_data["email"], self.user.email)
        self.assertEqual(response_data["has_password"], True)
        self.assertEqual(response_data["is_staff"], False)
        self.assertNotIn("password", response_data)
        self.assertNotIn("current_password", response_data)
        self.assertNotIn("set_current_team", response_data)
        self.assertEqual(response_data["team"]["id"], self.team.id)
        self.assertEqual(response_data["team"]["name"], self.team.name)
        self.assertEqual(response_data["team"]["api_token"], "token123")
        self.assertNotIn("test_account_filters", response_data["team"])  # Ensure we're not returning the full `Team`
        self.assertNotIn("event_names", response_data["team"])

        self.assertEqual(response_data["organization"]["name"], self.organization.name)
        self.assertEqual(response_data["organization"]["membership_level"], 1)
        self.assertEqual(response_data["organization"]["teams"][0]["id"], self.team.id)
        self.assertEqual(response_data["organization"]["teams"][0]["name"], self.team.name)
        self.assertNotIn(
            "test_account_filters", response_data["organization"]["teams"][0]
        )  # Ensure we're not returning the full `Team`
        self.assertNotIn("event_names", response_data["organization"]["teams"][0])

        self.assertCountEqual(
            response_data["organizations"],
            [
                {
                    "id": str(self.organization.id),
                    "name": self.organization.name,
                    "slug": slugify(self.organization.name),
                    "logo_media_id": None,
                    "membership_level": 1,
                },
                {
                    "id": str(self.new_org.id),
                    "name": "New Organization",
                    "slug": "new-organization",
                    "logo_media_id": None,
                    "membership_level": 1,
                },
            ],
        )

    def test_hedgehog_config_is_unset(self):
        self.user.hedgehog_config = None
        self.user.save()

        response = self.client.get(f"/api/users/@me/hedgehog_config/")
        assert response.status_code == status.HTTP_200_OK
        # the front end assumes it will _always_ get JSON
        assert response.json() == {}

    def test_hedgehog_config_is_set(self):
        self.user.hedgehog_config = {"a bag": "of data"}
        self.user.save()

        response = self.client.get(f"/api/users/@me/hedgehog_config/")
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {"a bag": "of data"}

    def test_can_only_list_yourself(self):
        """
        At this moment only the current user can be retrieved from this endpoint.
        """
        response = self.client.get("/api/users/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 1)
        self.assertEqual(response.json()["results"][0]["uuid"], str(self.user.uuid))

        user = self._create_user("newtest@posthog.com")
        response = self.client.get(f"/api/users/{user.uuid}")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(
            response.json(),
            {
                "type": "authentication_error",
                "code": "permission_denied",
                "detail": "As a non-staff user you're only allowed to access the `@me` user instance.",
                "attr": None,
            },
        )

    def test_unauthenticated_user_cannot_fetch_endpoint(self):
        self.client.logout()
        response = self.client.get("/api/users/@me/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(response.json(), self.unauthenticated_response())

    # CREATING USERS

    def test_creating_users_on_this_endpoint_is_not_supported(self):
        """
        At this moment we don't support creating users on this endpoint. Refer to /api/signup or
        /api/organization/@current/members to add users.
        """
        count = User.objects.count()

        response = self.client.post("/api/users/", {"first_name": "James", "email": "test+james@posthog.com"})
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
        self.assertEqual(response.json(), self.method_not_allowed_response("POST"))

        self.assertEqual(User.objects.count(), count)

    # UPDATING USER

    @patch("posthog.tasks.user_identify.identify_task")
    @patch("posthoganalytics.capture")
    def test_update_current_user(self, mock_capture, mock_identify_task):
        another_org = Organization.objects.create(name="Another Org")
        another_team = Team.objects.create(name="Another Team", organization=another_org)
        user = self._create_user("old@posthog.com", password="12345678")
        self.client.force_login(user)
        response = self.client.patch(
            "/api/users/@me/",
            {
                "first_name": "Cooper",
                "anonymize_data": True,
                "events_column_config": {"active": ["column_1", "column_2"]},
                "notification_settings": {"plugin_disabled": False},
                "has_seen_product_intro_for": {"feature_flags": True},
                "uuid": 1,  # should be ignored
                "id": 1,  # should be ignored
                "organization": str(another_org.id),  # should be ignored
                "team": str(another_team.id),  # should be ignored
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data = response.json()

        self.assertNotEqual(response_data["uuid"], 1)
        self.assertEqual(response_data["first_name"], "Cooper")
        self.assertEqual(response_data["anonymize_data"], True)
        self.assertEqual(response_data["events_column_config"], {"active": ["column_1", "column_2"]})
        self.assertEqual(response_data["organization"]["id"], str(self.organization.id))
        self.assertEqual(response_data["team"]["id"], self.team.id)
        self.assertEqual(response_data["has_seen_product_intro_for"], {"feature_flags": True})

        user.refresh_from_db()
        self.assertNotEqual(user.pk, 1)
        self.assertNotEqual(user.uuid, 1)
        self.assertEqual(user.first_name, "Cooper")
        self.assertEqual(user.anonymize_data, True)
        self.assertDictContainsSubset({"plugin_disabled": False}, user.notification_settings)
        self.assertEqual(user.has_seen_product_intro_for, {"feature_flags": True})

        mock_capture.assert_called_once_with(
            user.distinct_id,
            "user updated",
            properties={
                "updated_attrs": [
                    "anonymize_data",
                    "events_column_config",
                    "first_name",
                    "has_seen_product_intro_for",
                    "partial_notification_settings",
                ],
                "$set": mock.ANY,
            },
            groups={
                "instance": ANY,
                "organization": str(self.team.organization_id),
                "project": str(self.team.uuid),
            },
        )

    @patch("posthog.tasks.user_identify.identify_task")
    @patch("posthoganalytics.capture")
    def test_set_scene_personalisation_for_user_dashboard_must_be_in_current_team(
        self, _mock_capture, _mock_identify_task
    ):
        a_third_team = Team.objects.create(name="A Third Team", organization=self.organization)

        dashboard_one = Dashboard.objects.create(team=a_third_team, name="Dashboard 1")

        response = self.client.post(
            "/api/users/@me/scene_personalisation",
            # even if someone tries to send a different user or team they are ignored
            {
                "user": 12345,
                "team": 12345,
                "dashboard": str(dashboard_one.id),
                "scene": "Person",
            },
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @patch("posthog.tasks.user_identify.identify_task")
    @patch("posthoganalytics.capture")
    def test_set_scene_personalisation_for_user_dashboard_must_exist(self, _mock_capture, _mock_identify_task):
        response = self.client.post(
            "/api/users/@me/scene_personalisation",
            # even if someone tries to send a different user or team they are ignored
            {"user": 12345, "team": 12345, "dashboard": 12345, "scene": "Person"},
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @patch("posthog.tasks.user_identify.identify_task")
    @patch("posthoganalytics.capture")
    def test_set_scene_personalisation_for_user_must_send_dashboard(self, _mock_capture, _mock_identify_task):
        response = self.client.post(
            "/api/users/@me/scene_personalisation",
            # even if someone tries to send a different user or team they are ignored
            {"user": 12345, "team": 12345, "scene": "Person"},
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @patch("posthog.tasks.user_identify.identify_task")
    @patch("posthoganalytics.capture")
    def test_set_scene_personalisation_for_user_must_send_scene(self, _mock_capture, _mock_identify_task):
        dashboard_one = Dashboard.objects.create(team=self.team, name="Dashboard 1")

        response = self.client.post(
            "/api/users/@me/scene_personalisation",
            # even if someone tries to send a different user or team they are ignored
            {
                "user": 12345,
                "team": 12345,
                "dashboard": str(dashboard_one.id),
            },
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @patch("posthog.tasks.user_identify.identify_task")
    @patch("posthoganalytics.capture")
    def test_set_scene_personalisation_for_user(self, _mock_capture, _mock_identify_task):
        another_org = Organization.objects.create(name="Another Org")
        another_team = Team.objects.create(name="Another Team", organization=another_org)
        user = self._create_user("the-user@posthog.com", password="12345678")
        user.current_team = another_team
        user.save()
        self.client.force_login(user)

        dashboard_one = Dashboard.objects.create(team=another_team, name="Dashboard 1")
        dashboard_two = Dashboard.objects.create(team=another_team, name="Dashboard 2")

        self._assert_set_scene_choice(
            "Person",
            dashboard_one,
            user,
            [
                {
                    "dashboard": dashboard_one.pk,
                    "scene": "Person",
                },
            ],
        )

        self._assert_set_scene_choice(
            "Person",
            dashboard_two,
            user,
            [
                {
                    "dashboard": dashboard_two.pk,
                    "scene": "Person",
                },
            ],
        )

        self._assert_set_scene_choice(
            "Group",
            dashboard_two,
            user,
            [
                {
                    "dashboard": dashboard_two.pk,
                    "scene": "Person",
                },
                {
                    "dashboard": dashboard_two.pk,
                    "scene": "Group",
                },
            ],
        )

    def _assert_set_scene_choice(
        self, scene: str, dashboard: Dashboard, user: User, expected_choices: list[dict]
    ) -> None:
        response = self.client.post(
            "/api/users/@me/scene_personalisation",
            # even if someone tries to send a different user or team they are ignored
            {
                "user": 12345,
                "team": 12345,
                "dashboard": str(dashboard.id),
                "scene": scene,
            },
        )
        assert response.status_code == status.HTTP_200_OK
        response_data = response.json()
        assert response_data["uuid"] == str(user.uuid)
        assert response_data["scene_personalisation"] == expected_choices

    @patch("posthog.api.user.is_email_available", return_value=False)
    @patch("posthog.tasks.email.send_email_change_emails.delay")
    def test_no_notifications_when_user_email_is_changed_and_email_not_available(
        self, mock_send_email_change_emails, mock_is_email_available
    ):
        self.user.email = "alpha@example.com"
        self.user.save()

        response = self.client.patch(
            "/api/users/@me/",
            {
                "email": "beta@example.com",
            },
        )
        response_data = response.json()
        self.user.refresh_from_db()

        assert response.status_code == status.HTTP_200_OK
        assert response_data["email"] == "beta@example.com"
        assert self.user.email == "beta@example.com"
        mock_is_email_available.assert_called_once()
        mock_send_email_change_emails.assert_not_called()

    @patch("posthog.api.user.is_email_available", return_value=True)
    @patch("posthog.tasks.email.send_email_change_emails.delay")
    @patch("posthog.api.email_verification.send_email_verification")
    def test_notifications_sent_when_user_email_is_changed_and_email_available(
        self,
        mock_send_email_verification,
        mock_send_email_change_emails,
        mock_is_email_available,
    ):
        """Test that when a user updates their email, they receive a verification email before the switch actually happens."""
        self.user.email = "alpha@example.com"
        self.user.save()
        with self.is_cloud(True):
            with freeze_time("2020-01-01T21:37:00+00:00"):
                response = self.client.patch(
                    "/api/users/@me/",
                    {
                        "email": "beta@example.com",
                    },
                )
            response_data = response.json()
            self.user.refresh_from_db()

            assert response.status_code == status.HTTP_200_OK
            assert response_data["email"] == "alpha@example.com"
            assert response_data["pending_email"] == "beta@example.com"
            assert self.user.email == "alpha@example.com"
            assert self.user.pending_email == "beta@example.com"

            mock_is_email_available.assert_called_once()
            mock_send_email_verification.assert_called_once()

            token = email_verification_token_generator.make_token(self.user)
            with freeze_time("2020-01-01T21:37:00+00:00"):
                response = self.client.post(
                    f"/api/users/@me/verify_email/",
                    {"uuid": self.user.uuid, "token": token},
                )
            self.assertEqual(response.status_code, status.HTTP_200_OK)

            self.user.refresh_from_db()
            assert self.user.email == "beta@example.com"
            self.assertIsNone(self.user.pending_email)
            mock_is_email_available.assert_called_once()
            mock_send_email_change_emails.assert_called_once_with(
                "2020-01-01T21:37:00+00:00",
                self.user.first_name,
                "alpha@example.com",
                "beta@example.com",
            )

    @patch("posthog.api.user.is_email_available", return_value=True)
    @patch("posthog.tasks.email.send_email_change_emails.delay")
    def test_no_notifications_when_user_email_is_changed_and_only_case_differs(
        self, mock_send_email_change_emails, mock_is_email_available
    ):
        self.user.email = "alpha@example.com"
        self.user.save()

        response = self.client.patch(
            "/api/users/@me/",
            {
                "email": "ALPHA@example.com",
            },
        )
        response_data = response.json()
        self.user.refresh_from_db()

        assert response.status_code == status.HTTP_200_OK
        assert response_data["email"] == "ALPHA@example.com"
        assert self.user.email == "ALPHA@example.com"
        mock_is_email_available.assert_not_called()
        mock_send_email_change_emails.assert_not_called()

    def test_cannot_upgrade_yourself_to_staff_user(self):
        response = self.client.patch("/api/users/@me/", {"is_staff": True})

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(
            response.json(),
            self.permission_denied_response("You are not a staff user, contact your instance admin."),
        )

        self.user.refresh_from_db()
        self.assertEqual(self.user.is_staff, False)

    @patch("posthog.tasks.user_identify.identify_task")
    @patch("posthoganalytics.capture")
    def test_can_update_current_organization(self, mock_capture, mock_identify):
        response = self.client.patch("/api/users/@me/", {"set_current_organization": str(self.new_org.id)})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data = response.json()
        self.assertEqual(response_data["organization"]["id"], str(self.new_org.id))
        self.assertEqual(response_data["organization"]["name"], self.new_org.name)

        # Team is set too
        self.assertEqual(response_data["team"]["id"], self.new_project.id)
        self.assertEqual(response_data["team"]["name"], self.new_project.name)

        self.user.refresh_from_db()
        self.assertEqual(self.user.current_organization, self.new_org)
        self.assertEqual(self.user.current_team, self.new_project)

        mock_capture.assert_called_once_with(
            self.user.distinct_id,
            "user updated",
            properties={"updated_attrs": ["current_organization", "current_team"], "$set": mock.ANY},
            groups={
                "instance": ANY,
                "organization": str(self.new_org.id),
                "project": str(self.new_project.uuid),
            },
        )

    @patch("posthog.tasks.user_identify.identify_task")
    @patch("posthoganalytics.capture")
    def test_can_update_current_project(self, mock_capture, mock_identify):
        team = Team.objects.create(name="Local Team", organization=self.new_org)
        response = self.client.patch("/api/users/@me/", {"set_current_team": team.id})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data = response.json()
        self.assertEqual(response_data["team"]["id"], team.id)
        self.assertEqual(response_data["team"]["name"], "Local Team")

        # Org is updated too
        self.assertEqual(response_data["organization"]["id"], str(self.new_org.id))

        self.user.refresh_from_db()
        self.assertEqual(self.user.current_organization, self.new_org)
        self.assertEqual(self.user.current_team, team)

        mock_capture.assert_called_once_with(
            self.user.distinct_id,
            "user updated",
            properties={"updated_attrs": ["current_organization", "current_team"], "$set": mock.ANY},
            groups={
                "instance": ANY,
                "organization": str(self.new_org.id),
                "project": str(team.uuid),
            },
        )

    def test_cannot_set_mismatching_org_and_team(self):
        org = Organization.objects.create(name="Isolated Org")
        first_team = Team.objects.create(name="Isolated Team", organization=org)
        team = Team.objects.create(name="Isolated Team 2", organization=org)
        self.user.join(organization=org)

        response = self.client.patch(
            "/api/users/@me/",
            {
                "set_current_team": team.id,
                "set_current_organization": self.organization.id,
            },
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json(),
            {
                "type": "validation_error",
                "code": "invalid_input",
                "detail": "Team must belong to the same organization in set_current_organization.",
                "attr": "set_current_team",
            },
        )

        self.user.refresh_from_db()
        self.assertEqual(self.user.current_team, first_team)
        self.assertEqual(self.user.current_organization, org)

    def test_cannot_set_an_organization_without_permissions(self):
        org = Organization.objects.create(name="Isolated Org")

        response = self.client.patch("/api/users/@me/", {"set_current_organization": org.id})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json(),
            {
                "type": "validation_error",
                "code": "does_not_exist",
                "detail": f"Object with id={org.id} does not exist.",
                "attr": "set_current_organization",
            },
        )

        self._assert_current_org_and_team_unchanged()

    def test_cannot_set_a_team_without_permissions(self):
        org = Organization.objects.create(name="Isolated Org")
        team = Team.objects.create(name="Isolated Team", organization=org)

        response = self.client.patch("/api/users/@me/", {"set_current_team": team.id})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json(),
            {
                "type": "validation_error",
                "code": "does_not_exist",
                "detail": f"Object with id={team.id} does not exist.",
                "attr": "set_current_team",
            },
        )

        self._assert_current_org_and_team_unchanged()

    def test_cannot_set_a_non_existent_org_or_team(self):
        response = self.client.patch("/api/users/@me/", {"set_current_team": 3983838})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json(),
            {
                "type": "validation_error",
                "code": "does_not_exist",
                "detail": f"Object with id=3983838 does not exist.",
                "attr": "set_current_team",
            },
        )

        _uuid = str(uuid.uuid4())
        response = self.client.patch("/api/users/@me/", {"set_current_organization": _uuid})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json(),
            {
                "type": "validation_error",
                "code": "does_not_exist",
                "detail": f"Object with id={_uuid} does not exist.",
                "attr": "set_current_organization",
            },
        )

        self._assert_current_org_and_team_unchanged()

    def test_current_team_prefer_current_organization(self):
        """
        If current_organization is set but current_team isn't (for example when a team is deleted), make sure we set the team in the current organization
        """
        org2 = Organization.objects.create(name="bla")
        OrganizationMembership.objects.create(organization=org2, user=self.user)
        team2 = Team.objects.create(organization=org2)

        # select current organization
        self.user.current_organization = org2
        self.user.current_team = None
        self.user.save()

        response = self.client.get("/api/users/@me/").json()
        self.assertEqual(response["team"]["id"], team2.pk)

    @patch("posthog.tasks.user_identify.identify_task")
    @patch("posthoganalytics.capture")
    def test_user_can_update_password(self, mock_capture, mock_identify):
        user = self._create_user("bob@posthog.com", password="A12345678")
        self.client.force_login(user)

        response = self.client.patch(
            "/api/users/@me/",
            {"current_password": "A12345678", "password": "a_new_password"},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data = response.json()
        self.assertEqual(response_data["email"], "bob@posthog.com")
        self.assertNotIn("password", response_data)
        self.assertNotIn("current_password", response_data)

        # Assert session is still valid
        get_response = self.client.get("/api/users/@me/")
        self.assertEqual(get_response.status_code, status.HTTP_200_OK)

        # Password was successfully changed
        user.refresh_from_db()
        self.assertTrue(user.check_password("a_new_password"))

        mock_capture.assert_called_once_with(
            user.distinct_id,
            "user updated",
            properties={"updated_attrs": ["password"], "$set": mock.ANY},
            groups={
                "instance": ANY,
                "organization": str(self.team.organization_id),
                "project": str(self.team.uuid),
            },
        )

        # User can log in with new password
        response = self.client.post("/api/login", {"email": "bob@posthog.com", "password": "a_new_password"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    @patch("posthog.tasks.user_identify.identify_task")
    @patch("posthoganalytics.capture")
    def test_user_with_no_password_set_can_set_password(self, mock_capture, mock_identify):
        user = self._create_user("no_password@posthog.com", password=None)
        self.client.force_login(user)

        response = self.client.patch(
            "/api/users/@me/",
            {"password": "a_new_password"},  # note we don't send current password
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data = response.json()
        self.assertEqual(response_data["email"], "no_password@posthog.com")
        self.assertNotIn("password", response_data)
        self.assertNotIn("current_password", response_data)

        # Assert session is still valid
        get_response = self.client.get("/api/users/@me/")
        self.assertEqual(get_response.status_code, status.HTTP_200_OK)

        # Password was successfully changed
        user.refresh_from_db()
        self.assertTrue(user.check_password("a_new_password"))

        mock_capture.assert_called_once_with(
            user.distinct_id,
            "user updated",
            properties={"updated_attrs": ["password"], "$set": mock.ANY},
            groups={
                "instance": ANY,
                "organization": str(self.team.organization_id),
                "project": str(self.team.uuid),
            },
        )

        # User can log in with new password
        response = self.client.post(
            "/api/login",
            {"email": "no_password@posthog.com", "password": "a_new_password"},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_user_with_unusable_password_set_can_set_password(self):
        user = self._create_user("no_password@posthog.com", password="123456789")
        user.set_unusable_password()
        user.save()
        self.client.force_login(user)

        response = self.client.patch("/api/users/@me/", {"password": "a_new_password"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Assert session is still valid
        get_response = self.client.get("/api/users/@me/")
        self.assertEqual(get_response.status_code, status.HTTP_200_OK)

        # Password was successfully changed
        user.refresh_from_db()
        self.assertTrue(user.check_password("a_new_password"))

    @patch("posthog.tasks.user_identify.identify_task")
    @patch("posthoganalytics.capture")
    def test_cannot_update_to_insecure_password(self, mock_capture, mock_identify):
        response = self.client.patch(
            "/api/users/@me/",
            {"current_password": self.CONFIG_PASSWORD, "password": "123"},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json(),
            {
                "type": "validation_error",
                "code": "invalid_input",
                "detail": "This password is too short. It must contain at least 8 characters.",
                "attr": "password",
            },
        )

        # Assert session is still valid
        get_response = self.client.get("/api/users/@me/")
        self.assertEqual(get_response.status_code, status.HTTP_200_OK)

        # Password was not changed
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(self.CONFIG_PASSWORD))
        mock_capture.assert_not_called()

    def test_user_cannot_update_password_without_current_password(self):
        response = self.client.patch("/api/users/@me/", {"password": "12345678"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json(),
            {
                "type": "validation_error",
                "code": "required",
                "detail": "This field is required when updating your password.",
                "attr": "current_password",
            },
        )

        # Password was not changed
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(self.CONFIG_PASSWORD))

    def test_user_cannot_update_password_with_incorrect_current_password(self):
        response = self.client.patch("/api/users/@me/", {"current_password": "wrong", "password": "12345678"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json(),
            {
                "type": "validation_error",
                "code": "incorrect_password",
                "detail": "Your current password is incorrect.",
                "attr": "current_password",
            },
        )

        # Password was not changed
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(self.CONFIG_PASSWORD))

    def test_unauthenticated_user_cannot_update_anything(self):
        self.client.logout()
        response = self.client.patch(
            "/api/users/@me/",
            {
                "id": str(self.user.uuid),
                "email": "new@posthog.com",
                "password": "hijacked",
                "current_password": self.CONFIG_PASSWORD,
            },
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(response.json(), self.unauthenticated_response())

        self.user.refresh_from_db()
        self.assertNotEqual(self.user.email, "new@posthog.com")
        self.assertFalse(self.user.check_password("hijacked"))

    def test_user_cannot_update_password_with_incorrect_current_password_and_ratelimit_to_prevent_attacks(self):
        for _ in range(7):
            response = self.client.patch("/api/users/@me/", {"current_password": "wrong", "password": "12345678"})
        self.assertEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
        self.assertDictContainsSubset(
            {"attr": None, "code": "throttled", "type": "throttled_error"},
            response.json(),
        )

        # Password was not changed
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(self.CONFIG_PASSWORD))

    def test_no_ratelimit_for_get_requests_for_users(self):
        for _ in range(6):
            response = self.client.get("/api/users/@me/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        for _ in range(4):
            # below rate limit, so shouldn't be throttled
            response = self.client.patch("/api/users/@me/", {"current_password": "wrong", "password": "12345678"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        for _ in range(2):
            response = self.client.get("/api/users/@me/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        for _ in range(2):
            # finally above rate limit, so should be throttled
            response = self.client.patch("/api/users/@me/", {"current_password": "wrong", "password": "12345678"})
        self.assertEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)

    # DELETING USER

    def test_deleting_current_user_is_not_supported(self):
        """
        Self-serve account deletion is currently not supported.
        """
        response = self.client.delete("/api/users/@me/")
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
        self.assertEqual(response.json(), self.method_not_allowed_response("DELETE"))

        self.user.refresh_from_db()

    @patch("posthog.api.user.secrets.token_urlsafe")
    def test_redirect_user_to_site_with_toolbar(self, patched_token):
        patched_token.return_value = "tokenvalue"

        self.team.app_urls = ["http://127.0.0.1:8000"]
        self.team.save()

        response = self.client.get(
            "/api/user/redirect_to_site/?userIntent=add-action&appUrl=http%3A%2F%2F127.0.0.1%3A8000"
        )
        self.assertEqual(response.status_code, status.HTTP_302_FOUND)
        locationHeader = response.headers.get("location", "not found")
        self.assertIn("%22jsURL%22%3A%20%22http%3A%2F%2Flocalhost%3A8234%22", locationHeader)
        self.maxDiff = None
        self.assertEqual(
            locationHeader,
            "http://127.0.0.1:8000#__posthog=%7B%22action%22%3A%20%22ph_authorize%22%2C%20%22token%22%3A%20%22token123%22%2C%20%22temporaryToken%22%3A%20%22tokenvalue%22%2C%20%22actionId%22%3A%20null%2C%20%22userIntent%22%3A%20%22add-action%22%2C%20%22toolbarVersion%22%3A%20%22toolbar%22%2C%20%22apiURL%22%3A%20%22http%3A%2F%2Ftestserver%22%2C%20%22dataAttributes%22%3A%20%5B%22data-attr%22%5D%2C%20%22jsURL%22%3A%20%22http%3A%2F%2Flocalhost%3A8234%22%7D",
        )

    @patch("posthog.api.user.secrets.token_urlsafe")
    def test_redirect_only_to_allowed_urls(self, patched_token):
        patched_token.return_value = "tokenvalue"

        self.team.app_urls = [
            "https://www.example.com",
            "https://*.otherexample.com",
            "https://anotherexample.com",
        ]
        self.team.save()

        def assert_allowed_url(url):
            response = self.client.get(f"/api/user/redirect_to_site/?appUrl={quote(url)}")
            location = cast(str | None, response.headers.get("location")) or ""
            self.assertEqual(response.status_code, status.HTTP_302_FOUND)
            self.assertTrue(f"{url}#__posthog=" in location)

        def assert_forbidden_url(url):
            response = self.client.get(f"/api/user/redirect_to_site/?appUrl={quote(url)}")
            self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
            self.assertEqual(response.headers.get("location"), None)

        # hostnames
        assert_allowed_url("https://www.example.com")
        assert_forbidden_url("https://www.notexample.com")
        assert_forbidden_url("https://www.anotherexample.com")

        # wildcard domains and folders
        assert_forbidden_url("https://subdomain.example.com")
        assert_allowed_url("https://subdomain.otherexample.com")
        assert_allowed_url("https://sub.subdomain.otherexample.com")

    def test_user_cannot_update_protected_fields(self):
        self.user.is_staff = False
        self.user.save()
        fields = {
            "date_joined": "2021-01-01T00:00:00Z",
            "uuid": str(uuid.uuid4()),
            "distinct_id": "distinct_id",
            "pending_email": "changed@example.com",
            "is_email_verified": True,
        }

        initial_user = self.client.get("/api/users/@me/").json()

        for field, value in fields.items():
            response = self.client.patch("/api/users/@me/", {field: value})
            assert (
                response.json()[field] == initial_user[field]
            ), f"Updating field '{field}' to '{value}' worked when it shouldn't! Was {initial_user[field]} and is now {response.json()[field]}"


class TestUserSlackWebhook(APIBaseTest):
    ENDPOINT: str = "/api/user/test_slack_webhook/"

    def send_request(self, payload):
        return self.client.post(self.ENDPOINT, payload)

    def test_slack_webhook_no_webhook(self):
        response = self.send_request({})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["error"], "no webhook URL")

    def test_slack_webhook_bad_url(self):
        response = self.send_request({"webhook": "blabla"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["error"], "invalid webhook URL")

    def test_slack_webhook_bad_url_full(self):
        response = self.send_request({"webhook": "http://localhost/bla"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["error"], "invalid webhook URL")


class TestLoginViews(APIBaseTest):
    def test_redirect_to_preflight_when_no_users(self):
        User.objects.all().delete()
        response = self.client.get("/", follow=True)
        self.assertRedirects(response, "/preflight")


class TestStaffUserAPI(APIBaseTest):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.user.is_staff = True
        cls.user.save()

    def test_can_list_staff_users(self):
        response = self.client.get("/api/users/?is_staff=true")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data = response.json()
        self.assertEqual(response_data["count"], 1)
        self.assertEqual(response_data["results"][0]["is_staff"], True)
        self.assertEqual(response_data["results"][0]["email"], self.CONFIG_EMAIL)

    def test_only_staff_can_list_other_users(self):
        self.user.is_staff = False
        self.user.save()

        response = self.client.get("/api/users")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 1)
        self.assertEqual(response.json()["results"][0]["uuid"], str(self.user.uuid))

    def test_update_staff_user(self):
        user = self._create_user("newuser@posthog.com", password="12345678")
        self.assertEqual(user.is_staff, False)

        # User becomes staff
        response = self.client.patch(f"/api/users/{user.uuid}/", {"is_staff": True})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data = response.json()
        self.assertEqual(response_data["is_staff"], True)
        user.refresh_from_db()
        self.assertEqual(user.is_staff, True)

        # User is no longer staff
        response = self.client.patch(f"/api/users/{user.uuid}/", {"is_staff": False})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data = response.json()
        self.assertEqual(response_data["is_staff"], False)
        user.refresh_from_db()
        self.assertEqual(user.is_staff, False)

    def test_only_staff_user_can_update_staff_prop(self):
        user = self._create_user("newuser@posthog.com", password="12345678")

        self.user.is_staff = False
        self.user.save()

        response = self.client.patch(f"/api/users/{user.uuid}/", {"is_staff": True})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(
            response.json(),
            {
                "type": "authentication_error",
                "code": "permission_denied",
                "detail": "As a non-staff user you're only allowed to access the `@me` user instance.",
                "attr": None,
            },
        )

        user.refresh_from_db()
        self.assertEqual(user.is_staff, False)

    @patch("posthog.api.user.TOTPDeviceForm")
    def test_add_2fa(self, patch_is_valid):
        patch_is_valid.return_value = Mock()
        self._create_user("newuser@posthog.com", password="12345678")
        response = self.client.get(f"/api/users/@me/start_2fa_setup/")
        response = self.client.post(f"/api/users/@me/validate_2fa/", {"token": 123456})
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)


class TestEmailVerificationAPI(APIBaseTest):
    CONFIG_AUTO_LOGIN = False

    def setUp(self):
        # prevent throttling of user requests to pass on from one test
        # to the next
        cache.clear()
        return super().setUp()

    # Email verification request

    @patch("posthoganalytics.capture")
    def test_user_can_request_verification_email(self, mock_capture):
        set_instance_setting("EMAIL_HOST", "localhost")
        with self.settings(CELERY_TASK_ALWAYS_EAGER=True, SITE_URL="https://my.posthog.net"):
            response = self.client.post(f"/api/users/@me/request_email_verification/", {"uuid": self.user.uuid})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.content.decode(), '{"success":true}')
        self.assertSetEqual({",".join(outmail.to) for outmail in mail.outbox}, {self.CONFIG_EMAIL})

        self.assertEqual(mail.outbox[0].subject, "Verify your email address")
        self.assertEqual(mail.outbox[0].body, "")  # no plain-text version support yet

        html_message = mail.outbox[0].alternatives[0][0]  # type: ignore
        self.validate_basic_html(
            html_message,
            "https://my.posthog.net",
            preheader="Please follow the link inside to verify your account.",
        )
        link_index = html_message.find("https://my.posthog.net/verify_email")
        reset_link = html_message[link_index : html_message.find('"', link_index)]
        token = reset_link.replace("https://my.posthog.net/verify_email/", "").replace(f"{self.user.uuid}/", "")

        response = self.client.post(f"/api/users/@me/verify_email/", {"uuid": self.user.uuid, "token": token})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # check is_email_verified is changed to True
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_email_verified)

        # assert events were captured
        mock_capture.assert_any_call(
            self.user.distinct_id,
            "user logged in",
            properties={"social_provider": ""},
            groups={
                "instance": ANY,
                "organization": str(self.team.organization_id),
                "project": str(self.team.uuid),
            },
        )
        mock_capture.assert_any_call(
            self.user.distinct_id,
            "user verified email",
            properties={"$set": ANY},
        )

        mock_capture.assert_any_call(
            self.user.distinct_id,
            "verification email sent",
            groups={
                "organization": str(self.team.organization_id),
            },
        )
        self.assertEqual(mock_capture.call_count, 3)

    def test_cant_verify_if_email_is_not_configured(self):
        with self.settings(CELERY_TASK_ALWAYS_EAGER=True):
            response = self.client.post(f"/api/users/@me/request_email_verification/", {"uuid": self.user.uuid})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json(),
            {
                "type": "validation_error",
                "code": "email_not_available",
                "detail": "Cannot verify email address because email is not configured for your instance. Please contact your administrator.",
                "attr": None,
            },
        )

    def test_cant_verify_more_than_six_times(self):
        set_instance_setting("EMAIL_HOST", "localhost")

        for i in range(7):
            with self.settings(CELERY_TASK_ALWAYS_EAGER=True, SITE_URL="https://my.posthog.net"):
                response = self.client.post(
                    f"/api/users/@me/request_email_verification/",
                    {"uuid": self.user.uuid},
                )
            if i < 6:
                self.assertEqual(response.status_code, status.HTTP_200_OK)
            else:
                # Fourth request should fail
                self.assertEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
                self.assertDictContainsSubset(
                    {"attr": None, "code": "throttled", "type": "throttled_error"},
                    response.json(),
                )

        # Three emails should be sent, fourth should not
        self.assertEqual(len(mail.outbox), 6)

    # Token validation

    def test_can_validate_email_verification_token(self):
        token = email_verification_token_generator.make_token(self.user)
        response = self.client.post(f"/api/users/@me/verify_email/", {"uuid": self.user.uuid, "token": token})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_cant_validate_email_verification_token_without_a_token(self):
        response = self.client.post(f"/api/users/@me/verify_email/", {"uuid": self.user.uuid})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json(),
            {
                "type": "validation_error",
                "code": "required",
                "detail": "This field is required.",
                "attr": "token",
            },
        )

    def test_invalid_verification_token_returns_error(self):
        valid_token = default_token_generator.make_token(self.user)

        with freeze_time(timezone.now() - datetime.timedelta(seconds=86_401)):
            # tokens expire after one day
            expired_token = default_token_generator.make_token(self.user)

        for token in [
            valid_token[:-1],
            "not_even_trying",
            self.user.uuid,
            expired_token,
        ]:
            response = self.client.post(
                f"/api/users/@me/verify_email/",
                {"uuid": self.user.uuid, "token": token},
            )
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
            self.assertEqual(
                response.json(),
                {
                    "type": "validation_error",
                    "code": "invalid_token",
                    "detail": "This verification token is invalid or has expired.",
                    "attr": "token",
                },
            )
