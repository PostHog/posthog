from django.conf import settings
from rest_framework import status

from posthog.models import Action, Cohort, Dashboard, FeatureFlag, Insight, Team
from posthog.models.organization import Organization
from posthog.models.team import Team
from posthog.test.base import APIBaseTest


class TestAccessMiddleware(APIBaseTest):
    CONFIG_AUTO_LOGIN = False

    def test_ip_range(self):
        """
        Also test that capture endpoint is not restrictied by ALLOWED_IP_BLOCKS
        """

        with self.settings(ALLOWED_IP_BLOCKS=["192.168.0.0/31", "127.0.0.0/25", "128.0.0.1"]):

            # not in list
            response = self.client.get("/", REMOTE_ADDR="10.0.0.1")
            self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
            self.assertIn(b"IP is not allowed", response.content)

            response = self.client.get("/batch/", REMOTE_ADDR="10.0.0.1",)

            self.assertEqual(
                response.status_code, status.HTTP_400_BAD_REQUEST
            )  # Check for a bad request exception because it means the middleware didn't block the request

            # /31 block
            response = self.client.get("/", REMOTE_ADDR="192.168.0.1")
            self.assertNotEqual(response.status_code, status.HTTP_403_FORBIDDEN)
            self.assertNotIn(b"IP is not allowed", response.content)

            response = self.client.get("/", REMOTE_ADDR="192.168.0.2")
            self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
            self.assertIn(b"IP is not allowed", response.content)

            response = self.client.get("/batch/", REMOTE_ADDR="192.168.0.1")
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

            response = self.client.get("/batch/", REMOTE_ADDR="192.168.0.2")
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

            # /24 block
            response = self.client.get("/", REMOTE_ADDR="127.0.0.1")
            self.assertNotEqual(response.status_code, status.HTTP_403_FORBIDDEN)
            self.assertNotIn(b"IP is not allowed", response.content)

            response = self.client.get("/", REMOTE_ADDR="127.0.0.100")
            self.assertNotEqual(response.status_code, status.HTTP_403_FORBIDDEN)
            self.assertNotIn(b"IP is not allowed", response.content)

            response = self.client.get("/", REMOTE_ADDR="127.0.0.200")
            self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
            self.assertIn(b"IP is not allowed", response.content)

            # precise ip
            response = self.client.get("/", REMOTE_ADDR="128.0.0.1")
            self.assertNotEqual(response.status_code, status.HTTP_403_FORBIDDEN)
            self.assertNotIn(b"IP is not allowed", response.content)

            response = self.client.get("/", REMOTE_ADDR="128.0.0.2")
            self.assertIn(b"IP is not allowed", response.content)

    def test_trusted_proxies(self):
        with self.settings(
            ALLOWED_IP_BLOCKS=["192.168.0.0/31", "127.0.0.0/25,128.0.0.1"], USE_X_FORWARDED_HOST=True,
        ):
            with self.settings(TRUSTED_PROXIES="10.0.0.1"):
                response = self.client.get("/", REMOTE_ADDR="10.0.0.1", HTTP_X_FORWARDED_FOR="192.168.0.1,10.0.0.1",)
                self.assertNotIn(b"IP is not allowed", response.content)

    def test_attempt_spoofing(self):
        with self.settings(
            ALLOWED_IP_BLOCKS=["192.168.0.0/31", "127.0.0.0/25,128.0.0.1"], USE_X_FORWARDED_HOST=True,
        ):
            with self.settings(TRUSTED_PROXIES="10.0.0.1"):
                response = self.client.get("/", REMOTE_ADDR="10.0.0.1", HTTP_X_FORWARDED_FOR="192.168.0.1,10.0.0.2",)
                self.assertIn(b"IP is not allowed", response.content)

    def test_trust_all_proxies(self):
        with self.settings(
            ALLOWED_IP_BLOCKS=["192.168.0.0/31", "127.0.0.0/25,128.0.0.1"], USE_X_FORWARDED_HOST=True,
        ):
            with self.settings(TRUST_ALL_PROXIES=True):
                response = self.client.get("/", REMOTE_ADDR="10.0.0.1", HTTP_X_FORWARDED_FOR="192.168.0.1,10.0.0.1",)
                self.assertNotIn(b"IP is not allowed", response.content)


class TestToolbarCookieMiddleware(APIBaseTest):
    CONFIG_AUTO_LOGIN = False

    def test_logged_out_client(self):
        response = self.client.get("/")
        self.assertEqual(0, len(response.cookies))

    def test_logged_in_client(self):
        with self.settings(TOOLBAR_COOKIE_NAME="phtoolbar", TOOLBAR_COOKIE_SECURE=False):
            self.client.force_login(self.user)

            response = self.client.get("/")
            toolbar_cookie = response.cookies[settings.TOOLBAR_COOKIE_NAME]

            self.assertEqual(toolbar_cookie.key, settings.TOOLBAR_COOKIE_NAME)
            self.assertEqual(toolbar_cookie.value, "yes")
            self.assertEqual(toolbar_cookie["path"], "/")
            self.assertEqual(toolbar_cookie["samesite"], "None")
            self.assertEqual(toolbar_cookie["httponly"], True)
            self.assertEqual(toolbar_cookie["domain"], "")
            self.assertEqual(toolbar_cookie["comment"], "")
            self.assertEqual(toolbar_cookie["secure"], "")
            self.assertEqual(toolbar_cookie["max-age"], 31536000)

    def test_logged_in_client_secure(self):
        with self.settings(TOOLBAR_COOKIE_NAME="phtoolbar", TOOLBAR_COOKIE_SECURE=True):
            self.client.force_login(self.user)

            response = self.client.get("/")
            toolbar_cookie = response.cookies[settings.TOOLBAR_COOKIE_NAME]

            self.assertEqual(toolbar_cookie.key, "phtoolbar")
            self.assertEqual(toolbar_cookie.value, "yes")
            self.assertEqual(toolbar_cookie["path"], "/")
            self.assertEqual(toolbar_cookie["samesite"], "None")
            self.assertEqual(toolbar_cookie["httponly"], True)
            self.assertEqual(toolbar_cookie["domain"], "")
            self.assertEqual(toolbar_cookie["comment"], "")
            self.assertEqual(toolbar_cookie["secure"], True)
            self.assertEqual(toolbar_cookie["max-age"], 31536000)

    def test_logout(self):
        with self.settings(TOOLBAR_COOKIE_NAME="phtoolbar"):
            self.client.force_login(self.user)

            response = self.client.get("/")
            self.assertEqual(response.cookies[settings.TOOLBAR_COOKIE_NAME].key, "phtoolbar")
            self.assertEqual(response.cookies[settings.TOOLBAR_COOKIE_NAME].value, "yes")
            self.assertEqual(response.cookies[settings.TOOLBAR_COOKIE_NAME]["max-age"], 31536000)

            response = self.client.get("/logout")
            self.assertEqual(response.cookies[settings.TOOLBAR_COOKIE_NAME].key, "phtoolbar")
            self.assertEqual(response.cookies[settings.TOOLBAR_COOKIE_NAME].value, "")
            self.assertEqual(response.cookies[settings.TOOLBAR_COOKIE_NAME]["max-age"], 0)


class TestAutoProjectMiddleware(APIBaseTest):
    second_team: Team

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        # Create another team that the user does have access to
        cls.second_team = Team.objects.create(organization=cls.organization, name="Second Life")

    def setUp(self):
        super().setUp()
        # Reset back to initial team/org for each test
        self.user.current_team = self.team
        self.user.current_organization = self.organization

    def test_project_switched_when_accessing_dashboard_of_another_accessible_team(self):
        dashboard = Dashboard.objects.create(team=self.second_team)

        response_app = self.client.get(f"/dashboard/{dashboard.id}")
        response_users_api = self.client.get(f"/api/users/@me/")
        response_users_api_data = response_users_api.json()
        self.user.refresh_from_db()
        response_dashboards_api = self.client.get(f"/api/projects/@current/dashboards/{dashboard.id}/")

        self.assertEqual(response_app.status_code, 200)
        self.assertEqual(response_users_api.status_code, 200)
        self.assertEqual(response_users_api_data.get("team", {}).get("id"), self.second_team.id)
        self.assertEqual(response_dashboards_api.status_code, 200)

    def test_project_switched_when_accessing_dashboard_of_another_accessible_team_with_trailing_slash(self):
        dashboard = Dashboard.objects.create(team=self.second_team)

        response_app = self.client.get(f"/dashboard/{dashboard.id}/")
        response_users_api = self.client.get(f"/api/users/@me/")
        response_users_api_data = response_users_api.json()
        self.user.refresh_from_db()
        response_dashboards_api = self.client.get(f"/api/projects/@current/dashboards/{dashboard.id}/")

        self.assertEqual(response_app.status_code, 200)
        self.assertEqual(response_users_api.status_code, 200)
        self.assertEqual(response_users_api_data.get("team", {}).get("id"), self.second_team.id)
        self.assertEqual(response_dashboards_api.status_code, 200)

    def test_project_unchanged_when_accessing_dashboard_of_another_off_limits_team(self):
        _, _, third_team = Organization.objects.bootstrap(
            None, name="Third Party", slug="third-party", team_fields={"name": "Third Team"}
        )
        dashboard = Dashboard.objects.create(team=third_team)

        response_app = self.client.get(f"/dashboard/{dashboard.id}")
        response_users_api = self.client.get(f"/api/users/@me/")
        response_users_api_data = response_users_api.json()
        self.user.refresh_from_db()
        response_dashboards_api = self.client.get(f"/api/projects/@current/dashboards/{dashboard.id}/")

        self.assertEqual(response_app.status_code, 200)
        self.assertEqual(response_users_api.status_code, 200)
        self.assertEqual(response_users_api_data.get("team", {}).get("id"), self.team.id)  # NOT third_team
        self.assertEqual(response_dashboards_api.status_code, 404)

    def test_project_switched_when_accessing_insight_of_another_accessible_team(self):
        insight = Insight.objects.create(team=self.second_team)

        response_app = self.client.get(f"/insights/{insight.short_id}")
        response_users_api = self.client.get(f"/api/users/@me/")
        response_users_api_data = response_users_api.json()
        self.user.refresh_from_db()
        response_insights_api = self.client.get(f"/api/projects/@current/insights/{insight.id}/")

        self.assertEqual(response_app.status_code, 200)
        self.assertEqual(response_users_api.status_code, 200)
        self.assertEqual(response_users_api_data.get("team", {}).get("id"), self.second_team.id)
        self.assertEqual(response_insights_api.status_code, 200)

    def test_project_switched_when_accessing_insight_edit_mode_of_another_accessible_team(self):
        insight = Insight.objects.create(team=self.second_team)

        response_app = self.client.get(f"/insights/{insight.short_id}/edit")
        response_users_api = self.client.get(f"/api/users/@me/")
        response_users_api_data = response_users_api.json()
        self.user.refresh_from_db()
        response_insights_api = self.client.get(f"/api/projects/@current/insights/{insight.id}/")

        self.assertEqual(response_app.status_code, 200)
        self.assertEqual(response_users_api.status_code, 200)
        self.assertEqual(response_users_api_data.get("team", {}).get("id"), self.second_team.id)
        self.assertEqual(response_insights_api.status_code, 200)

    def test_project_switched_when_accessing_action_of_another_accessible_team(self):
        action = Action.objects.create(team=self.second_team)

        response_app = self.client.get(f"/action/{action.id}")
        response_users_api = self.client.get(f"/api/users/@me/")
        response_users_api_data = response_users_api.json()
        self.user.refresh_from_db()
        response_actions_api = self.client.get(f"/api/projects/@current/actions/{action.id}/")

        self.assertEqual(response_app.status_code, 200)
        self.assertEqual(response_users_api.status_code, 200)
        self.assertEqual(response_users_api_data.get("team", {}).get("id"), self.second_team.id)
        self.assertEqual(response_actions_api.status_code, 200)

    def test_project_switched_when_accessing_cohort_of_another_accessible_team(self):
        cohort = Cohort.objects.create(team=self.second_team, created_by=self.user)

        response_app = self.client.get(f"/cohorts/{cohort.id}")
        response_users_api = self.client.get(f"/api/users/@me/")
        response_users_api_data = response_users_api.json()
        self.user.refresh_from_db()
        response_cohorts_api = self.client.get(f"/api/projects/@current/cohorts/{cohort.id}/")

        self.assertEqual(response_app.status_code, 200)
        self.assertEqual(response_users_api.status_code, 200)
        self.assertEqual(response_users_api_data.get("team", {}).get("id"), self.second_team.id)
        self.assertEqual(response_cohorts_api.status_code, 200)

    def test_project_switched_when_accessing_feature_flag_of_another_accessible_team(self):
        feature_flag = FeatureFlag.objects.create(team=self.second_team, created_by=self.user)

        response_app = self.client.get(f"/feature_flags/{feature_flag.id}")
        response_users_api = self.client.get(f"/api/users/@me/")
        response_users_api_data = response_users_api.json()
        self.user.refresh_from_db()
        response_feature_flags_api = self.client.get(f"/api/projects/@current/feature_flags/{feature_flag.id}/")

        self.assertEqual(response_app.status_code, 200)
        self.assertEqual(response_users_api.status_code, 200)
        self.assertEqual(response_users_api_data.get("team", {}).get("id"), self.second_team.id)
        self.assertEqual(response_feature_flags_api.status_code, 200)
