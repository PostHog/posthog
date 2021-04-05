from typing import cast

import pytest
from django.conf import settings
from rest_framework import status

from posthog.constants import RDBMS
from posthog.models import User
from posthog.test.base import APIBaseTest
from posthog.version import VERSION


class TestPreflight(APIBaseTest):
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
                "available_social_auth_providers": {"google-oauth2": False, "github": False, "gitlab": False},
            },
        )

    def test_preflight_request(self):
        with self.settings(MULTI_TENANCY=False):
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
                    "ee_available": settings.EE_AVAILABLE,
                    "ee_enabled": False,
                    "db_backend": "postgres",
                    "available_social_auth_providers": {"google-oauth2": False, "github": False, "gitlab": False},
                    "opt_out_capture": False,
                    "posthog_version": VERSION,
                    "email_service_available": False,
                    "is_debug": False,
                    "is_event_property_usage_enabled": False,
                    "is_async_event_action_mapping_enabled": True,
                },
            )
            self.assertDictContainsSubset({"Europe/Moscow": 3, "UTC": 0}, available_timezones)

    @pytest.mark.ee
    def test_cloud_preflight_request_unauthenticated(self):

        self.client.logout()  # make sure it works anonymously
        User.objects.all().delete()

        with self.settings(MULTI_TENANCY=True, PRIMARY_DB=RDBMS.CLICKHOUSE):
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
                    "initiated": False,
                    "cloud": True,
                    "available_social_auth_providers": {"google-oauth2": False, "github": False, "gitlab": False},
                },
            )

    @pytest.mark.ee
    def test_cloud_preflight_request(self):

        with self.settings(MULTI_TENANCY=True, PRIMARY_DB=RDBMS.CLICKHOUSE):
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
                    "ee_available": True,
                    "ee_enabled": True,
                    "db_backend": "clickhouse",
                    "available_social_auth_providers": {"google-oauth2": False, "github": False, "gitlab": False},
                    "opt_out_capture": False,
                    "posthog_version": VERSION,
                    "email_service_available": False,
                    "is_debug": False,
                    "is_event_property_usage_enabled": False,
                    "is_async_event_action_mapping_enabled": True,
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
            PRIMARY_DB=RDBMS.CLICKHOUSE,
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
                    "ee_available": True,
                    "ee_enabled": True,
                    "db_backend": "clickhouse",
                    "available_social_auth_providers": {"google-oauth2": True, "github": False, "gitlab": False},
                    "opt_out_capture": False,
                    "posthog_version": VERSION,
                    "email_service_available": True,
                    "is_debug": False,
                    "is_event_property_usage_enabled": False,
                    "is_async_event_action_mapping_enabled": True,
                },
            )
            self.assertDictContainsSubset({"Europe/Moscow": 3, "UTC": 0}, available_timezones)
