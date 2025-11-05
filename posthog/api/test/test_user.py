import uuid
import datetime
from datetime import timedelta
from typing import cast
from urllib.parse import quote, unquote

from freezegun.api import freeze_time
from posthog.test.base import APIBaseTest
from unittest import mock
from unittest.mock import ANY, patch

from django.conf import settings
from django.contrib.auth.tokens import default_token_generator
from django.core import mail
from django.core.cache import cache
from django.test import override_settings
from django.utils import timezone
from django.utils.text import slugify

from django_otp.plugins.otp_static.models import StaticDevice
from django_otp.plugins.otp_totp.models import TOTPDevice
from rest_framework import status

from posthog.api.email_verification import email_verification_token_generator
from posthog.api.test.test_oauth import generate_rsa_key
from posthog.models import Dashboard, Team, User, UserPinnedSceneTabs
from posthog.models.instance_setting import set_instance_setting
from posthog.models.oauth import OAuthAccessToken, OAuthApplication
from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.personal_api_key import PersonalAPIKey, hash_key_value
from posthog.models.utils import generate_random_token_personal


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
        self.assertEqual(response_data["role_at_organization"], self.user.role_at_organization)

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
                    "members_can_use_personal_api_keys": True,
                },
                {
                    "id": str(self.new_org.id),
                    "name": "New Organization",
                    "slug": "new-organization",
                    "logo_media_id": None,
                    "membership_level": 1,
                    "members_can_use_personal_api_keys": True,
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

    def test_pinned_scene_tabs_get_empty(self):
        response = self.client.get("/api/users/@me/pinned_scene_tabs/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.json(),
            {
                "tabs": [],
                "personal_tabs": [],
            },
        )

    def test_pinned_scene_tabs_update(self):
        payload = {
            "personal_tabs": [
                {
                    "id": "tab-1",
                    "pathname": "/a",
                    "search": "?q=1",
                    "hash": "#section",
                    "title": "Tab A",
                    "iconType": "blank",
                    "active": True,
                }
            ],
        }

        response = self.client.patch(
            "/api/users/@me/pinned_scene_tabs/",
            payload,
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        expected_personal_tab = {k: v for k, v in payload["personal_tabs"][0].items() if k != "active"}
        expected_personal_tab["pinned"] = True
        expected_personal_tab["pinnedScope"] = "personal"
        self.assertEqual(
            response.json(),
            {
                "tabs": [expected_personal_tab],
                "personal_tabs": [expected_personal_tab],
            },
        )

        stored = UserPinnedSceneTabs.objects.get(user=self.user, team=self.team)
        self.assertEqual(len(stored.tabs), 1)
        stored_tab = stored.tabs[0]
        self.assertEqual(stored_tab["id"], "tab-1")
        self.assertEqual(stored_tab["pinned"], True)
        self.assertEqual(stored_tab["pinnedScope"], "personal")
        self.assertNotIn("active", stored_tab)

        self.assertFalse(UserPinnedSceneTabs.objects.filter(user=None, team=self.team).exists())

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

    def test_non_admin_filter_users_by_email(self):
        org = Organization.objects.create()
        user = User.objects.create(
            email="foo@bar.com",
            password="<PASSWORD>",
            organization=org,
            current_team=Team.objects.create(organization=org, name="Another team"),
        )

        response = self.client.get(f"/api/users/?email={user.email}")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 0, "Should not return users from another orgs")

    def test_admin_filter_users_by_email(self):
        admin = User.objects.create(
            email="admin@admin.com",
            password="pw",
            organization=self.organization,
            current_team=self.team,
            is_staff=True,
        )
        self.client.force_authenticate(admin)
        org = Organization.objects.create()
        user = User.objects.create(
            email="foo@bar.com",
            password="<PASSWORD>",
            organization=org,
            current_team=Team.objects.create(organization=org, name="Another team"),
        )

        response = self.client.get(f"/api/users/?email={user.email}")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 1, "Admin users should be able to list users from other orgs")
        response_user = response.json()["results"][0]
        self.assertEqual(response_user["email"], user.email)
        self.assertEqual(response_user["id"], user.id, "User id should be returned")

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
                "role_at_organization": "engineering",
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
        self.assertEqual(response_data["role_at_organization"], "engineering")

        user.refresh_from_db()
        self.assertNotEqual(user.pk, 1)
        self.assertNotEqual(user.uuid, 1)
        self.assertEqual(user.first_name, "Cooper")
        self.assertEqual(user.anonymize_data, True)
        self.assertLessEqual({"plugin_disabled": False}.items(), user.notification_settings.items())
        self.assertEqual(user.has_seen_product_intro_for, {"feature_flags": True})
        self.assertEqual(user.role_at_organization, "engineering")

        mock_capture.assert_called_once_with(
            event="user updated",
            distinct_id=user.distinct_id,
            properties={
                "updated_attrs": [
                    "anonymize_data",
                    "events_column_config",
                    "first_name",
                    "has_seen_product_intro_for",
                    "partial_notification_settings",
                    "role_at_organization",
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
    def test_user_can_cancel_own_email_change_request(self, _mock_capture, _mock_identify_task):
        self.user.pending_email = "another@email.com"
        self.user.save()

        response = self.client.patch("/api/users/cancel_email_change_request")

        response_data = response.json()
        assert response.status_code == status.HTTP_200_OK
        assert response_data["pending_email"] is None

    @patch("posthog.tasks.user_identify.identify_task")
    @patch("posthoganalytics.capture")
    def test_user_cannot_cancel_email_change_request_if_it_doesnt_exist(self, _mock_capture, _mock_identify_task):
        # Fire a call to the endpoint without priming the User with a pending_email field

        response = self.client.patch("/api/users/cancel_email_change_request")

        assert response.status_code == status.HTTP_400_BAD_REQUEST

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
                    f"/api/users/verify_email/",
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
            event="user updated",
            distinct_id=self.user.distinct_id,
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
            event="user updated",
            distinct_id=self.user.distinct_id,
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

    def test_team_property_does_not_save_when_no_teams_found(self):
        """
        Test that the team property doesn't trigger a save when the teams query returns None
        """
        # Create a brand new user that belongs to no organizations or teams
        new_user = User.objects.create_user(
            email="newuser@posthog.com", password="testpass123", first_name="New", last_name="User"
        )

        # Clear the cached properties to force re-evaluation
        if hasattr(new_user, "_cached_team"):
            delattr(new_user, "_cached_team")
        if hasattr(new_user, "_cached_organization"):
            delattr(new_user, "_cached_organization")

        # Now test the team property - this should not trigger a save since no teams exist
        with mock.patch.object(new_user, "save") as mock_save:
            team = new_user.team  # Property access, but it can actually perform a save

            # Verify no save was called for the team property
            mock_save.assert_not_called()

            # Verify team is None
            self.assertIsNone(team)
            self.assertIsNone(new_user.current_team)

    def test_team_property_saves_when_team_found(self):
        """
        Test that the team property does trigger a save when a team is found
        """
        # Set current organization but no current team
        self.user.current_team = None
        self.user.save()

        # Clear the cached property to force re-evaluation
        if hasattr(self.user, "_cached_team"):
            delattr(self.user, "_cached_team")

        # Mock the save method to track if it's called
        with mock.patch.object(self.user, "save") as mock_save:
            # Access the team property - this should trigger a save since a team exists
            result_team = self.user.team

            # Verify save was called with correct parameters
            mock_save.assert_called_once_with(update_fields=["current_team"])

            # Verify team is set correctly
            self.assertEqual(result_team, self.team)
            self.assertEqual(self.user.current_team, self.team)

    def test_organization_property_does_not_save_when_no_organizations_found(self):
        """
        Test that the organization property doesn't trigger a save when no organizations exist
        """
        # Create a brand new user that belongs to no organizations or teams
        new_user = User.objects.create_user(
            email="newuser2@posthog.com", password="testpass123", first_name="New", last_name="User"
        )

        # Access the organization property - this should NOT trigger a save since no organizations exist
        with mock.patch.object(new_user, "save") as mock_save:
            organization = new_user.organization

            # Verify no save was called for the organization property
            mock_save.assert_not_called()

            # Verify organization is None
            self.assertIsNone(organization)
            self.assertIsNone(new_user.current_organization)

    def test_organization_property_saves_when_organization_found(self):
        """
        Test that the organization property does trigger a save when an organization is found
        """
        # Create a new organization and add the user to it
        new_org = Organization.objects.create(name="Test Organization")
        self.user.join(organization=new_org)

        # Set current organization to None to simulate the property needing to find and set it
        self.user.current_organization = None
        self.user.save()

        # Clear the cached property to force re-evaluation
        if hasattr(self.user, "_cached_organization"):
            delattr(self.user, "_cached_organization")

        # Mock the save method to track if it's called
        with mock.patch.object(self.user, "save") as mock_save:
            # Access the organization property - this should trigger a save since an organization exists
            result_organization = self.user.organization

            # Verify save was called with correct parameters
            mock_save.assert_called_once_with(update_fields=["current_organization"])

            # Verify organization is set correctly (should be one of the user's organizations)
            self.assertIsNotNone(result_organization)
            self.assertIn(result_organization, [self.organization, new_org])
            self.assertEqual(self.user.current_organization, result_organization)

    @patch("posthog.tasks.user_identify.identify_task")
    @patch("posthoganalytics.capture")
    @patch("posthog.tasks.email.send_password_changed_email.delay")
    def test_user_can_update_password(self, mock_send_password_changed_email, mock_capture, mock_identify):
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
            event="user updated",
            distinct_id=user.distinct_id,
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

        # Assert password changed email was sent
        mock_send_password_changed_email.assert_called_once_with(user.id)

    @patch("posthog.tasks.user_identify.identify_task")
    @patch("posthoganalytics.capture")
    @patch("posthog.tasks.email.send_password_changed_email.delay")
    def test_user_with_no_password_set_can_set_password(
        self, mock_send_password_changed_email, mock_capture, mock_identify
    ):
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
            event="user updated",
            distinct_id=user.distinct_id,
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

        # Assert password changed email was sent
        mock_send_password_changed_email.assert_called_once_with(user.id)

    @patch("posthog.tasks.email.send_password_changed_email.delay")
    def test_user_with_unusable_password_set_can_set_password(self, mock_send_password_changed_email):
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
        self.assertLessEqual(
            {"attr": None, "code": "throttled", "type": "throttled_error"}.items(),
            response.json().items(),
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

    def test_no_ratelimit_for_updates_that_are_not_password_changes(self):
        for _ in range(10):
            response = self.client.patch("/api/users/@me/", {"organization_name": "new name"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_cannot_delete_user_with_organization_memberships(self):
        user = self._create_user("activeorgmemberships@posthog.com", password="test")

        self.client.force_login(user)

        user.join(organization=self.new_org, level=OrganizationMembership.Level.MEMBER)

        assert OrganizationMembership.objects.filter(user=user, organization=self.new_org).exists()

        response = self.client.delete(f"/api/users/@me/")
        assert response.status_code == status.HTTP_409_CONFLICT

    @patch("posthoganalytics.capture")
    def test_can_delete_user_with_no_organization_memberships(self, mock_capture):
        user = self._create_user("noactiveorgmemberships@posthog.com", password="test")

        self.client.force_login(user)

        user.join(organization=self.new_org, level=OrganizationMembership.Level.MEMBER)

        assert OrganizationMembership.objects.filter(user=user, organization=self.new_org).exists()

        OrganizationMembership.objects.filter(user=user).delete()

        assert not OrganizationMembership.objects.filter(user=user).exists()

        response = self.client.delete(f"/api/users/@me/")
        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert not User.objects.filter(uuid=user.uuid).exists()

        mock_capture.assert_called_once_with(
            distinct_id=user.distinct_id,
            event="user account deleted",
            properties=mock.ANY,
        )

    def test_cannot_delete_another_user_with_no_org_memberships(self):
        user = self._create_user("deleteanotheruser@posthog.com", password="test")

        user_with_no_org_memberships = self._create_user("userwithnoorgmemberships@posthog.com", password="test")

        OrganizationMembership.objects.filter(user=user_with_no_org_memberships).delete()

        assert not OrganizationMembership.objects.filter(user=user_with_no_org_memberships).exists()

        self.client.force_login(user)

        response = self.client.delete(f"/api/users/{user_with_no_org_memberships.uuid}/")
        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert User.objects.filter(uuid=user_with_no_org_memberships.uuid).exists()

    def test_forbidden_to_delete_another_user_with_org_memberships(self):
        user = self._create_user("deleteanotheruser@posthog.com", password="test")

        user_with_org_memberships = self._create_user("userwithorgmemberships@posthog.com", password="test")

        assert OrganizationMembership.objects.filter(user=user_with_org_memberships).exists()

        self.client.force_login(user)

        response = self.client.delete(f"/api/users/{user_with_org_memberships.uuid}/")
        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert User.objects.filter(uuid=user_with_org_memberships.uuid).exists()

    def test_cannot_delete_own_user_account_with_personal_api_key(self):
        api_key_value = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="Test Delete User Account Key",
            user=self.user,
            secure_value=hash_key_value(api_key_value),
            scopes=["*"],
        )

        OrganizationMembership.objects.filter(user=self.user).delete()

        assert not OrganizationMembership.objects.filter(user=self.user).exists()

        self.client.logout()

        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {api_key_value}")
        response = self.client.delete(f"/api/users/@me/")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    @patch("posthog.api.user.secrets.token_urlsafe")
    def test_redirect_user_to_site_with_toolbar(self, patched_token):
        patched_token.return_value = "tokenvalue"

        self.team.app_urls = ["http://127.0.0.1:8010"]
        self.team.save()

        response = self.client.get(
            "/api/user/redirect_to_site/?userIntent=add-action&appUrl=http%3A%2F%2F127.0.0.1%3A8010"
        )
        self.assertEqual(response.status_code, status.HTTP_302_FOUND)
        locationHeader = response.headers.get("location", "not found")
        self.assertIn("22apiURL%22%3A%20%22http%3A%2F%2Ftestserver%22", locationHeader)
        self.maxDiff = None
        assert (
            unquote(locationHeader)
            == 'http://127.0.0.1:8010#__posthog={"action": "ph_authorize", "token": "token123", "temporaryToken": "tokenvalue", "actionId": null, "experimentId": null, "userIntent": "add-action", "toolbarVersion": "toolbar", "apiURL": "http://testserver", "dataAttributes": ["data-attr"]}'
        )

    @patch("posthog.api.user.secrets.token_urlsafe")
    def test_generate_params_for_user_to_load_toolbar(self, patched_token):
        patched_token.return_value = "tokenvalue"

        self.team.app_urls = ["http://127.0.0.1:8010"]
        self.team.save()

        response = self.client.get(
            "/api/user/redirect_to_site/?userIntent=add-action&appUrl=http%3A%2F%2F127.0.0.1%3A8010&generateOnly=1"
        )
        assert response.status_code == status.HTTP_200_OK
        assert (
            unquote(response.json()["toolbarParams"])
            == '{"action": "ph_authorize", "token": "token123", "temporaryToken": "tokenvalue", "actionId": null, "experimentId": null, "userIntent": "add-action", "toolbarVersion": "toolbar", "apiURL": "http://testserver", "dataAttributes": ["data-attr"]}'
        )

    @patch("posthog.api.user.secrets.token_urlsafe")
    def test_generate_only_param_can_be_falsy(self, patched_token):
        patched_token.return_value = "tokenvalue"

        self.team.app_urls = ["http://127.0.0.1:8010"]
        self.team.save()

        response = self.client.get(
            "/api/user/redirect_to_site/?userIntent=add-action&appUrl=http%3A%2F%2F127.0.0.1%3A8010&generateOnly=0"
        )
        assert response.status_code == status.HTTP_302_FOUND

    @patch("posthog.api.user.secrets.token_urlsafe")
    def test_redirect_user_to_site_with_experiments_toolbar(self, patched_token):
        patched_token.return_value = "tokenvalue"

        self.team.app_urls = ["http://127.0.0.1:8010"]
        self.team.save()

        response = self.client.get(
            "/api/user/redirect_to_site/?userIntent=edit-experiment&experimentId=12&appUrl=http%3A%2F%2F127.0.0.1%3A8010"
        )
        self.assertEqual(response.status_code, status.HTTP_302_FOUND)
        locationHeader = response.headers.get("location", "not found")
        self.assertIn("22apiURL%22%3A%20%22http%3A%2F%2Ftestserver%22", locationHeader)
        self.maxDiff = None
        self.assertEqual(
            unquote(locationHeader),
            'http://127.0.0.1:8010#__posthog={"action": "ph_authorize", "token": "token123", "temporaryToken": "tokenvalue", "actionId": null, "experimentId": "12", "userIntent": "edit-experiment", "toolbarVersion": "toolbar", "apiURL": "http://testserver", "dataAttributes": ["data-attr"]}',
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

    def test_can_update_notification_settings(self):
        response = self.client.patch(
            "/api/users/@me/",
            {
                "notification_settings": {
                    "plugin_disabled": False,
                    "discussions_mentioned": False,
                    "error_tracking_issue_assigned": False,
                    "project_weekly_digest_disabled": {123: True},
                    "all_weekly_digest_disabled": True,
                }
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data = response.json()
        self.assertEqual(
            response_data["notification_settings"],
            {
                "plugin_disabled": False,
                "discussions_mentioned": False,
                "project_weekly_digest_disabled": {"123": True},  # Note: JSON converts int keys to strings
                "all_weekly_digest_disabled": True,
                "error_tracking_issue_assigned": False,
            },
        )

        self.user.refresh_from_db()
        self.assertEqual(
            self.user.partial_notification_settings,
            {
                "plugin_disabled": False,
                "discussions_mentioned": False,
                "project_weekly_digest_disabled": {"123": True},
                "all_weekly_digest_disabled": True,
                "error_tracking_issue_assigned": False,
            },
        )

    def test_notification_settings_project_settings_are_merged_not_replaced(self):
        # First update
        response = self.client.patch(
            "/api/users/@me/", {"notification_settings": {"project_weekly_digest_disabled": {123: True}}}
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Second update with different project
        response = self.client.patch(
            "/api/users/@me/", {"notification_settings": {"project_weekly_digest_disabled": {456: True}}}
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        response_data = response.json()
        self.assertEqual(
            response_data["notification_settings"]["project_weekly_digest_disabled"], {"123": True, "456": True}
        )

    def test_invalid_notification_settings_returns_error(self):
        response = self.client.patch("/api/users/@me/", {"notification_settings": {"invalid_key": True}})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json(),
            {
                "type": "validation_error",
                "code": "invalid_input",
                "detail": "Key invalid_key is not valid as a key for notification settings",
                "attr": "notification_settings",
            },
        )

    def test_notification_settings_wrong_type_returns_error(self):
        response = self.client.patch(
            "/api/users/@me/",
            {
                "notification_settings": {
                    "project_weekly_digest_disabled": {"123": "not a boolean"}  # This should be True or False
                }
            },
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json(),
            {
                "type": "validation_error",
                "code": "invalid_input",
                "detail": "Project notification setting values must be boolean, got <class 'str'> instead",
                "attr": "notification_settings",
            },
        )

    def test_can_disable_all_notifications(self):
        response = self.client.patch("/api/users/@me/", {"notification_settings": {"all_weekly_digest_disabled": True}})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data = response.json()
        self.assertEqual(
            response_data["notification_settings"],
            {
                "plugin_disabled": True,  # Default value
                "discussions_mentioned": True,  # Default value
                "project_weekly_digest_disabled": {},  # Default value
                "all_weekly_digest_disabled": True,
                "error_tracking_issue_assigned": True,  # Default value
            },
        )


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


class TestEmailVerificationAPI(APIBaseTest):
    CONFIG_AUTO_LOGIN = False

    def setUp(self):
        # prevent throttling of user requests to pass on from one test
        # to the next
        cache.clear()
        super().setUp()

        set_instance_setting("EMAIL_HOST", "localhost")

        self.other_user = self._create_user("otheruser@posthog.com", password="12345678")
        assert not self.other_user.is_email_verified
        assert not self.other_user.is_email_verified

    # Email verification request

    @patch("posthoganalytics.capture")
    def test_user_can_request_verification_email(self, mock_capture):
        set_instance_setting("EMAIL_HOST", "localhost")
        with self.settings(CELERY_TASK_ALWAYS_EAGER=True, SITE_URL="https://my.posthog.net"):
            response = self.client.post(f"/api/users/request_email_verification/", {"uuid": self.user.uuid})
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

        response = self.client.post(f"/api/users/verify_email/", {"uuid": self.user.uuid, "token": token})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # check is_email_verified is changed to True
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_email_verified)

        # assert events were captured
        mock_capture.assert_any_call(
            event="user logged in",
            distinct_id=self.user.distinct_id,
            properties={"social_provider": ""},
            groups={
                "instance": ANY,
                "organization": str(self.team.organization_id),
                "project": str(self.team.uuid),
            },
        )
        mock_capture.assert_any_call(
            event="user verified email",
            distinct_id=self.user.distinct_id,
            properties={"$set": ANY},
        )

        mock_capture.assert_any_call(
            event="verification email sent",
            distinct_id=self.user.distinct_id,
            groups={
                "organization": str(self.team.organization_id),
            },
        )
        self.assertEqual(mock_capture.call_count, 3)

    def test_cant_verify_if_email_is_not_configured(self):
        set_instance_setting("EMAIL_HOST", "")
        with self.settings(CELERY_TASK_ALWAYS_EAGER=True):
            response = self.client.post(f"/api/users/request_email_verification/", {"uuid": self.user.uuid})
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
                    f"/api/users/request_email_verification/",
                    {"uuid": self.user.uuid},
                )
            if i < 6:
                self.assertEqual(response.status_code, status.HTTP_200_OK)
            else:
                # Fourth request should fail
                self.assertEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
                self.assertLessEqual(
                    {"attr": None, "code": "throttled", "type": "throttled_error"}.items(),
                    response.json().items(),
                )

        # Three emails should be sent, fourth should not
        self.assertEqual(len(mail.outbox), 6)

    # Token validation

    def test_can_validate_email_verification_token(self):
        token = email_verification_token_generator.make_token(self.user)
        response = self.client.post(f"/api/users/verify_email/", {"uuid": self.user.uuid, "token": token})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_cant_validate_email_verification_token_without_a_token(self):
        response = self.client.post(f"/api/users/verify_email/", {"uuid": self.user.uuid})
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
                f"/api/users/verify_email/",
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

    def test_can_only_validate_email_token_one_time(self):
        token = email_verification_token_generator.make_token(self.user)
        response = self.client.post(f"/api/users/verify_email/", {"uuid": self.user.uuid, "token": token})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        response = self.client.post(f"/api/users/verify_email/", {"uuid": self.user.uuid, "token": token})
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

    def test_email_verification_logs_in_user(self):
        token = email_verification_token_generator.make_token(self.user)

        self.client.logout()
        assert self.client.get("/api/users/@me/").status_code == 401
        session_user_id = self.client.session.get("_auth_user_id")
        assert session_user_id is None

        # NOTE: Posting sets the session user id but doesn't log in the test client hence we just check the session id
        self.client.post(f"/api/users/verify_email/", {"uuid": self.user.uuid, "token": token})
        session_user_id = self.client.session.get("_auth_user_id")
        assert session_user_id == str(self.user.id)

    def test_email_verification_logs_in_correctuser(self):
        other_token = email_verification_token_generator.make_token(self.other_user)
        self.client.logout()
        assert self.client.session.get("_auth_user_id") is None

        # NOTE: The user id in path should basically be ignored
        self.client.post(f"/api/users/verify_email/", {"uuid": self.other_user.uuid, "token": other_token})
        session_user_id = self.client.session.get("_auth_user_id")
        assert session_user_id == str(self.other_user.id)

    def test_email_verification_does_not_apply_to_current_logged_in_user(self):
        other_token = email_verification_token_generator.make_token(self.other_user)

        res = self.client.post(f"/api/users/verify_email/", {"uuid": self.other_user.uuid, "token": other_token})
        assert res.status_code == status.HTTP_200_OK
        self.user.refresh_from_db()
        self.other_user.refresh_from_db()
        # Should now be logged in as other user
        assert self.client.session.get("_auth_user_id") == str(self.other_user.id)
        assert not self.user.is_email_verified
        assert self.other_user.is_email_verified

    def test_email_verification_fails_if_using_other_accounts_token(self):
        token = email_verification_token_generator.make_token(self.user)
        other_token = email_verification_token_generator.make_token(self.other_user)
        self.client.logout()

        assert (
            self.client.post(f"/api/users/verify_email/", {"uuid": self.other_user.uuid, "token": token}).status_code
            == status.HTTP_400_BAD_REQUEST
        )

        assert (
            self.client.post(f"/api/users/verify_email/", {"uuid": self.user.uuid, "token": other_token}).status_code
            == status.HTTP_400_BAD_REQUEST
        )

    def test_does_not_apply_pending_email_for_old_tokens(self):
        self.client.logout()

        token = email_verification_token_generator.make_token(self.user)
        self.user.pending_email = "new@posthog.com"
        self.user.save()

        response = self.client.post(f"/api/users/verify_email/", {"uuid": self.user.uuid, "token": token})
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert self.user.email != "new@posthog.com"
        assert self.user.pending_email == "new@posthog.com"

        token = email_verification_token_generator.make_token(self.user)
        response = self.client.post(f"/api/users/verify_email/", {"uuid": self.user.uuid, "token": token})
        assert response.status_code == status.HTTP_200_OK
        self.user.refresh_from_db()
        assert self.user.email == "new@posthog.com"
        assert self.user.pending_email is None


class TestUserTwoFactor(APIBaseTest):
    def setUp(self):
        super().setUp()
        # prevent throttling of user requests to pass on from one test
        # to the next
        cache.clear()

    @patch("posthog.api.user.TOTPDeviceForm")
    def test_two_factor_start_setup(self, mock_totp_form):
        response = self.client.get(f"/api/users/@me/two_factor_start_setup/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), {"success": True, "secret": ANY})

        # Verify session contains required keys
        self.assertIn("django_two_factor-hex", self.client.session)
        self.assertIn("django_two_factor-qr_secret_key", self.client.session)
        self.assertEqual(len(self.client.session["django_two_factor-hex"]), 40)  # 20 bytes hex = 40 chars

    @patch("posthog.api.user.send_two_factor_auth_enabled_email")
    @patch("posthog.api.user.TOTPDeviceForm")
    def test_two_factor_validation_with_valid_token(self, mock_totp_form, mock_send_email):
        # Setup form mock
        mock_form_instance = mock_totp_form.return_value
        mock_form_instance.is_valid.return_value = True

        # Setup session state
        session = self.client.session
        session["django_two_factor-hex"] = "1234567890abcdef1234"
        session.save()

        response = self.client.post(f"/api/users/@me/two_factor_validate/", {"token": "123456"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), {"success": True})

        # Verify form was created with correct params
        mock_totp_form.assert_called_once_with("1234567890abcdef1234", self.user, data={"token": "123456"})
        mock_form_instance.save.assert_called_once()

        # Verify email was triggered
        mock_send_email.delay.assert_called_once_with(self.user.id)

    @patch("posthog.api.user.TOTPDeviceForm")
    def test_two_factor_validation_with_invalid_token(self, mock_totp_form):
        # Setup form mock to fail validation
        mock_form_instance = mock_totp_form.return_value
        mock_form_instance.is_valid.return_value = False

        # Setup session state
        session = self.client.session
        session["django_two_factor-hex"] = "1234567890abcdef1234"
        session.save()

        response = self.client.post(f"/api/users/@me/two_factor_validate/", {"token": "invalid"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json(),
            {
                "type": "validation_error",
                "code": "token_invalid",
                "detail": "Token is not valid",
                "attr": None,
            },
        )

    def test_two_factor_status_when_disabled(self):
        response = self.client.get(f"/api/users/@me/two_factor_status/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.json(),
            {
                "is_enabled": False,
                "backup_codes": [],
                "method": None,
            },
        )

    @patch("posthog.api.user.default_device")
    def test_two_factor_status_when_enabled(self, mock_default_device):
        # Mock TOTP device
        totp_device = TOTPDevice.objects.create(user=self.user, name="default")
        mock_default_device.return_value = totp_device

        # Create backup codes
        static_device = StaticDevice.objects.create(user=self.user, name="backup")
        static_device.token_set.create(token="123456")
        static_device.token_set.create(token="789012")

        response = self.client.get(f"/api/users/@me/two_factor_status/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.json(),
            {
                "is_enabled": True,
                "backup_codes": ["123456", "789012"],
                "method": "TOTP",
            },
        )

    @patch("posthog.api.user.default_device")
    def test_two_factor_backup_codes_generation(self, mock_default_device):
        # Mock TOTP device to simulate 2FA being enabled
        totp_device = TOTPDevice.objects.create(user=self.user, name="default")
        mock_default_device.return_value = totp_device

        response = self.client.post(f"/api/users/@me/two_factor_backup_codes/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        backup_codes = response.json()["backup_codes"]
        self.assertEqual(len(backup_codes), 5)  # Verify 5 backup codes are generated

        # Verify codes are stored in database
        static_device = StaticDevice.objects.get(user=self.user)
        stored_codes = [token.token for token in static_device.token_set.all()]
        self.assertEqual(sorted(backup_codes), sorted(stored_codes))

    def test_two_factor_backup_codes_requires_2fa_enabled(self):
        response = self.client.post(f"/api/users/@me/two_factor_backup_codes/")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json(),
            {
                "type": "validation_error",
                "code": "2fa_not_enabled",
                "detail": "2FA must be enabled first",
                "attr": None,
            },
        )

    @patch("posthog.api.user.send_two_factor_auth_disabled_email")
    def test_two_factor_disable(self, mock_send_email):
        # Setup 2FA devices
        TOTPDevice.objects.create(user=self.user, name="default")
        static_device = StaticDevice.objects.create(user=self.user, name="backup")
        static_device.token_set.create(token="123456")

        response = self.client.post(f"/api/users/@me/two_factor_disable/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), {"success": True})

        # Verify all 2FA devices are removed
        self.assertEqual(TOTPDevice.objects.filter(user=self.user).count(), 0)
        self.assertEqual(StaticDevice.objects.filter(user=self.user).count(), 0)

        # Verify email was triggered
        mock_send_email.delay.assert_called_once_with(self.user.id)

    @override_settings(
        OAUTH2_PROVIDER={
            **settings.OAUTH2_PROVIDER,
            "OIDC_RSA_PRIVATE_KEY": generate_rsa_key(),
        }
    )
    def test_team_scoped_oauth_token_with_user_read_can_access_me_endpoint(self):
        oauth_app = OAuthApplication.objects.create(
            name="Test OAuth App",
            client_id="test_client_id",
            client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://example.com/callback",
            algorithm="RS256",
            user=self.user,
        )

        access_token = OAuthAccessToken.objects.create(
            application=oauth_app,
            user=self.user,
            token="test_oauth_token",
            scope="user:read project:read",
            expires=timezone.now() + timedelta(hours=1),
            scoped_teams=[self.team.id],
        )

        response = self.client.get("/api/users/@me/", HTTP_AUTHORIZATION=f"Bearer {access_token.token}")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data = response.json()
        self.assertEqual(response_data["uuid"], str(self.user.uuid))
