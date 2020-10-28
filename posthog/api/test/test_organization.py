from unittest.mock import patch

from django.test import tag
from rest_framework import status

from posthog.models import Dashboard, Organization, OrganizationMembership, Team, User

from .base import APIBaseTest


class TestOrganizationAPI(APIBaseTest):
    def test_no_create_organization_without_license_selfhosted(self):
        with self.settings(MULTI_TENANCY=False):
            response = self.client.post("/api/organizations/", {"name": "Test"})
            self.assertEqual(response.status_code, 403)
            self.assertEqual(
                response.data,
                {
                    "attr": None,
                    "code": "permission_denied",
                    "detail": "You must upgrade your PostHog plan to be able to create and manage multiple organizations.",
                    "type": "authentication_error",
                },
            )
            self.assertEqual(Organization.objects.count(), 1)
            response = self.client.post("/api/organizations/", {"name": "Test"})
            self.assertEqual(Organization.objects.count(), 1)

    def test_rename_organization_without_license_if_admin(self):
        response = self.client.patch(f"/api/organizations/{self.organization.id}", {"name": "QWERTY"})
        self.assertEqual(response.status_code, 200)
        self.organization.refresh_from_db()
        self.assertEqual(self.organization.name, "QWERTY")
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        response = self.client.patch(f"/api/organizations/{self.organization.id}", {"name": "ASDFG"})
        self.assertEqual(response.status_code, 403)


class TestSignup(APIBaseTest):
    CONFIG_USER_EMAIL = None

    @tag("skip_on_multitenancy")
    @patch("posthog.api.team.settings.EE_AVAILABLE", False)
    @patch("posthog.api.team.posthoganalytics.identify")
    @patch("posthog.api.team.posthoganalytics.capture")
    def test_api_sign_up(self, mock_capture, mock_identify):
        response = self.client.post(
            "/api/signup/",
            {
                "first_name": "John",
                "email": "hedgehog@posthog.com",
                "password": "notsecure",
                "company_name": "Hedgehogs United, LLC",
                "email_opt_in": False,
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        user: User = User.objects.order_by("-pk")[0]
        team: Team = user.team
        organization: Organization = user.organization
        self.assertEqual(
            response.data,
            {"id": user.pk, "distinct_id": user.distinct_id, "first_name": "John", "email": "hedgehog@posthog.com"},
        )

        # Assert that the user was properly created
        self.assertEqual(user.first_name, "John")
        self.assertEqual(user.email, "hedgehog@posthog.com")
        self.assertEqual(user.email_opt_in, False)

        # Assert that the team was properly created
        self.assertEqual(team.name, "Default Project")

        # Assert that the org was properly created
        self.assertEqual(organization.name, "Hedgehogs United, LLC")

        # Assert that the sign up event & identify calls were sent to PostHog analytics
        mock_capture.assert_called_once_with(
            user.distinct_id, "user signed up", properties={"is_first_user": True, "is_organization_first_user": True},
        )

        mock_identify.assert_called_once_with(
            user.distinct_id, properties={"email": "hedgehog@posthog.com", "realm": "hosted", "ee_available": False},
        )

        # Assert that the user is logged in
        response = self.client.get("/api/user/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["email"], "hedgehog@posthog.com")

        # Assert that the password was correctly saved
        self.assertTrue(user.check_password("notsecure"))

    @tag("skip_on_multitenancy")
    @patch("posthog.api.team.posthoganalytics.capture")
    def test_sign_up_minimum_attrs(self, mock_capture):
        response = self.client.post(
            "/api/signup/", {"first_name": "Jane", "email": "hedgehog2@posthog.com", "password": "notsecure"},
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        user: User = User.objects.order_by("-pk").get()
        organization: Organization = user.organization
        self.assertEqual(
            response.data,
            {"id": user.pk, "distinct_id": user.distinct_id, "first_name": "Jane", "email": "hedgehog2@posthog.com",},
        )

        # Assert that the user was properly created
        self.assertEqual(user.first_name, "Jane")
        self.assertEqual(user.email, "hedgehog2@posthog.com")
        self.assertEqual(user.email_opt_in, True)  # Defaults to True
        self.assertEqual(organization.name, "Jane")

        # Assert that the sign up event & identify calls were sent to PostHog analytics
        mock_capture.assert_called_once_with(
            user.distinct_id, "user signed up", properties={"is_first_user": True, "is_organization_first_user": True},
        )

        # Assert that the user is logged in
        response = self.client.get("/api/user/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["email"], "hedgehog2@posthog.com")

        # Assert that the password was correctly saved
        self.assertTrue(user.check_password("notsecure"))

    def test_cant_sign_up_without_required_attributes(self):
        count: int = User.objects.count()
        team_count: int = Team.objects.count()

        required_attributes = [
            "first_name",
            "email",
            "password",
        ]

        for attribute in required_attributes:
            body = {
                "first_name": "Jane",
                "email": "invalid@posthog.com",
                "password": "notsecure",
            }
            body.pop(attribute)

            # Make sure the endpoint works with and without the trailing slash
            response = self.client.post("/api/signup", body)
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
            self.assertEqual(
                response.data,
                {
                    "type": "validation_error",
                    "code": "required",
                    "detail": "This field is required.",
                    "attr": attribute,
                },
            )

        self.assertEqual(User.objects.count(), count)
        self.assertEqual(Team.objects.count(), team_count)

    def test_cant_sign_up_with_short_password(self):
        count: int = User.objects.count()
        team_count: int = Team.objects.count()

        response = self.client.post(
            "/api/signup/", {"first_name": "Jane", "email": "failed@posthog.com", "password": "123"},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data,
            {
                "type": "validation_error",
                "code": "password_too_short",
                "detail": "This password is too short. It must contain at least 8 characters.",
                "attr": "password",
            },
        )

        self.assertEqual(User.objects.count(), count)
        self.assertEqual(Team.objects.count(), team_count)

    @patch("posthog.models.team.posthoganalytics.feature_enabled")
    def test_default_dashboard_is_created_on_signup(self, mock_feature_enabled):
        """
        Tests that the default web app dashboard is created on signup.
        Note: This feature is currently behind a feature flag.
        """

        mock_feature_enabled.return_value = True

        response = self.client.post(
            "/api/signup/", {"first_name": "Jane", "email": "hedgehog75@posthog.com", "password": "notsecure"},
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        user: User = User.objects.order_by("-pk").get()

        mock_feature_enabled.assert_called_with("1694-dashboards", user.distinct_id)

        self.assertEqual(
            response.data,
            {"id": user.pk, "distinct_id": user.distinct_id, "first_name": "Jane", "email": "hedgehog75@posthog.com"},
        )

        dashboard: Dashboard = Dashboard.objects.last()  # type: ignore
        self.assertEqual(dashboard.team, user.team)
        self.assertEqual(dashboard.items.count(), 7)
        self.assertEqual(dashboard.name, "My App Dashboard")
        self.assertEqual(
            dashboard.items.all()[0].description, "Shows the number of unique users that use your app everyday."
        )
