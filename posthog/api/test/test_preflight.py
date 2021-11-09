from typing import cast

import pytest
from django.conf import settings
from django.utils import timezone
from rest_framework import status

from posthog.constants import AnalyticsDBMS
from posthog.models.organization import Organization, OrganizationInvite
from posthog.test.base import APIBaseTest
from posthog.version import VERSION


class TestPreflight(APIBaseTest):
    def instance_preferences(self, **kwargs):
        return {
            "debug_queries": False,
            "disable_paid_fs": False,
            **kwargs,
        }

    def test_preflight_request_unauthenticated(self):
        """
        For security purposes, the information contained in an unauthenticated preflight request is minimal.
        """
        self.client.logout()
        with self.settings(MULTI_TENANCY=False):
            response = self.client.get("/_preflight/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.json(),
            {
                "django": True,
                "redis": True,
                "plugins": True,
                "celery": True,
                "db": True,
                "initiated": True,
                "cloud": False,
                "realm": "hosted",
                "available_social_auth_providers": {
                    "google-oauth2": False,
                    "github": False,
                    "gitlab": False,
                    "saml": False,
                },
                "can_create_org": False,
                "email_service_available": False,
            },
        )

    def test_preflight_request(self):
        with self.settings(MULTI_TENANCY=False, INSTANCE_PREFERENCES=self.instance_preferences(debug_queries=True)):
            response = self.client.get("/_preflight/")
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            response = response.json()
            available_timezones = cast(dict, response).pop("available_timezones")

            self.assertEqual(
                response,
                {
                    "django": True,
                    "redis": True,
                    "plugins": True,
                    "celery": True,
                    "db": True,
                    "initiated": True,
                    "cloud": False,
                    "realm": "hosted",
                    "ee_available": settings.EE_AVAILABLE,
                    "is_clickhouse_enabled": False,
                    "db_backend": "postgres",
                    "available_social_auth_providers": {
                        "google-oauth2": False,
                        "github": False,
                        "gitlab": False,
                        "saml": False,
                    },
                    "opt_out_capture": False,
                    "posthog_version": VERSION,
                    "email_service_available": False,
                    "is_debug": False,
                    "is_event_property_usage_enabled": False,
                    "licensed_users_available": None,
                    "site_url": "http://localhost:8000",
                    "can_create_org": False,
                    "instance_preferences": {"debug_queries": True, "disable_paid_fs": False,},
                },
            )
            self.assertDictContainsSubset({"Europe/Moscow": 3, "UTC": 0}, available_timezones)

    @pytest.mark.ee
    def test_cloud_preflight_request_unauthenticated(self):

        self.client.logout()  # make sure it works anonymously

        with self.settings(MULTI_TENANCY=True, PRIMARY_DB=AnalyticsDBMS.CLICKHOUSE, EMAIL_HOST="localhost"):
            response = self.client.get("/_preflight/")
            self.assertEqual(response.status_code, status.HTTP_200_OK)

            self.assertEqual(
                response.json(),
                {
                    "django": True,
                    "redis": True,
                    "plugins": True,
                    "celery": True,
                    "db": True,
                    "initiated": True,
                    "cloud": True,
                    "realm": "cloud",
                    "available_social_auth_providers": {
                        "google-oauth2": False,
                        "github": False,
                        "gitlab": False,
                        "saml": False,
                    },
                    "can_create_org": True,
                    "email_service_available": True,
                },
            )

    @pytest.mark.ee
    def test_cloud_preflight_request(self):
        with self.settings(MULTI_TENANCY=True, PRIMARY_DB=AnalyticsDBMS.CLICKHOUSE, SITE_URL="https://app.posthog.com"):
            response = self.client.get("/_preflight/")
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            response = response.json()
            available_timezones = cast(dict, response).pop("available_timezones")

            self.assertEqual(
                response,
                {
                    "django": True,
                    "redis": True,
                    "plugins": True,
                    "celery": True,
                    "db": True,
                    "initiated": True,
                    "cloud": True,
                    "realm": "cloud",
                    "ee_available": True,
                    "is_clickhouse_enabled": True,
                    "db_backend": "clickhouse",
                    "available_social_auth_providers": {
                        "google-oauth2": False,
                        "github": False,
                        "gitlab": False,
                        "saml": False,
                    },
                    "opt_out_capture": False,
                    "posthog_version": VERSION,
                    "email_service_available": False,
                    "is_debug": False,
                    "is_event_property_usage_enabled": False,
                    "licensed_users_available": None,
                    "site_url": "https://app.posthog.com",
                    "can_create_org": True,
                    "instance_preferences": {"debug_queries": False, "disable_paid_fs": False,},
                },
            )
            self.assertDictContainsSubset({"Europe/Moscow": 3, "UTC": 0}, available_timezones)

    @pytest.mark.ee
    def test_cloud_preflight_request_with_social_auth_providers(self):
        with self.settings(
            SOCIAL_AUTH_GOOGLE_OAUTH2_KEY="test_key",
            SOCIAL_AUTH_GOOGLE_OAUTH2_SECRET="test_secret",
            MULTI_TENANCY=True,
            EMAIL_HOST="localhost",
            PRIMARY_DB=AnalyticsDBMS.CLICKHOUSE,
            INSTANCE_PREFERENCES=self.instance_preferences(disable_paid_fs=True),
        ):
            response = self.client.get("/_preflight/")
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            response = response.json()
            available_timezones = cast(dict, response).pop("available_timezones")

            self.assertEqual(
                response,
                {
                    "django": True,
                    "redis": True,
                    "plugins": True,
                    "celery": True,
                    "db": True,
                    "initiated": True,
                    "cloud": True,
                    "realm": "cloud",
                    "ee_available": True,
                    "is_clickhouse_enabled": True,
                    "db_backend": "clickhouse",
                    "available_social_auth_providers": {
                        "google-oauth2": True,
                        "github": False,
                        "gitlab": False,
                        "saml": False,
                    },
                    "opt_out_capture": False,
                    "posthog_version": VERSION,
                    "email_service_available": True,
                    "is_debug": False,
                    "is_event_property_usage_enabled": False,
                    "licensed_users_available": None,
                    "site_url": "http://localhost:8000",
                    "can_create_org": True,
                    "instance_preferences": {"debug_queries": False, "disable_paid_fs": True,},
                },
            )
            self.assertDictContainsSubset({"Europe/Moscow": 3, "UTC": 0}, available_timezones)

    @pytest.mark.ee
    @pytest.mark.skip_on_multitenancy
    def test_ee_preflight_with_saml(self):

        from ee.models.license import License, LicenseManager

        super(LicenseManager, cast(LicenseManager, License.objects)).create(
            key="key_123", plan="enterprise", valid_until=timezone.datetime(2038, 1, 19, 3, 14, 7),
        )

        self.client.logout()  # make sure it works anonymously

        with self.settings(PRIMARY_DB=AnalyticsDBMS.CLICKHOUSE, SAML_CONFIGURED=True):
            response = self.client.get("/_preflight/")
            self.assertEqual(response.status_code, status.HTTP_200_OK)

            self.assertEqual(
                response.json(),
                {
                    "django": True,
                    "redis": True,
                    "plugins": True,
                    "celery": True,
                    "db": True,
                    "initiated": True,
                    "cloud": False,
                    "realm": "hosted-clickhouse",
                    "available_social_auth_providers": {
                        "google-oauth2": False,
                        "github": False,
                        "gitlab": False,
                        "saml": True,
                    },
                    "can_create_org": False,
                    "email_service_available": False,
                },
            )

    @pytest.mark.ee
    @pytest.mark.skip_on_multitenancy
    def test_ee_preflight_with_users_limit(self):

        from ee.models.license import License, LicenseManager

        super(LicenseManager, cast(LicenseManager, License.objects)).create(
            key="key_123", plan="free_clickhouse", valid_until=timezone.datetime(2038, 1, 19, 3, 14, 7), max_users=3,
        )

        OrganizationInvite.objects.create(organization=self.organization, target_email="invite@posthog.com")

        response = self.client.get("/_preflight/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["licensed_users_available"], 1)
        self.assertEqual(response.json()["can_create_org"], False)

    def test_can_create_org_in_fresh_instance(self):
        Organization.objects.all().delete()

        response = self.client.get("/_preflight/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["can_create_org"], True)

    @pytest.mark.ee
    @pytest.mark.skip_on_multitenancy
    def test_can_create_org_with_multi_org(self):

        # First with no license
        with self.settings(MULTI_ORG_ENABLED=True):
            response = self.client.get("/_preflight/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["can_create_org"], False)

        # Now with proper license
        from ee.models.license import License, LicenseManager

        super(LicenseManager, cast(LicenseManager, License.objects)).create(
            key="key_123", plan="enterprise", valid_until=timezone.datetime(2038, 1, 19, 3, 14, 7), max_users=3,
        )
        with self.settings(MULTI_ORG_ENABLED=True):
            response = self.client.get("/_preflight/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["can_create_org"], True)
