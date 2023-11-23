import json
from urllib.parse import quote

from django.test.client import Client
from rest_framework import status

from posthog.models import Action, Cohort, Dashboard, FeatureFlag, Insight
from posthog.models.organization import Organization
from posthog.models.team import Team
from posthog.settings import SITE_URL
from posthog.test.base import APIBaseTest, override_settings


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

            response = self.client.get("/batch/", REMOTE_ADDR="10.0.0.1")

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
            ALLOWED_IP_BLOCKS=["192.168.0.0/31", "127.0.0.0/25,128.0.0.1"],
            USE_X_FORWARDED_HOST=True,
        ):
            with self.settings(TRUSTED_PROXIES="10.0.0.1"):
                response = self.client.get(
                    "/",
                    REMOTE_ADDR="10.0.0.1",
                    HTTP_X_FORWARDED_FOR="192.168.0.1,10.0.0.1",
                )
                self.assertNotIn(b"IP is not allowed", response.content)

    def test_attempt_spoofing(self):
        with self.settings(
            ALLOWED_IP_BLOCKS=["192.168.0.0/31", "127.0.0.0/25,128.0.0.1"],
            USE_X_FORWARDED_HOST=True,
        ):
            with self.settings(TRUSTED_PROXIES="10.0.0.1"):
                response = self.client.get(
                    "/",
                    REMOTE_ADDR="10.0.0.1",
                    HTTP_X_FORWARDED_FOR="192.168.0.1,10.0.0.2",
                )
                self.assertIn(b"IP is not allowed", response.content)

    def test_trust_all_proxies(self):
        with self.settings(
            ALLOWED_IP_BLOCKS=["192.168.0.0/31", "127.0.0.0/25,128.0.0.1"],
            USE_X_FORWARDED_HOST=True,
        ):
            with self.settings(TRUST_ALL_PROXIES=True):
                response = self.client.get(
                    "/",
                    REMOTE_ADDR="10.0.0.1",
                    HTTP_X_FORWARDED_FOR="192.168.0.1,10.0.0.1",
                )
                self.assertNotIn(b"IP is not allowed", response.content)


class TestAutoProjectMiddleware(APIBaseTest):
    # How many queries are made in the base app
    # On Cloud there's an additional multi_tenancy_organizationbilling query
    second_team: Team
    base_app_num_queries: int

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.base_app_num_queries = 41
        # Create another team that the user does have access to
        cls.second_team = Team.objects.create(organization=cls.organization, name="Second Life")

    def setUp(self):
        super().setUp()
        # Reset back to initial team/org for each test
        self.user.current_team = self.team
        self.user.current_organization = self.organization

    @override_settings(PERSON_ON_EVENTS_V2_OVERRIDE=False)
    def test_project_switched_when_accessing_dashboard_of_another_accessible_team(self):
        dashboard = Dashboard.objects.create(team=self.second_team)

        with self.assertNumQueries(self.base_app_num_queries + 4):  # AutoProjectMiddleware adds 4 queries
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
            None,
            name="Third Party",
            slug="third-party",
            team_fields={"name": "Third Team"},
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

    @override_settings(PERSON_ON_EVENTS_V2_OVERRIDE=False)
    def test_project_unchanged_when_accessing_dashboards_list(self):
        with self.assertNumQueries(self.base_app_num_queries):  # No AutoProjectMiddleware queries
            response_app = self.client.get(f"/dashboard")
        response_users_api = self.client.get(f"/api/users/@me/")
        response_users_api_data = response_users_api.json()
        self.user.refresh_from_db()

        self.assertEqual(response_app.status_code, 200)
        self.assertEqual(response_users_api.status_code, 200)
        self.assertEqual(response_users_api_data.get("team", {}).get("id"), self.team.id)  # NOT third_team

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

    @override_settings(PERSON_ON_EVENTS_V2_OVERRIDE=False)
    def test_project_switched_when_accessing_feature_flag_of_another_accessible_team(self):
        feature_flag = FeatureFlag.objects.create(team=self.second_team, created_by=self.user)

        with self.assertNumQueries(self.base_app_num_queries + 4):
            response_app = self.client.get(f"/feature_flags/{feature_flag.id}")
        response_users_api = self.client.get(f"/api/users/@me/")
        response_users_api_data = response_users_api.json()
        self.user.refresh_from_db()
        response_feature_flags_api = self.client.get(f"/api/projects/@current/feature_flags/{feature_flag.id}/")

        self.assertEqual(response_app.status_code, 200)
        self.assertEqual(response_users_api.status_code, 200)
        self.assertEqual(response_users_api_data.get("team", {}).get("id"), self.second_team.id)
        self.assertEqual(response_feature_flags_api.status_code, 200)

    @override_settings(PERSON_ON_EVENTS_V2_OVERRIDE=False)
    def test_project_unchanged_when_creating_feature_flag(self):
        with self.assertNumQueries(self.base_app_num_queries):
            response_app = self.client.get(f"/feature_flags/new")
        response_users_api = self.client.get(f"/api/users/@me/")
        response_users_api_data = response_users_api.json()
        self.user.refresh_from_db()

        self.assertEqual(response_app.status_code, 200)
        self.assertEqual(response_users_api.status_code, 200)
        self.assertEqual(response_users_api_data.get("team", {}).get("id"), self.team.id)


class TestPostHogTokenCookieMiddleware(APIBaseTest):
    initial_cloud_mode = True
    CONFIG_AUTO_LOGIN = False

    def test_logged_out_client(self):
        self.client.logout()
        response = self.client.get("/")
        self.assertEqual(0, len(response.cookies))

    def test_logged_in_client(self):
        self.client.force_login(self.user)
        response = self.client.get("/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        ph_project_token_cookie = response.cookies["ph_current_project_token"]
        self.assertEqual(ph_project_token_cookie.key, "ph_current_project_token")
        self.assertEqual(ph_project_token_cookie.value, self.team.api_token)
        self.assertEqual(ph_project_token_cookie["path"], "/")
        self.assertEqual(ph_project_token_cookie["samesite"], "Strict")
        self.assertEqual(ph_project_token_cookie["httponly"], "")
        self.assertEqual(ph_project_token_cookie["domain"], "posthog.com")
        self.assertEqual(ph_project_token_cookie["comment"], "")
        self.assertEqual(ph_project_token_cookie["secure"], True)
        self.assertEqual(ph_project_token_cookie["max-age"], 31536000)

        ph_project_name_cookie = response.cookies["ph_current_project_name"]
        self.assertEqual(ph_project_name_cookie.key, "ph_current_project_name")
        self.assertEqual(ph_project_name_cookie.value, self.team.name)
        self.assertEqual(ph_project_name_cookie["path"], "/")
        self.assertEqual(ph_project_name_cookie["samesite"], "Strict")
        self.assertEqual(ph_project_name_cookie["httponly"], "")
        self.assertEqual(ph_project_name_cookie["domain"], "posthog.com")
        self.assertEqual(ph_project_name_cookie["comment"], "")
        self.assertEqual(ph_project_name_cookie["secure"], True)
        self.assertEqual(ph_project_name_cookie["max-age"], 31536000)

        ph_instance_cookie = response.cookies["ph_current_instance"]
        self.assertEqual(ph_instance_cookie.key, "ph_current_instance")
        self.assertEqual(ph_instance_cookie.value, SITE_URL)
        self.assertEqual(ph_instance_cookie["path"], "/")
        self.assertEqual(ph_instance_cookie["samesite"], "Strict")
        self.assertEqual(ph_instance_cookie["httponly"], "")
        self.assertEqual(ph_instance_cookie["domain"], "posthog.com")
        self.assertEqual(ph_instance_cookie["comment"], "")
        self.assertEqual(ph_instance_cookie["secure"], True)
        self.assertEqual(ph_instance_cookie["max-age"], 31536000)

    def test_ph_project_cookies_are_not_set_on_capture_or_api_endpoints(self):
        self.client.logout()

        data = {
            "event": "user did custom action",
            "properties": {"distinct_id": 2, "token": self.team.api_token},
        }

        response = self.client.get(
            "/e/?data=%s" % quote(json.dumps(data)),
            HTTP_ORIGIN="https://localhost",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(0, len(response.cookies))  # no cookies are set

        django_client = Client()
        response = django_client.post(
            "/track/",
            {
                "data": json.dumps(
                    [
                        {
                            "event": "beep",
                            "properties": {
                                "distinct_id": "eeee",
                                "token": self.team.api_token,
                            },
                        }
                    ]
                ),
                "api_key": self.team.api_token,
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(0, len(response.cookies))  # no cookies are set

        self.client.force_login(self.user)

        response = self.client.get("/api/users/@me/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(0, len(response.cookies))  # no cookies are set

        response = self.client.patch("/api/users/@me/", {"first_name": "Alice"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(0, len(response.cookies))  # no cookies are set

    def test_logout(self):
        self.client.force_login(self.user)
        response = self.client.get("/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.assertEqual(response.cookies["ph_current_project_token"].key, "ph_current_project_token")
        self.assertEqual(response.cookies["ph_current_project_token"].value, self.team.api_token)
        self.assertEqual(response.cookies["ph_current_project_token"]["max-age"], 31536000)

        self.assertEqual(response.cookies["ph_current_project_name"].key, "ph_current_project_name")
        self.assertEqual(response.cookies["ph_current_project_name"].value, self.team.name)
        self.assertEqual(response.cookies["ph_current_project_name"]["max-age"], 31536000)

        self.assertEqual(response.cookies["ph_current_instance"].key, "ph_current_instance")
        self.assertEqual(response.cookies["ph_current_instance"].value, SITE_URL)
        self.assertEqual(response.cookies["ph_current_instance"]["max-age"], 31536000)

        response = self.client.get("/logout")

        # Check that the local cookies will be removed by having 'expires' in the past
        self.assertTrue(response.cookies["ph_current_project_token"]["expires"] == "Thu, 01 Jan 1970 00:00:00 GMT")
        self.assertTrue(response.cookies["ph_current_project_name"]["expires"] == "Thu, 01 Jan 1970 00:00:00 GMT")
        # We don't want to remove the ph_current_instance cookie
        self.assertNotIn("ph_current_instance", response.cookies)

        # Request a page after logging out
        response = self.client.get("/")

        # Check if the cookies are not present in the response
        self.assertNotIn("ph_current_project_token", response.cookies)
        self.assertNotIn("ph_current_project_name", response.cookies)
