from typing import cast
from unittest.mock import patch

import pytest
from django.utils import timezone
from rest_framework import status

from posthog.models.instance_setting import set_instance_setting
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
        with self.settings(MULTI_TENANCY=False, OBJECT_STORAGE_ENABLED=False):
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
                "demo": False,
                "clickhouse": True,
                "kafka": True,
                "realm": "hosted-clickhouse",
                "available_social_auth_providers": {"google-oauth2": False, "github": False, "gitlab": False,},
                "can_create_org": False,
                "email_service_available": False,
                "object_storage": False,
            },
        )

    def test_preflight_request(self):
        with self.settings(
            MULTI_TENANCY=False,
            INSTANCE_PREFERENCES=self.instance_preferences(debug_queries=True),
            OBJECT_STORAGE_ENABLED=False,
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
                    "cloud": False,
                    "demo": False,
                    "clickhouse": True,
                    "kafka": True,
                    "realm": "hosted-clickhouse",
                    "available_social_auth_providers": {"google-oauth2": False, "github": False, "gitlab": False,},
                    "opt_out_capture": False,
                    "posthog_version": VERSION,
                    "email_service_available": False,
                    "is_debug": False,
                    "is_event_property_usage_enabled": True,
                    "licensed_users_available": None,
                    "site_url": "http://localhost:8000",
                    "can_create_org": False,
                    "instance_preferences": {"debug_queries": True, "disable_paid_fs": False,},
                    "object_storage": False,
                },
            )
            self.assertDictContainsSubset({"Europe/Moscow": 3, "UTC": 0}, available_timezones)

    @patch("posthog.storage.object_storage.s3_client")
    def test_preflight_request_with_object_storage_available(self, patched_s3_client):
        patched_s3_client.head_bucket.return_value = True

        with self.settings(
            MULTI_TENANCY=False,
            INSTANCE_PREFERENCES=self.instance_preferences(debug_queries=True),
            OBJECT_STORAGE_ENABLED=True,
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
                    "cloud": False,
                    "demo": False,
                    "clickhouse": True,
                    "kafka": True,
                    "realm": "hosted-clickhouse",
                    "available_social_auth_providers": {"google-oauth2": False, "github": False, "gitlab": False,},
                    "opt_out_capture": False,
                    "posthog_version": VERSION,
                    "email_service_available": False,
                    "is_debug": False,
                    "is_event_property_usage_enabled": True,
                    "licensed_users_available": None,
                    "site_url": "http://localhost:8000",
                    "can_create_org": False,
                    "instance_preferences": {"debug_queries": True, "disable_paid_fs": False,},
                    "object_storage": True,
                },
            )
            self.assertDictContainsSubset({"Europe/Moscow": 3, "UTC": 0}, available_timezones)

    @pytest.mark.ee
    def test_cloud_preflight_request_unauthenticated(self):
        set_instance_setting("EMAIL_HOST", "localhost")

        self.client.logout()  # make sure it works anonymously

        with self.settings(MULTI_TENANCY=True, OBJECT_STORAGE_ENABLED=False):
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
                    "demo": False,
                    "clickhouse": True,
                    "kafka": True,
                    "realm": "cloud",
                    "available_social_auth_providers": {"google-oauth2": False, "github": False, "gitlab": False,},
                    "can_create_org": True,
                    "email_service_available": True,
                    "object_storage": False,
                },
            )

    @pytest.mark.ee
    def test_cloud_preflight_request(self):
        with self.settings(MULTI_TENANCY=True, SITE_URL="https://app.posthog.com", OBJECT_STORAGE_ENABLED=False):
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
                    "demo": False,
                    "clickhouse": True,
                    "kafka": True,
                    "realm": "cloud",
                    "available_social_auth_providers": {"google-oauth2": False, "github": False, "gitlab": False,},
                    "opt_out_capture": False,
                    "posthog_version": VERSION,
                    "email_service_available": False,
                    "is_debug": False,
                    "is_event_property_usage_enabled": True,
                    "licensed_users_available": None,
                    "site_url": "https://app.posthog.com",
                    "can_create_org": True,
                    "instance_preferences": {"debug_queries": False, "disable_paid_fs": False,},
                    "object_storage": False,
                },
            )
            self.assertDictContainsSubset({"Europe/Moscow": 3, "UTC": 0}, available_timezones)

    @pytest.mark.ee
    def test_cloud_preflight_request_with_social_auth_providers(self):
        set_instance_setting("EMAIL_HOST", "localhost")

        with self.settings(
            SOCIAL_AUTH_GOOGLE_OAUTH2_KEY="test_key",
            SOCIAL_AUTH_GOOGLE_OAUTH2_SECRET="test_secret",
            MULTI_TENANCY=True,
            INSTANCE_PREFERENCES=self.instance_preferences(disable_paid_fs=True),
            OBJECT_STORAGE_ENABLED=False,
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
                    "demo": False,
                    "clickhouse": True,
                    "kafka": True,
                    "realm": "cloud",
                    "available_social_auth_providers": {"google-oauth2": True, "github": False, "gitlab": False,},
                    "opt_out_capture": False,
                    "posthog_version": VERSION,
                    "email_service_available": True,
                    "is_debug": False,
                    "is_event_property_usage_enabled": True,
                    "licensed_users_available": None,
                    "site_url": "http://localhost:8000",
                    "can_create_org": True,
                    "instance_preferences": {"debug_queries": False, "disable_paid_fs": True,},
                    "object_storage": False,
                },
            )
            self.assertDictContainsSubset({"Europe/Moscow": 3, "UTC": 0}, available_timezones)

    @pytest.mark.skip_on_multitenancy
    def test_demo(self):
        self.client.logout()  # make sure it works anonymously

        with self.settings(DEMO=True, OBJECT_STORAGE_ENABLED=False):
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
                "demo": True,
                "clickhouse": True,
                "kafka": True,
                "realm": "demo",
                "available_social_auth_providers": {"google-oauth2": False, "github": False, "gitlab": False,},
                "can_create_org": True,
                "email_service_available": False,
                "object_storage": False,
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
