import uuid
from unittest.mock import ANY, patch

import pytest
from django.core.cache import cache
from django.utils.text import slugify
from rest_framework import status

from posthog.models import Tag, Team, User
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
                    "membership_level": 1,
                },
                {
                    "id": str(self.new_org.id),
                    "name": "New Organization",
                    "slug": "new-organization",
                    "membership_level": 1,
                },
            ],
        )

    @pytest.mark.ee
    def test_organization_metadata_on_user_serializer(self):

        from ee.models import EnterpriseEventDefinition, EnterprisePropertyDefinition

        enterprise_event = EnterpriseEventDefinition.objects.create(
            team=self.team, name="enterprise event", owner=self.user
        )
        tag = Tag.objects.create(name="deprecated", team_id=self.team.id)
        enterprise_event.tagged_items.create(tag_id=tag.id)
        EnterpriseEventDefinition.objects.create(
            team=self.team, name="a new event", owner=self.user  # I shouldn't be counted
        )
        timestamp_property = EnterprisePropertyDefinition.objects.create(
            team=self.team, name="a timestamp", property_type="DateTime", description="This is a cool timestamp.",
        )
        tag_test = Tag.objects.create(name="test", team_id=self.team.id)
        tag_official = Tag.objects.create(name="official", team_id=self.team.id)
        timestamp_property.tagged_items.create(tag_id=tag_test.id)
        timestamp_property.tagged_items.create(tag_id=tag_official.id)
        EnterprisePropertyDefinition.objects.create(
            team=self.team, name="plan", description="The current membership plan the user has active.",
        )
        tagged_property = EnterprisePropertyDefinition.objects.create(team=self.team, name="property")
        tag_test2 = Tag.objects.create(name="test2", team_id=self.team.id)
        tagged_property.tagged_items.create(tag_id=tag_test2.id)
        EnterprisePropertyDefinition.objects.create(
            team=self.team, name="some_prop",  # I shouldn't be counted
        )

        response = self.client.get("/api/users/@me/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data = response.json()
        self.assertEqual(response_data["organization"]["metadata"]["taxonomy_set_events_count"], 1)
        self.assertEqual(response_data["organization"]["metadata"]["taxonomy_set_properties_count"], 3)

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

    @patch("posthoganalytics.capture")
    def test_update_current_user(self, mock_capture):
        another_org = Organization.objects.create(name="Another Org")
        another_team = Team.objects.create(name="Another Team", organization=another_org)
        user = self._create_user("old@posthog.com", password="12345678")
        self.client.force_login(user)
        response = self.client.patch(
            "/api/users/@me/",
            {
                "first_name": "Cooper",
                "email": "updated@posthog.com",
                "anonymize_data": True,
                "email_opt_in": False,
                "events_column_config": {"active": ["column_1", "column_2"]},
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
        self.assertEqual(response_data["email"], "updated@posthog.com")
        self.assertEqual(response_data["anonymize_data"], True)
        self.assertEqual(response_data["email_opt_in"], False)
        self.assertEqual(response_data["events_column_config"], {"active": ["column_1", "column_2"]})
        self.assertEqual(response_data["organization"]["id"], str(self.organization.id))
        self.assertEqual(response_data["team"]["id"], self.team.id)

        user.refresh_from_db()
        self.assertNotEqual(user.pk, 1)
        self.assertNotEqual(user.uuid, 1)
        self.assertEqual(user.first_name, "Cooper")
        self.assertEqual(user.email, "updated@posthog.com")
        self.assertEqual(user.anonymize_data, True)

        mock_capture.assert_called_once_with(
            user.distinct_id,
            "user updated",
            properties={
                "updated_attrs": ["anonymize_data", "email", "email_opt_in", "events_column_config", "first_name"],
            },
            groups={"instance": ANY, "organization": str(self.team.organization_id), "project": str(self.team.uuid),},
        )

    def test_cannot_upgrade_yourself_to_staff_user(self):
        response = self.client.patch("/api/users/@me/", {"is_staff": True},)

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(
            response.json(), self.permission_denied_response("You are not a staff user, contact your instance admin.")
        )

        self.user.refresh_from_db()
        self.assertEqual(self.user.is_staff, False)

    @patch("posthoganalytics.capture")
    def test_can_update_current_organization(self, mock_capture):
        response = self.client.patch("/api/users/@me/", {"set_current_organization": str(self.new_org.id)},)
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
            properties={"updated_attrs": ["current_organization", "current_team"]},
            groups={"instance": ANY, "organization": str(self.new_org.id), "project": str(self.new_project.uuid),},
        )

    @patch("posthoganalytics.capture")
    def test_can_update_current_project(self, mock_capture):
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
            properties={"updated_attrs": ["current_organization", "current_team"]},
            groups={"instance": ANY, "organization": str(self.new_org.id), "project": str(team.uuid),},
        )

    def test_cannot_set_mismatching_org_and_team(self):
        org = Organization.objects.create(name="Isolated Org")
        first_team = Team.objects.create(name="Isolated Team", organization=org)
        team = Team.objects.create(name="Isolated Team 2", organization=org)
        self.user.join(organization=org)

        response = self.client.patch(
            "/api/users/@me/", {"set_current_team": team.id, "set_current_organization": self.organization.id}
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

    @patch("posthoganalytics.capture")
    def test_user_can_update_password(self, mock_capture):

        user = self._create_user("bob@posthog.com", password="A12345678")
        self.client.force_login(user)

        response = self.client.patch("/api/users/@me/", {"current_password": "A12345678", "password": "a_new_password"})
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
            properties={"updated_attrs": ["password"]},
            groups={"instance": ANY, "organization": str(self.team.organization_id), "project": str(self.team.uuid),},
        )

        # User can log in with new password
        response = self.client.post("/api/login", {"email": "bob@posthog.com", "password": "a_new_password"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    @patch("posthoganalytics.capture")
    def test_user_with_no_password_set_can_set_password(self, mock_capture):
        user = self._create_user("no_password@posthog.com", password=None)
        self.client.force_login(user)

        response = self.client.patch(
            "/api/users/@me/", {"password": "a_new_password"},  # note we don't send current password
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
            properties={"updated_attrs": ["password"]},
            groups={"instance": ANY, "organization": str(self.team.organization_id), "project": str(self.team.uuid),},
        )

        # User can log in with new password
        response = self.client.post("/api/login", {"email": "no_password@posthog.com", "password": "a_new_password"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_user_with_unusable_password_set_can_set_password(self):
        user = self._create_user("no_password@posthog.com", password="123456789")
        user.set_unusable_password()
        user.save()
        self.client.force_login(user)

        response = self.client.patch("/api/users/@me/", {"password": "a_new_password"},)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Assert session is still valid
        get_response = self.client.get("/api/users/@me/")
        self.assertEqual(get_response.status_code, status.HTTP_200_OK)

        # Password was successfully changed
        user.refresh_from_db()
        self.assertTrue(user.check_password("a_new_password"))

    @patch("posthoganalytics.capture")
    def test_cant_update_to_insecure_password(self, mock_capture):

        response = self.client.patch("/api/users/@me/", {"current_password": self.CONFIG_PASSWORD, "password": "123"})
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

        for i in range(7):
            response = self.client.patch("/api/users/@me/", {"current_password": "wrong", "password": "12345678"})
        self.assertEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
        self.assertDictContainsSubset(
            {"attr": None, "code": "throttled", "type": "throttled_error"}, response.json(),
        )

        # Password was not changed
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(self.CONFIG_PASSWORD))

    def test_no_ratelimit_for_get_requests_for_users(self):

        for i in range(10):
            response = self.client.get("/api/users/@me/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

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

        response = self.client.get(
            "/api/user/redirect_to_site/?userIntent=add-action&appUrl=http%3A%2F%2F127.0.0.1%3A8000"
        )
        self.assertEqual(response.status_code, status.HTTP_302_FOUND)
        locationHeader = response.headers.get("location", "not found")
        self.assertIn(
            "%22jsURL%22%3A%20%22http%3A%2F%2Flocalhost%3A8234%22", locationHeader,
        )
        self.maxDiff = None
        self.assertEqual(
            locationHeader,
            "http://127.0.0.1:8000#__posthog=%7B%22action%22%3A%20%22ph_authorize%22%2C%20%22token%22%3A%20%22token123%22%2C%20%22temporaryToken%22%3A%20%22tokenvalue%22%2C%20%22actionId%22%3A%20null%2C%20%22userIntent%22%3A%20%22add-action%22%2C%20%22toolbarVersion%22%3A%20%22toolbar%22%2C%20%22dataAttributes%22%3A%20%5B%22data-attr%22%5D%2C%20%22jsURL%22%3A%20%22http%3A%2F%2Flocalhost%3A8234%22%7D",
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
