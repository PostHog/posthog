import datetime
import uuid
from typing import Dict, Optional, cast
from unittest import mock
from unittest.mock import ANY, patch
from zoneinfo import ZoneInfo

import pytest
from django.core import mail
from django.urls.base import reverse
from django.utils import timezone
from rest_framework import status

from posthog.cloud_utils import TEST_clear_instance_license_cache
from posthog.constants import AvailableFeature
from posthog.models import Dashboard, Organization, Team, User
from posthog.models.instance_setting import override_instance_config
from posthog.models.organization import OrganizationInvite, OrganizationMembership
from posthog.models.organization_domain import OrganizationDomain
from posthog.test.base import APIBaseTest
from posthog.utils import get_instance_realm

MOCK_GITLAB_SSO_RESPONSE = {
    "access_token": "123",
    "email": "testemail@posthog.com",
    "name": "John Doe",
}


class TestSignupAPI(APIBaseTest):
    @classmethod
    def setUpTestData(cls):
        # Do not set up any test data
        TEST_clear_instance_license_cache()

    @pytest.mark.skip_on_multitenancy
    @patch("posthoganalytics.capture")
    def test_api_sign_up(self, mock_capture):
        # Ensure the internal system metrics org doesn't prevent org-creation
        Organization.objects.create(name="PostHog Internal Metrics", for_internal_metrics=True)

        response = self.client.post(
            "/api/signup/",
            {
                "first_name": "John",
                "email": "hedgehog@posthog.com",
                "password": "notsecure",
                "organization_name": "Hedgehogs United, LLC",
                "role_at_organization": "product",
                "email_opt_in": False,
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        user = cast(User, User.objects.order_by("-pk")[0])
        team = cast(Team, user.team)
        organization = cast(Organization, user.organization)

        self.assertEqual(
            response.json(),
            {
                "id": user.pk,
                "uuid": str(user.uuid),
                "distinct_id": user.distinct_id,
                "last_name": "",
                "first_name": "John",
                "email": "hedgehog@posthog.com",
                "redirect_url": "/",
                "is_email_verified": False,
            },
        )

        # Assert that the user was properly created
        self.assertEqual(user.first_name, "John")
        self.assertEqual(user.email, "hedgehog@posthog.com")
        self.assertFalse(user.email_opt_in)
        self.assertTrue(user.is_staff)  # True because this is the first user in the instance
        self.assertFalse(user.is_email_verified)

        # Assert that the team was properly created
        self.assertEqual(team.name, "Default Project")

        # Assert that the org was properly created
        self.assertEqual(organization.name, "Hedgehogs United, LLC")

        # Assert that the sign up event & identify calls were sent to PostHog analytics
        mock_capture.assert_called_once()
        self.assertEqual(user.distinct_id, mock_capture.call_args.args[0])
        self.assertEqual("user signed up", mock_capture.call_args.args[1])
        # Assert that key properties were set properly
        event_props = mock_capture.call_args.kwargs["properties"]
        self.assertEqual(event_props["is_first_user"], True)
        self.assertEqual(event_props["is_organization_first_user"], True)
        self.assertEqual(event_props["new_onboarding_enabled"], False)
        self.assertEqual(event_props["signup_backend_processor"], "OrganizationSignupSerializer")
        self.assertEqual(event_props["signup_social_provider"], "")
        self.assertEqual(event_props["realm"], get_instance_realm())

        # Assert that the user is logged in
        response = self.client.get("/api/users/@me/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["email"], "hedgehog@posthog.com")

        # Assert that the password was correctly saved
        self.assertTrue(user.check_password("notsecure"))

    @pytest.mark.skip_on_multitenancy
    def test_signup_disallowed_on_email_collision(self):
        # Create a user with the same email
        User.objects.create(email="fake@posthog.com", first_name="Jane")

        response = self.client.post(
            "/api/signup/",
            {
                "first_name": "John",
                "email": "fake@posthog.com",
                "password": "notsecure",
            },
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json(),
            self.validation_error_response(
                "There is already an account with this email address.",
                code="unique",
                attr="email",
            ),
        )
        self.assertEqual(User.objects.count(), 1)

    @pytest.mark.skip_on_multitenancy
    def test_signup_disallowed_on_self_hosted_by_default(self):
        with self.is_cloud(False):
            response = self.client.post(
                "/api/signup/",
                {
                    "first_name": "Jane",
                    "email": "hedgehog2@posthog.com",
                    "password": "notsecure",
                },
            )
            self.assertEqual(response.status_code, status.HTTP_201_CREATED)
            response = self.client.post(
                "/api/signup/",
                {
                    "first_name": "Jane",
                    "email": "hedgehog2@posthog.com",
                    "password": "notsecure",
                },
            )
            self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
            self.assertEqual(
                response.json(),
                {
                    "attr": None,
                    "code": "permission_denied",
                    "detail": "New organizations cannot be created in this instance. Contact your administrator if you"
                    " think this is a mistake.",
                    "type": "authentication_error",
                },
            )

    @pytest.mark.ee
    def test_signup_allowed_on_self_hosted_with_env_var(self):
        try:
            from ee.models.license import License, LicenseManager
        except ImportError:
            pass
        else:
            super(LicenseManager, cast(LicenseManager, License.objects)).create(
                key="key_123",
                plan="enterprise",
                valid_until=timezone.datetime(2038, 1, 19, 3, 14, 7),
            )

            Organization.objects.create(name="name")
            User.objects.create(first_name="name", email="email@posthog.com")
            count = Organization.objects.count()
            with self.is_cloud(False):
                with self.settings(MULTI_ORG_ENABLED=True):
                    response = self.client.post(
                        "/api/signup/",
                        {
                            "first_name": "Jane",
                            "email": "hedgehog4@posthog.com",
                            "password": "notsecure",
                        },
                    )
            self.assertEqual(response.status_code, status.HTTP_201_CREATED)
            self.assertEqual(response.json()["email"], "hedgehog4@posthog.com")
            self.assertEqual(Organization.objects.count(), count + 1)

    @pytest.mark.skip_on_multitenancy
    @patch("posthoganalytics.capture")
    def test_signup_minimum_attrs(self, mock_capture):
        response = self.client.post(
            "/api/signup/",
            {
                "first_name": "Jane",
                "email": "hedgehog2@posthog.com",
                "password": "notsecure",
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        user = cast(User, User.objects.order_by("-pk").get())
        organization = cast(Organization, user.organization)
        self.assertEqual(
            response.json(),
            {
                "id": user.pk,
                "uuid": str(user.uuid),
                "distinct_id": user.distinct_id,
                "last_name": "",
                "first_name": "Jane",
                "email": "hedgehog2@posthog.com",
                "redirect_url": "/",
                "is_email_verified": False,
            },
        )

        # Assert that the user & org were properly created
        self.assertEqual(user.first_name, "Jane")
        self.assertEqual(user.email, "hedgehog2@posthog.com")
        self.assertTrue(user.email_opt_in)  # Defaults to True
        self.assertEqual(organization.name, "Jane")
        self.assertTrue(user.is_staff)  # True because this is the first user in the instance

        # Assert that the sign up event & identify calls were sent to PostHog analytics
        mock_capture.assert_called_once()
        self.assertEqual(user.distinct_id, mock_capture.call_args.args[0])
        self.assertEqual("user signed up", mock_capture.call_args.args[1])
        # Assert that key properties were set properly
        event_props = mock_capture.call_args.kwargs["properties"]
        self.assertEqual(event_props["is_first_user"], True)
        self.assertEqual(event_props["is_organization_first_user"], True)
        self.assertEqual(event_props["new_onboarding_enabled"], False)
        self.assertEqual(event_props["signup_backend_processor"], "OrganizationSignupSerializer")
        self.assertEqual(event_props["signup_social_provider"], "")
        self.assertEqual(event_props["realm"], get_instance_realm())

        # Assert that the user is logged in
        response = self.client.get("/api/users/@me/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["email"], "hedgehog2@posthog.com")

        # Assert that the password was correctly saved
        self.assertTrue(user.check_password("notsecure"))

    def test_cant_sign_up_without_required_attributes(self):
        count: int = User.objects.count()
        team_count: int = Team.objects.count()
        org_count: int = Organization.objects.count()

        required_attributes = ["first_name", "email", "password"]

        for attribute in required_attributes:
            body = {
                "first_name": "Jane",
                "email": "invalid@posthog.com",
                "password": "notsecure",
            }
            body.pop(attribute)

            # Make sure the endpoint works with and without the trailing slash
            response = self.client.post("/api/signup", body)
            self.assertEqual(
                response.status_code,
                status.HTTP_400_BAD_REQUEST,
                f"{attribute} is required",
            )
            self.assertEqual(
                response.json(),
                {
                    "type": "validation_error",
                    "code": "required",
                    "detail": "This field is required.",
                    "attr": attribute,
                },
                f"{attribute} is required",
            )

        self.assertEqual(User.objects.count(), count)
        self.assertEqual(Team.objects.count(), team_count)
        self.assertEqual(Organization.objects.count(), org_count)

    def test_cant_sign_up_with_required_attributes_null(self):
        count: int = User.objects.count()
        team_count: int = Team.objects.count()
        org_count: int = Organization.objects.count()

        required_attributes = ["first_name", "email"]

        for attribute in required_attributes:
            body: Dict[str, Optional[str]] = {
                "first_name": "Jane",
                "email": "invalid@posthog.com",
                "password": "notsecure",
            }
            body[attribute] = None

            response = self.client.post("/api/signup/", body)
            self.assertEqual(
                response.status_code,
                status.HTTP_400_BAD_REQUEST,
                f"{attribute} may not be null",
            )
            self.assertEqual(
                response.json(),
                {
                    "type": "validation_error",
                    "code": "null",
                    "detail": "This field may not be null.",
                    "attr": attribute,
                },
                f"{attribute} may not be null",
            )

        self.assertEqual(User.objects.count(), count)
        self.assertEqual(Team.objects.count(), team_count)
        self.assertEqual(Organization.objects.count(), org_count)

    def test_cant_sign_up_with_short_password(self):
        count: int = User.objects.count()
        team_count: int = Team.objects.count()

        response = self.client.post(
            "/api/signup/",
            {"first_name": "Jane", "email": "failed@posthog.com", "password": "123"},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json(),
            {
                "type": "validation_error",
                "code": "password_too_short",
                "detail": "This password is too short. It must contain at least 8 characters.",
                "attr": "password",
            },
        )

        self.assertEqual(User.objects.count(), count)
        self.assertEqual(Team.objects.count(), team_count)

    def test_default_dashboard_is_created_on_signup(self):
        """
        Tests that the default web app dashboard is created on signup.
        Note: This feature is currently behind a feature flag.
        """

        response = self.client.post(
            "/api/signup/",
            {
                "first_name": "Jane",
                "email": "hedgehog75@posthog.com",
                "password": "notsecure",
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        user: User = User.objects.order_by("-pk").get()

        self.assertEqual(
            response.json(),
            {
                "id": user.pk,
                "uuid": str(user.uuid),
                "distinct_id": user.distinct_id,
                "last_name": "",
                "first_name": "Jane",
                "email": "hedgehog75@posthog.com",
                "redirect_url": "/",
                "is_email_verified": False,
            },
        )

        dashboard: Dashboard = Dashboard.objects.first()  # type: ignore
        self.assertEqual(dashboard.team, user.team)
        self.assertEqual(dashboard.tiles.count(), 6)
        self.assertEqual(dashboard.name, "My App Dashboard")
        self.assertEqual(Dashboard.objects.filter(team=user.team).count(), 1)

    @mock.patch("social_core.backends.base.BaseAuth.request")
    @pytest.mark.ee
    def test_api_can_use_social_login_to_create_organization_if_enabled(self, mock_request):
        Organization.objects.create(name="Test org")

        try:
            from ee.models.license import License, LicenseManager
        except ImportError:
            pass
        else:
            super(LicenseManager, cast(LicenseManager, License.objects)).create(
                key="key_123",
                plan="enterprise",
                valid_until=timezone.datetime(2038, 1, 19, 3, 14, 7),
            )

            with self.settings(
                SOCIAL_AUTH_GITLAB_KEY="gitlab_123",
                SOCIAL_AUTH_GITLAB_SECRET="gitlab_secret",
            ):
                response = self.client.get(reverse("social:begin", kwargs={"backend": "gitlab"}))
            self.assertEqual(response.status_code, status.HTTP_302_FOUND)

            url = reverse("social:complete", kwargs={"backend": "gitlab"})
            url += f"?code=2&state={response.client.session['gitlab_state']}"
            mock_request.return_value.json.return_value = MOCK_GITLAB_SSO_RESPONSE

            with self.settings(MULTI_ORG_ENABLED=True):
                response = self.client.get(url, follow=True)
            self.assertEqual(response.status_code, status.HTTP_200_OK)  # because `follow=True`
            self.assertRedirects(
                response,
                "/organization/confirm-creation?organization_name=&first_name=John%20Doe&email=testemail%40posthog.com",
            )  # page where user will create a new org

    @mock.patch("social_core.backends.base.BaseAuth.request")
    @pytest.mark.ee
    @pytest.mark.skip_on_multitenancy
    def test_api_cannot_use_social_login_to_create_organization_if_disabled(self, mock_request):
        Organization.objects.create(name="Test org")
        # Even with a valid license, because `MULTI_ORG_ENABLED` is not enabled, no new organizations will be allowed.
        try:
            from ee.models.license import License, LicenseManager
        except ImportError:
            pass
        else:
            super(LicenseManager, cast(LicenseManager, License.objects)).create(
                key="key_123",
                plan="enterprise",
                valid_until=timezone.datetime(2038, 1, 19, 3, 14, 7),
            )

            with self.settings(
                SOCIAL_AUTH_GITLAB_KEY="gitlab_123",
                SOCIAL_AUTH_GITLAB_SECRET="gitlab_secret",
            ):
                response = self.client.get(reverse("social:begin", kwargs={"backend": "gitlab"}))
            self.assertEqual(response.status_code, status.HTTP_302_FOUND)

            url = reverse("social:complete", kwargs={"backend": "gitlab"})
            url += f"?code=2&state={response.client.session['gitlab_state']}"
            mock_request.return_value.json.return_value = MOCK_GITLAB_SSO_RESPONSE

            response = self.client.get(url, follow=True)
            self.assertEqual(response.status_code, status.HTTP_200_OK)  # because `follow=True`
            self.assertRedirects(
                response, "/login?error_code=no_new_organizations"
            )  # show the user an error; operation not permitted

    @mock.patch("social_core.backends.base.BaseAuth.request")
    @pytest.mark.ee
    def test_api_social_login_to_create_organization(self, mock_request):
        with self.settings(
            SOCIAL_AUTH_GITHUB_KEY="github_123",
            SOCIAL_AUTH_GITHUB_SECRET="github_secret",
        ):
            response = self.client.get(reverse("social:begin", kwargs={"backend": "github"}))
        self.assertEqual(response.status_code, status.HTTP_302_FOUND)

        session = self.client.session
        session.update({"organization_name": "HogFlix"})
        session.save()

        url = reverse("social:complete", kwargs={"backend": "github"})
        url += f"?code=2&state={response.client.session['github_state']}"
        mock_request.return_value.json.return_value = MOCK_GITLAB_SSO_RESPONSE

        response = self.client.get(url, follow=True)
        self.assertEqual(response.status_code, status.HTTP_200_OK)  # because `follow=True`
        self.assertRedirects(
            response,
            "/organization/confirm-creation?organization_name=HogFlix&first_name=John%20Doe&email=testemail%40posthog.com",
        )  # page where user will create a new org

    @mock.patch("social_core.backends.base.BaseAuth.request")
    @mock.patch("posthog.api.authentication.get_instance_available_sso_providers")
    @pytest.mark.skip_on_multitenancy
    def test_api_social_login_cannot_create_second_organization(self, mock_sso_providers, mock_request):
        mock_sso_providers.return_value = {"gitlab": True}
        Organization.objects.create(name="Test org")
        response = self.client.get(reverse("social:begin", kwargs={"backend": "gitlab"}))
        self.assertEqual(response.status_code, status.HTTP_302_FOUND)
        self.assertNotIn("/login?error_code", response.headers["Location"])

        url = reverse("social:complete", kwargs={"backend": "gitlab"})
        url += f"?code=2&state={response.client.session['gitlab_state']}"
        mock_request.return_value.json.return_value = MOCK_GITLAB_SSO_RESPONSE

        response = self.client.get(url, follow=True)
        self.assertEqual(response.status_code, status.HTTP_200_OK)  # because `follow=True`
        self.assertRedirects(
            response, "/login?error_code=no_new_organizations"
        )  # show the user an error; operation not permitted

    def run_test_for_allowed_domain(self, mock_sso_providers, mock_request, mock_capture):
        # Make sure Google Auth is valid for this test instance
        mock_sso_providers.return_value = {"google-oauth2": True}

        new_org = Organization.objects.create(name="Hogflix Movies")
        OrganizationDomain.objects.create(
            domain="hogflix.posthog.com",
            verified_at=timezone.now(),
            jit_provisioning_enabled=True,
            organization=new_org,
        )
        new_project = Team.objects.create(organization=new_org, name="My First Project")
        user_count = User.objects.count()
        response = self.client.get(reverse("social:begin", kwargs={"backend": "google-oauth2"}))
        self.assertEqual(response.status_code, status.HTTP_302_FOUND)

        url = reverse("social:complete", kwargs={"backend": "google-oauth2"})
        url += f"?code=2&state={response.client.session['google-oauth2_state']}"
        mock_request.return_value.json.return_value = {
            "access_token": "123",
            "email": "jane@hogflix.posthog.com",
        }

        response = self.client.get(url, follow=True)
        self.assertEqual(response.status_code, status.HTTP_200_OK)  # because `follow=True`
        self.assertRedirects(response, "/")

        self.assertEqual(User.objects.count(), user_count + 1)
        user = cast(User, User.objects.last())
        self.assertEqual(user.email, "jane@hogflix.posthog.com")
        self.assertFalse(user.is_staff)  # Not first user in the instance
        self.assertEqual(user.organization, new_org)
        self.assertEqual(user.team, new_project)
        self.assertEqual(user.organization_memberships.count(), 1)
        self.assertEqual(
            cast(OrganizationMembership, user.organization_memberships.first()).level,
            OrganizationMembership.Level.MEMBER,
        )
        self.assertFalse(mock_capture.call_args.kwargs["properties"]["is_organization_first_user"])

    @patch("posthoganalytics.capture")
    @mock.patch("social_core.backends.base.BaseAuth.request")
    @mock.patch("posthog.api.authentication.get_instance_available_sso_providers")
    @mock.patch("posthog.tasks.user_identify.identify_task")
    @pytest.mark.ee
    def test_social_signup_with_allowed_domain_on_self_hosted(
        self, mock_identify, mock_sso_providers, mock_request, mock_capture
    ):
        self.run_test_for_allowed_domain(mock_sso_providers, mock_request, mock_capture)

    @patch("posthoganalytics.capture")
    @mock.patch("ee.billing.billing_manager.BillingManager.update_billing_distinct_ids")
    @mock.patch("ee.billing.billing_manager.BillingManager.update_billing_customer_email")
    @mock.patch("social_core.backends.base.BaseAuth.request")
    @mock.patch("posthog.api.authentication.get_instance_available_sso_providers")
    @mock.patch("posthog.tasks.user_identify.identify_task")
    @pytest.mark.ee
    def test_social_signup_with_allowed_domain_on_cloud(
        self,
        mock_identify,
        mock_sso_providers,
        mock_request,
        mock_update_distinct_ids,
        mock_update_billing_customer_email,
        mock_capture,
    ):
        with self.is_cloud(True):
            self.run_test_for_allowed_domain(mock_sso_providers, mock_request, mock_capture)
        assert mock_update_distinct_ids.called_once()
        assert mock_update_billing_customer_email.called_once()

    @mock.patch("social_core.backends.base.BaseAuth.request")
    @mock.patch("posthog.api.authentication.get_instance_available_sso_providers")
    @pytest.mark.ee
    def test_social_signup_with_allowed_domain_on_cloud_reverse(self, mock_sso_providers, mock_request):
        with self.is_cloud(True):
            # user already exists
            User.objects.create(email="jane@hogflix.posthog.com", distinct_id=str(uuid.uuid4()))

            # Make sure Google Auth is valid for this test instance
            mock_sso_providers.return_value = {"google-oauth2": True}

            new_org = Organization.objects.create(name="Hogflix Movies")
            OrganizationDomain.objects.create(
                domain="hogflix.posthog.com",
                verified_at=timezone.now(),
                jit_provisioning_enabled=True,
                organization=new_org,
            )
            new_project = Team.objects.create(organization=new_org, name="My First Project")
            user_count = User.objects.count()
            response = self.client.get(reverse("social:begin", kwargs={"backend": "google-oauth2"}))
            self.assertEqual(response.status_code, status.HTTP_302_FOUND)

            url = reverse("social:complete", kwargs={"backend": "google-oauth2"})
            url += f"?code=2&state={response.client.session['google-oauth2_state']}"
            mock_request.return_value.json.return_value = {
                "access_token": "123",
                "email": "jane@hogflix.posthog.com",
            }

            response = self.client.get(url, follow=True)
            self.assertEqual(response.status_code, status.HTTP_200_OK)  # because `follow=True`
            self.assertRedirects(response, "/")

            self.assertEqual(User.objects.count(), user_count)  # should remain the same
            user = cast(User, User.objects.last())
            self.assertEqual(user.email, "jane@hogflix.posthog.com")
            self.assertFalse(user.is_staff)  # Not first user in the instance
            self.assertEqual(user.organization, new_org)
            self.assertEqual(user.team, new_project)
            self.assertEqual(user.organization_memberships.count(), 1)
            self.assertEqual(
                cast(OrganizationMembership, user.organization_memberships.first()).level,
                OrganizationMembership.Level.MEMBER,
            )

    @mock.patch("social_core.backends.base.BaseAuth.request")
    @mock.patch("posthog.api.authentication.get_instance_available_sso_providers")
    @pytest.mark.ee
    def test_cannot_social_signup_with_allowed_but_jit_provisioning_disabled(self, mock_sso_providers, mock_request):
        mock_sso_providers.return_value = {"google-oauth2": True}
        new_org = Organization.objects.create(name="Test org")
        OrganizationDomain.objects.create(
            domain="posthog.net",
            verified_at=timezone.now(),
            jit_provisioning_enabled=False,
            organization=new_org,
        )  # note `jit_provisioning_enabled=False`

        response = self.client.get(reverse("social:begin", kwargs={"backend": "google-oauth2"}))
        self.assertEqual(response.status_code, status.HTTP_302_FOUND)

        url = reverse("social:complete", kwargs={"backend": "google-oauth2"})
        url += f"?code=2&state={response.client.session['google-oauth2_state']}"
        mock_request.return_value.json.return_value = {
            "access_token": "123",
            "email": "alice@posthog.net",
        }

        response = self.client.get(url, follow=True)
        self.assertEqual(response.status_code, status.HTTP_200_OK)  # because `follow=True`
        self.assertRedirects(
            response, "/login?error_code=jit_not_enabled"
        )  # show the user an error; operation not permitted

    @mock.patch("social_core.backends.base.BaseAuth.request")
    @mock.patch("posthog.api.authentication.get_instance_available_sso_providers")
    @pytest.mark.ee
    def test_cannot_social_signup_with_allowed_but_unverified_domain(self, mock_sso_providers, mock_request):
        mock_sso_providers.return_value = {"google-oauth2": True}
        new_org = Organization.objects.create(name="Test org")
        OrganizationDomain.objects.create(
            domain="posthog.net",
            verified_at=None,
            jit_provisioning_enabled=True,
            organization=new_org,
        )  # note `verified_at=None`

        response = self.client.get(reverse("social:begin", kwargs={"backend": "google-oauth2"}))
        self.assertEqual(response.status_code, status.HTTP_302_FOUND)

        url = reverse("social:complete", kwargs={"backend": "google-oauth2"})
        url += f"?code=2&state={response.client.session['google-oauth2_state']}"
        mock_request.return_value.json.return_value = {
            "access_token": "123",
            "email": "alice@posthog.net",
        }

        response = self.client.get(url, follow=True)
        self.assertEqual(response.status_code, status.HTTP_200_OK)  # because `follow=True`
        self.assertRedirects(
            response, "/login?error_code=no_new_organizations"
        )  # show the user an error; operation not permitted

    @mock.patch("social_core.backends.base.BaseAuth.request")
    @mock.patch("posthog.api.authentication.get_instance_available_sso_providers")
    @pytest.mark.ee
    def test_api_cannot_use_allow_list_for_different_domain(self, mock_sso_providers, mock_request):
        mock_sso_providers.return_value = {"google-oauth2": True}
        new_org = Organization.objects.create(name="Test org")
        OrganizationDomain.objects.create(
            domain="good.com",
            verified_at=timezone.now(),
            jit_provisioning_enabled=True,
            organization=new_org,
        )

        response = self.client.get(reverse("social:begin", kwargs={"backend": "google-oauth2"}))
        self.assertEqual(response.status_code, status.HTTP_302_FOUND)

        url = reverse("social:complete", kwargs={"backend": "google-oauth2"})
        url += f"?code=2&state={response.client.session['google-oauth2_state']}"
        mock_request.return_value.json.return_value = {
            "access_token": "123",
            "email": "alice@evil.com",
        }  # note evil.com

        response = self.client.get(url, follow=True)
        self.assertEqual(response.status_code, status.HTTP_200_OK)  # because `follow=True`
        self.assertRedirects(
            response, "/login?error_code=no_new_organizations"
        )  # show the user an error; operation not permitted

    @mock.patch("social_core.backends.base.BaseAuth.request")
    @mock.patch("posthog.api.authentication.get_instance_available_sso_providers")
    @pytest.mark.ee
    def test_social_signup_to_existing_org_without_allowed_domain_on_cloud(self, mock_sso_providers, mock_request):
        with self.is_cloud(True):
            mock_sso_providers.return_value = {"google-oauth2": True}
            Organization.objects.create(name="Hogflix Movies")
            user_count = User.objects.count()
            org_count = Organization.objects.count()
            response = self.client.get(reverse("social:begin", kwargs={"backend": "google-oauth2"}))
            self.assertEqual(response.status_code, 302)

            url = reverse("social:complete", kwargs={"backend": "google-oauth2"})
            url += f"?code=2&state={response.client.session['google-oauth2_state']}"
            mock_request.return_value.json.return_value = {
                "access_token": "123",
                "email": "jane@hogflix.posthog.com",
            }
            response = self.client.get(url, follow=True)

        self.assertEqual(response.status_code, status.HTTP_200_OK)  # because `follow=True`
        self.assertRedirects(
            response,
            "/organization/confirm-creation?organization_name=&first_name=jane&email=jane%40hogflix.posthog.com",
        )  # page where user will create a new org

        # User and org are not created
        self.assertEqual(User.objects.count(), user_count)
        self.assertEqual(Organization.objects.count(), org_count)


class TestInviteSignupAPI(APIBaseTest):
    """
    Tests the sign up process for users with an invite (i.e. existing organization).
    """

    CONFIG_EMAIL = None

    # Invite pre-validation

    def test_api_invite_sign_up_prevalidate(self):
        invite: OrganizationInvite = OrganizationInvite.objects.create(
            target_email="test+19@posthog.com", organization=self.organization
        )

        response = self.client.get(f"/api/signup/{invite.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.json(),
            {
                "id": str(invite.id),
                "target_email": "test+19@posthog.com",
                "first_name": "",
                "organization_name": self.CONFIG_ORGANIZATION_NAME,
            },
        )

    def test_api_invite_sign_up_with_first_name_prevalidate(self):
        invite: OrganizationInvite = OrganizationInvite.objects.create(
            target_email="test+58@posthog.com",
            organization=self.organization,
            first_name="Jane",
        )

        response = self.client.get(f"/api/signup/{invite.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.json(),
            {
                "id": str(invite.id),
                "target_email": "test+58@posthog.com",
                "first_name": "Jane",
                "organization_name": self.CONFIG_ORGANIZATION_NAME,
            },
        )

    def test_api_invite_sign_up_prevalidate_for_existing_user(self):
        user = self._create_user("test+29@posthog.com", "test_password")
        new_org = Organization.objects.create(name="Test, Inc")
        invite: OrganizationInvite = OrganizationInvite.objects.create(
            target_email="test+29@posthog.com", organization=new_org
        )

        self.client.force_login(user)
        response = self.client.get(f"/api/signup/{invite.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.json(),
            {
                "id": str(invite.id),
                "target_email": "test+29@posthog.com",
                "first_name": "",
                "organization_name": "Test, Inc",
            },
        )

    def test_api_invite_sign_up_prevalidate_invalid_invite(self):
        for invalid_invite in [uuid.uuid4(), "abc", "1234"]:
            response = self.client.get(f"/api/signup/{invalid_invite}/")
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
            self.assertEqual(
                response.json(),
                {
                    "type": "validation_error",
                    "code": "invalid_input",
                    "detail": "The provided invite ID is not valid.",
                    "attr": None,
                },
            )

    def test_existing_user_cant_claim_invite_if_it_doesnt_match_target_email(self):
        user = self._create_user("test+39@posthog.com", "test_password")
        invite: OrganizationInvite = OrganizationInvite.objects.create(
            target_email="test+49@posthog.com", organization=self.organization
        )

        self.client.force_login(user)
        response = self.client.get(f"/api/signup/{invite.id}/")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json(),
            {
                "type": "validation_error",
                "code": "invalid_recipient",
                "detail": "This invite is intended for another email address.",
                "attr": None,
            },
        )

    def test_api_invite_sign_up_prevalidate_expired_invite(self):
        invite: OrganizationInvite = OrganizationInvite.objects.create(
            target_email="test+59@posthog.com", organization=self.organization
        )
        invite.created_at = datetime.datetime(2020, 12, 1, tzinfo=ZoneInfo("UTC"))
        invite.save()

        response = self.client.get(f"/api/signup/{invite.id}/")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json(),
            {
                "type": "validation_error",
                "code": "expired",
                "detail": "This invite has expired. Please ask your admin for a new one.",
                "attr": None,
            },
        )

    # Signup (using invite)

    @patch("posthoganalytics.capture")
    def test_api_invite_sign_up(self, mock_capture):
        invite: OrganizationInvite = OrganizationInvite.objects.create(
            target_email="test+99@posthog.com", organization=self.organization
        )

        response = self.client.post(
            f"/api/signup/{invite.id}/",
            {
                "first_name": "Alice",
                "password": "test_password",
                "email_opt_in": True,
                "role_at_organization": "Engineering",
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        user = cast(User, User.objects.order_by("-pk")[0])
        self.assertEqual(
            response.json(),
            {
                "id": user.pk,
                "uuid": str(user.uuid),
                "distinct_id": user.distinct_id,
                "last_name": "",
                "first_name": "Alice",
                "email": "test+99@posthog.com",
                "redirect_url": "/",
                "is_email_verified": False,
            },
        )

        # User is now a member of the organization
        self.assertEqual(user.organization_memberships.count(), 1)
        self.assertEqual(
            user.organization_memberships.first().organization,  # type: ignore
            self.organization,
        )

        # Defaults are set correctly
        self.assertEqual(user.organization, self.organization)
        self.assertEqual(user.team, self.team)

        # Assert that the user was properly created
        self.assertEqual(user.first_name, "Alice")
        self.assertEqual(user.email, "test+99@posthog.com")
        self.assertEqual(user.email_opt_in, True)

        # Assert that the sign up event & identify calls were sent to PostHog analytics
        mock_capture.assert_called_once()
        self.assertEqual(user.distinct_id, mock_capture.call_args.args[0])
        self.assertEqual("user signed up", mock_capture.call_args.args[1])
        self.assertEqual(
            "Engineering",
            mock_capture.call_args[1]["properties"]["role_at_organization"],
        )
        # Assert that key properties were set properly
        event_props = mock_capture.call_args.kwargs["properties"]
        self.assertEqual(event_props["is_first_user"], False)
        self.assertEqual(event_props["is_organization_first_user"], False)
        self.assertEqual(event_props["new_onboarding_enabled"], False)
        self.assertEqual(
            event_props["signup_backend_processor"],
            "OrganizationInviteSignupSerializer",
        )
        self.assertEqual(event_props["signup_social_provider"], "")
        self.assertEqual(event_props["realm"], get_instance_realm())

        # Assert that the user is logged in
        response = self.client.get("/api/users/@me/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["email"], "test+99@posthog.com")

        # Assert that the password was correctly saved
        self.assertTrue(user.check_password("test_password"))

    @pytest.mark.ee
    def test_api_invite_sign_up_where_there_are_no_default_non_private_projects(self):
        self.client.logout()
        invite: OrganizationInvite = OrganizationInvite.objects.create(
            target_email="test+private@posthog.com", organization=self.organization
        )

        self.organization.available_features = [AvailableFeature.PROJECT_BASED_PERMISSIONING]
        self.organization.save()
        self.team.access_control = True
        self.team.save()

        response = self.client.post(
            f"/api/signup/{invite.id}/",
            {"first_name": "Alice", "password": "test_password", "email_opt_in": True},
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        user = cast(User, User.objects.order_by("-pk")[0])
        self.assertEqual(user.organization_memberships.count(), 1)
        self.assertEqual(user.organization, self.organization)
        # here
        self.assertEqual(
            user.current_team, None
        )  # User is not assigned to a project, as there are no non-private projects
        self.assertEqual(user.team, None)

    def test_api_invite_sign_up_where_default_project_is_private(self):
        self.client.logout()
        self.team.access_control = True
        self.team.save()
        team = Team.objects.create(name="Public project", organization=self.organization, access_control=False)
        invite: OrganizationInvite = OrganizationInvite.objects.create(
            target_email="test+privatepublic@posthog.com",
            organization=self.organization,
        )
        response = self.client.post(
            f"/api/signup/{invite.id}/",
            {"first_name": "Charlie", "password": "test_password"},
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        user = cast(User, User.objects.order_by("-pk")[0])
        self.assertEqual(user.organization_memberships.count(), 1)
        self.assertEqual(user.organization, self.organization)
        self.assertEqual(user.current_team, team)
        self.assertEqual(user.team, team)

    def test_api_invite_sign_up_member_joined_email_is_not_sent_for_initial_member(self):
        invite: OrganizationInvite = OrganizationInvite.objects.create(
            target_email="test+100@posthog.com", organization=self.organization
        )

        with self.settings(
            EMAIL_ENABLED=True,
            EMAIL_HOST="localhost",
            SITE_URL="http://test.posthog.com",
        ):
            response = self.client.post(
                f"/api/signup/{invite.id}/",
                {
                    "first_name": "Alice",
                    "password": "test_password",
                    "email_opt_in": True,
                },
            )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        self.assertEqual(len(mail.outbox), 0)

    def test_api_invite_sign_up_member_joined_email_is_sent_for_next_members(self):
        with override_instance_config("EMAIL_HOST", "localhost"):
            initial_user = User.objects.create_and_join(self.organization, "test+420@posthog.com", None)

            invite: OrganizationInvite = OrganizationInvite.objects.create(
                target_email="test+100@posthog.com", organization=self.organization
            )

            with self.settings(EMAIL_ENABLED=True, SITE_URL="http://test.posthog.com"):
                response = self.client.post(
                    f"/api/signup/{invite.id}/",
                    {
                        "first_name": "Alice",
                        "password": "test_password",
                        "email_opt_in": True,
                    },
                )

            self.assertEqual(response.status_code, status.HTTP_201_CREATED)

            self.assertEqual(len(mail.outbox), 2)
            # Someone joined email is sent to the initial user
            self.assertListEqual(mail.outbox[0].to, [initial_user.email])
            # Verify email is sent to the new user
            self.assertListEqual(mail.outbox[1].to, [invite.target_email])

    def test_api_invite_sign_up_member_joined_email_is_not_sent_if_disabled(self):
        self.organization.is_member_join_email_enabled = False
        self.organization.save()

        User.objects.create_and_join(self.organization, "test+420@posthog.com", None)

        invite: OrganizationInvite = OrganizationInvite.objects.create(
            target_email="test+100@posthog.com", organization=self.organization
        )

        with self.settings(
            EMAIL_ENABLED=True,
            EMAIL_HOST="localhost",
            SITE_URL="http://test.posthog.com",
        ):
            response = self.client.post(
                f"/api/signup/{invite.id}/",
                {
                    "first_name": "Alice",
                    "password": "test_password",
                    "email_opt_in": True,
                },
            )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        self.assertEqual(len(mail.outbox), 0)

    @patch("posthoganalytics.capture")
    @patch("ee.billing.billing_manager.BillingManager.update_billing_distinct_ids")
    def test_existing_user_can_sign_up_to_a_new_organization(self, mock_update_distinct_ids, mock_capture):
        user = self._create_user("test+159@posthog.com", "test_password")
        new_org = Organization.objects.create(name="TestCo")
        new_team = Team.objects.create(organization=new_org)
        invite: OrganizationInvite = OrganizationInvite.objects.create(
            target_email="test+159@posthog.com", organization=new_org
        )

        self.client.force_login(user)

        count = User.objects.count()

        try:
            from ee.models.license import License, LicenseManager
        except ImportError:
            pass
        else:
            super(LicenseManager, cast(LicenseManager, License.objects)).create(
                key="key_123",
                plan="enterprise",
                valid_until=timezone.datetime(2038, 1, 19, 3, 14, 7),
            )

        with self.is_cloud(True):
            response = self.client.post(f"/api/signup/{invite.id}/")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(
            response.json(),
            {
                "id": user.pk,
                "uuid": str(user.uuid),
                "distinct_id": user.distinct_id,
                "last_name": "",
                "first_name": "",
                "email": "test+159@posthog.com",
                "redirect_url": "/",
                "is_email_verified": None,
            },
        )

        # No new user is created
        self.assertEqual(User.objects.count(), count)

        # User is now a member of the organization
        user.refresh_from_db()
        self.assertEqual(user.organization_memberships.count(), 2)
        self.assertTrue(user.organization_memberships.filter(organization=new_org).exists())

        # User is now changed to the new organization
        self.assertEqual(user.organization, new_org)
        self.assertEqual(user.team, new_team)

        # User is not changed
        self.assertEqual(user.first_name, "")
        self.assertEqual(user.email, "test+159@posthog.com")
        self.assertFalse(user.is_staff)  # Not first user in the instance

        # Assert that the sign up event & identify calls were sent to PostHog analytics
        mock_capture.assert_called_once_with(
            user.distinct_id,
            "user joined organization",
            properties={
                "organization_id": str(new_org.id),
                "user_number_of_org_membership": 2,
                "org_current_invite_count": 0,
                "org_current_project_count": 1,
                "org_current_members_count": 1,
                "$set": ANY,
            },
            groups={"instance": ANY, "organization": str(new_org.id)},
        )

        # Assert that the user remains logged in
        response = self.client.get("/api/users/@me/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Assert that the org's distinct IDs are sent to billing
        mock_update_distinct_ids.assert_called_once_with(new_org)

    @patch("posthoganalytics.capture")
    def test_cannot_use_claim_invite_endpoint_to_update_user(self, mock_capture):
        """
        Tests that a user cannot use the claim invite endpoint to change their name or password
        (as this endpoint does not do any checks that might be required).
        """
        new_org = Organization.objects.create(name="TestCo")
        user = self._create_user("test+189@posthog.com", "test_password")
        user2 = self._create_user("test+949@posthog.com")
        user2.join(organization=new_org)

        Team.objects.create(organization=new_org)
        invite: OrganizationInvite = OrganizationInvite.objects.create(
            target_email="test+189@posthog.com", organization=new_org
        )

        self.client.force_login(user)

        response = self.client.post(
            f"/api/signup/{invite.id}/",
            {"first_name": "Bob", "password": "new_password"},
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(
            response.json(),
            {
                "id": user.pk,
                "uuid": str(user.uuid),
                "distinct_id": user.distinct_id,
                "last_name": "",
                "first_name": "",
                "email": "test+189@posthog.com",
                "redirect_url": "/",
                "is_email_verified": None,
            },  # note the unchanged attributes
        )

        # User is subscribed to the new organization
        user.refresh_from_db()
        self.assertTrue(user.organization_memberships.filter(organization=new_org).exists())

        # User is not changed
        self.assertEqual(user.first_name, "")
        self.assertFalse(user.check_password("new_password"))  # Password is not updated

        # Assert that the sign up event & identify calls were sent to PostHog analytics
        mock_capture.assert_called_once_with(
            user.distinct_id,
            "user joined organization",
            properties={
                "organization_id": str(new_org.id),
                "user_number_of_org_membership": 2,
                "org_current_invite_count": 0,
                "org_current_project_count": 1,
                "org_current_members_count": 2,
                "$set": ANY,
            },
            groups={"instance": ANY, "organization": str(new_org.id)},
        )

    def test_cant_claim_sign_up_invite_without_required_attributes(self):
        count: int = User.objects.count()
        team_count: int = Team.objects.count()
        org_count: int = Organization.objects.count()

        required_attributes = ["first_name", "password"]

        invite: OrganizationInvite = OrganizationInvite.objects.create(
            target_email="test+799@posthog.com", organization=self.organization
        )

        for attribute in required_attributes:
            body = {"first_name": "Charlie", "password": "test_password"}
            body.pop(attribute)

            response = self.client.post(f"/api/signup/{invite.id}/", body)
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
            self.assertEqual(
                response.json(),
                {
                    "type": "validation_error",
                    "code": "required",
                    "detail": "This field is required.",
                    "attr": attribute,
                },
            )

        self.assertEqual(User.objects.count(), count)
        self.assertEqual(Team.objects.count(), team_count)
        self.assertEqual(Organization.objects.count(), org_count)

    def test_cant_claim_invite_sign_up_with_short_password(self):
        count: int = User.objects.count()
        team_count: int = Team.objects.count()
        org_count: int = Organization.objects.count()

        invite: OrganizationInvite = OrganizationInvite.objects.create(
            target_email="test+799@posthog.com", organization=self.organization
        )

        response = self.client.post(f"/api/signup/{invite.id}/", {"first_name": "Charlie", "password": "123"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json(),
            {
                "type": "validation_error",
                "code": "password_too_short",
                "detail": "This password is too short. It must contain at least 8 characters.",
                "attr": "password",
            },
        )

        self.assertEqual(User.objects.count(), count)
        self.assertEqual(Team.objects.count(), team_count)
        self.assertEqual(Organization.objects.count(), org_count)

    def test_cant_claim_invalid_invite(self):
        count: int = User.objects.count()
        team_count: int = Team.objects.count()
        org_count: int = Organization.objects.count()

        response = self.client.post(
            f"/api/signup/{uuid.uuid4()}/",
            {"first_name": "Charlie", "password": "test_password"},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json(),
            {
                "type": "validation_error",
                "code": "invalid_input",
                "detail": "The provided invite ID is not valid.",
                "attr": None,
            },
        )

        self.assertEqual(User.objects.count(), count)
        self.assertEqual(Team.objects.count(), team_count)
        self.assertEqual(Organization.objects.count(), org_count)

    def test_cant_claim_expired_invite(self):
        count: int = User.objects.count()
        team_count: int = Team.objects.count()
        org_count: int = Organization.objects.count()

        invite: OrganizationInvite = OrganizationInvite.objects.create(
            target_email="test+799@posthog.com", organization=self.organization
        )
        invite.created_at = datetime.datetime(2020, 3, 3, tzinfo=ZoneInfo("UTC"))
        invite.save()

        response = self.client.post(
            f"/api/signup/{invite.id}/",
            {"first_name": "Charlie", "password": "test_password"},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json(),
            {
                "type": "validation_error",
                "code": "expired",
                "detail": "This invite has expired. Please ask your admin for a new one.",
                "attr": None,
            },
        )

        self.assertEqual(User.objects.count(), count)
        self.assertEqual(Team.objects.count(), team_count)
        self.assertEqual(Organization.objects.count(), org_count)

    # Social signup (use invite)

    def test_api_social_invite_sign_up(self):
        Organization.objects.all().delete()  # Can only create organizations in fresh instances
        # Simulate SSO process started
        session = self.client.session
        session.update(
            {
                "backend": "google-oauth2",
                "email": "test_api_social_invite_sign_up@posthog.com",
            }
        )
        session.save()

        response = self.client.post(
            "/api/social_signup",
            {
                "organization_name": "Org test_api_social_invite_sign_up",
                "first_name": "Max",
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        self.assertEqual(response.json(), {"continue_url": "/complete/google-oauth2/"})

        # Check the organization and user were created
        self.assertEqual(
            User.objects.filter(
                email="test_api_social_invite_sign_up@posthog.com",
                first_name="Max",
                is_email_verified=True,
            ).count(),
            1,
        )
        self.assertEqual(
            Organization.objects.filter(name="Org test_api_social_invite_sign_up").count(),
            1,
        )

    @patch("posthog.api.signup.is_email_available", return_value=True)
    @patch("posthog.api.signup.EmailVerifier.create_token_and_send_email_verification")
    def test_api_social_invite_sign_up_if_email_verification_on(self, email_mock, email_available_mock):
        """Test to make sure that social signups skip email verification"""
        Organization.objects.all().delete()  # Can only create organizations in fresh instances
        # Simulate SSO process started
        session = self.client.session
        session.update(
            {
                "backend": "google-oauth2",
                "email": "test_api_social_invite_sign_up_with_verification@posthog.com",
            }
        )
        session.save()

        response = self.client.post(
            "/api/social_signup",
            {
                "organization_name": "Org test_api_social_invite_sign_up_with_verification",
                "first_name": "Max",
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        self.assertEqual(response.json(), {"continue_url": "/complete/google-oauth2/"})

        # Check the organization and user were created
        self.assertEqual(
            User.objects.filter(
                email="test_api_social_invite_sign_up_with_verification@posthog.com",
                first_name="Max",
            ).count(),
            1,
        )
        self.assertEqual(
            Organization.objects.filter(name="Org test_api_social_invite_sign_up_with_verification").count(),
            1,
        )
        me_response = self.client.get("/api/users/@me/")
        self.assertEqual(me_response.status_code, status.HTTP_200_OK)

    def test_cannot_use_social_invite_sign_up_if_social_session_is_not_active(self):
        Organization.objects.all().delete()  # Can only create organizations in fresh instances

        response = self.client.post(
            "/api/social_signup",
            {"organization_name": "Tech R Us", "first_name": "Max"},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json(),
            {
                "type": "validation_error",
                "code": "invalid_input",
                "detail": "Inactive social login session. Go to /login and log in before continuing.",
                "attr": None,
            },
        )
        self.assertEqual(len(self.client.session.keys()), 0)  # Nothing is saved in the session

    def test_cannot_use_social_invite_sign_up_without_required_attributes(self):
        Organization.objects.all().delete()  # Can only create organizations in fresh instances

        response = self.client.post("/api/social_signup", {"email_opt_in": False})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json(),
            {
                "type": "validation_error",
                "code": "required",
                "detail": "This field is required.",
                "attr": "organization_name",
            },
        )
        self.assertEqual(len(self.client.session.keys()), 0)  # Nothing is saved in the session

    def test_invite_an_already_existing_user(self):
        # Given an existing user
        user = self._create_user("test+29@posthog.com", "test_password")

        # IF an invitation is sent to that particular user
        invite: OrganizationInvite = OrganizationInvite.objects.create(
            target_email=user.email, organization=self.organization
        )

        # AND if the user is trying to accept the invite.
        response = self.client.get(f"/api/signup/{invite.id}/")

        # THEN the request should fail
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        # AND then
        self.assertEqual(response.json()["code"], "account_exists")

        # AND then
        self.assertEqual(response.json()["detail"], f"/login?next=/signup/{invite.id}")
