from unittest.mock import patch

from rest_framework import status

from posthog.models import Team, User
from posthog.models.organization import OrganizationMembership
from posthog.test.base import APITransactionBaseTest, BaseTest


class TestUser(BaseTest):
    TESTS_API = True

    # TODO: Move to TestUserAPI once endpoint is refactored to DRF
    def test_user_team_update(self):
        response = self.client.patch(
            "/api/user/",
            data={"team": {"anonymize_ips": False, "session_recording_opt_in": True}},
            content_type="application/json",
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


class TestUserChangePassword(BaseTest):
    TESTS_API = True
    ENDPOINT: str = "/api/user/change_password/"

    def send_request(self, payload):
        return self.client.patch(self.ENDPOINT, payload, content_type="application/json")

    def test_change_password_no_data(self):
        response = self.send_request({})
        self.assertEqual(response.status_code, 400)

    def test_change_password_invalid_old_password(self):
        response = self.send_request({"currentPassword": "12345", "newPassword": "12345"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "Incorrect old password")

    def test_change_password_invalid_new_password(self):
        response = self.send_request({"currentPassword": self.TESTS_PASSWORD, "newPassword": "123456"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "This password is too short. It must contain at least 8 characters.")

    def test_change_password_success(self):
        response = self.send_request(
            {"currentPassword": self.TESTS_PASSWORD, "newPassword": "prettyhardpassword123456",}
        )
        self.assertEqual(response.status_code, 200)


class TestUserSlackWebhook(BaseTest):
    TESTS_API = True
    ENDPOINT: str = "/api/user/test_slack_webhook/"

    def send_request(self, payload):
        return self.client.post(self.ENDPOINT, payload, content_type="application/json")

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


class TestLoginViews(BaseTest):
    def test_redirect_to_preflight_when_no_users(self):
        User.objects.all().delete()
        response = self.client.get("/", follow=True)
        self.assertRedirects(response, "/preflight")


class TestUserAPI(APITransactionBaseTest):
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
