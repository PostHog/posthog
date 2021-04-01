from unittest.mock import patch

from rest_framework import status

from posthog.models import Team, User
from posthog.models.organization import Organization, OrganizationMembership
from posthog.test.base import APIBaseTest


class TestUserAPI(APIBaseTest):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.new_org = Organization.objects.create(name="New Organization")
        cls.new_project = Team.objects.create(name="New Project", organization=cls.new_org)
        cls.user.join(organization=cls.new_org)
        cls.user.current_organization = cls.organization
        cls.user.current_team = cls.team
        cls.user.save()

    def test_retrieve_current_user(self):

        response = self.client.get("/api/v2/user/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data = response.json()

        self.assertEqual(response_data["id"], str(self.user.uuid))
        self.assertEqual(response_data["first_name"], self.user.first_name)
        self.assertEqual(response_data["email"], self.user.email)
        self.assertEqual(response_data["has_password"], True)
        self.assertEqual(response_data["is_staff"], False)
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

        self.assertEqual(
            response_data["organizations"],
            [
                {"id": str(self.organization.id), "name": self.organization.name},
                {"id": str(self.new_org.id), "name": "New Organization"},
            ],
        )

    def test_update_current_user(self):
        another_org = Organization.objects.create(name="Another Org")
        another_team = Team.objects.create(name="Another Team", organization=another_org)
        user = self._create_user("old@posthog.com", password="12345678")
        self.client.force_login(user)
        response = self.client.patch(
            "/api/v2/user/",
            {
                "first_name": "Cooper",
                "email": "updated@posthog.com",
                "anonymize_data": True,
                "email_opt_in": False,
                "id": 1,  # should be ignored
                "is_staff": True,  # should be ignored
                "organization": str(another_org.id),  # should be ignored
                "team": str(another_team.id),  # should be ignored
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data = response.json()

        self.assertNotEqual(response_data["id"], 1)
        self.assertEqual(response_data["first_name"], "Cooper")
        self.assertEqual(response_data["email"], "updated@posthog.com")
        self.assertEqual(response_data["anonymize_data"], True)
        self.assertEqual(response_data["email_opt_in"], False)
        self.assertEqual(response_data["is_staff"], False)
        self.assertEqual(response_data["organization"]["id"], str(self.organization.id))
        self.assertEqual(response_data["team"]["id"], str(self.team.id))
        self.assertEqual(response_data["team"]["id"], self.team.id)

        user.refresh_from_db()
        self.assertNotEqual(user.pk, 1)
        self.assertEqual(user.first_name, "Cooper")
        self.assertEqual(user.email, "updated@posthog.com")
        self.assertEqual(user.anonymize_data, True)


class TestUserAPILegacy(APIBaseTest):
    """
    Tests for the legacy /api/user endpoint.
    """

    def test_user_team_update(self):
        response = self.client.patch(
            "/api/user/", data={"team": {"anonymize_ips": False, "session_recording_opt_in": True}},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data = response.json()

        self.assertEqual(response_data["team"]["anonymize_ips"], False)
        self.assertEqual(response_data["team"]["session_recording_opt_in"], True)

        team = Team.objects.get(id=self.team.id)
        self.assertEqual(team.anonymize_ips, False)
        self.assertEqual(team.session_recording_opt_in, True)

    def test_event_names_job_not_run_yet(self):
        self.team.event_names = ["test event", "another event"]
        # test event not in event_names_with_usage
        self.team.event_names_with_usage = [{"event": "another event", "volume": 1, "usage_count": 1}]
        self.team.event_properties = ["test prop", "another prop"]
        self.team.event_properties_with_usage = [{"key": "another prop", "volume": 1, "usage_count": 1}]
        self.team.save()
        response = self.client.get("/api/user/")
        self.assertEqual(
            response.json()["team"]["event_names_with_usage"],
            [
                {"event": "test event", "volume": None, "usage_count": None},
                {"event": "another event", "volume": 1, "usage_count": 1},
            ],
        )
        self.assertEqual(
            response.json()["team"]["event_properties_with_usage"],
            [
                {"key": "test prop", "volume": None, "usage_count": None},
                {"key": "another prop", "volume": 1, "usage_count": 1},
            ],
        )

    def test_redirect_to_site(self):
        self.team.app_urls = ["http://somewebsite.com"]
        self.team.save()
        response = self.client.get("/api/user/redirect_to_site/?actionId=1")
        self.assertIn("http://somewebsite.com", response.url)

    @patch("posthoganalytics.identify")
    def test_user_api(self, mock_identify):
        # create another project/user to test analytics input
        for _ in range(0, 2):
            Team.objects.create(organization=self.organization, completed_snippet_onboarding=True, ingested_event=True)
        u = User.objects.create(email="user4@posthog.com")
        OrganizationMembership.objects.create(user=u, organization=self.organization)

        with self.settings(EE_AVAILABLE=True, MULTI_TENANCY=False):
            response = self.client.get("/api/user/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data = response.json()

        # TODO: When refactoring this to DRF; assert the full response is what's expected
        self.assertEqual(response_data["distinct_id"], self.user.distinct_id)

        # Make sure the user is update in PostHog (analytics)
        mock_identify.assert_called_once_with(
            self.user.distinct_id,
            {
                "realm": "hosted",
                "is_ee_available": True,
                "email_opt_in": False,
                "anonymize_data": False,
                "email": "user1@posthog.com",
                "is_signed_up": True,
                "organization_count": 1,
                "project_count": 3,
                "team_member_count_all": 2,
                "completed_onboarding_once": True,
                "billing_plan": None,
                "organization_id": str(self.organization.id),
                "project_id": str(self.team.uuid),
                "project_setup_complete": False,
                "joined_at": self.user.date_joined,
                "has_password_set": True,
                "has_social_auth": False,
                "social_providers": [],
            },
        )


class TestUserChangePassword(APIBaseTest):
    ENDPOINT: str = "/api/user/change_password/"

    def send_request(self, payload):
        return self.client.patch(self.ENDPOINT, payload)

    def test_change_password_no_data(self):
        response = self.send_request({})
        self.assertEqual(response.status_code, 400)

    def test_change_password_invalid_old_password(self):
        response = self.send_request({"currentPassword": "12345", "newPassword": "12345"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "Incorrect old password")

    def test_change_password_invalid_new_password(self):
        response = self.send_request({"currentPassword": self.CONFIG_PASSWORD, "newPassword": "123456"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "This password is too short. It must contain at least 8 characters.")

    def test_change_password_success(self):
        response = self.send_request(
            {"currentPassword": self.CONFIG_PASSWORD, "newPassword": "prettyhardpassword123456"}
        )
        self.assertEqual(response.status_code, 200)


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
