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
    maxDiff = 2000

    def instance_preferences(self, **kwargs):
        return {"debug_queries": False, "disable_paid_fs": False, **kwargs}

    def preflight_dict(self, options={}):
        preflight = {
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
            "region": None,
            "available_social_auth_providers": {"google-oauth2": False, "github": False, "gitlab": False},
            "can_create_org": False,
            "email_service_available": False,
            "slack_service": {"available": False, "client_id": None},
            "object_storage": False,
        }

        preflight.update(options)

        return preflight

    def preflight_authenticated_dict(self, options={}):
        preflight = {
            "opt_out_capture": False,
            "posthog_version": VERSION,
            "is_debug": False,
            "is_event_property_usage_enabled": True,
            "licensed_users_available": None,
            "site_url": "http://localhost:8000",
            "can_create_org": False,
            "instance_preferences": {"debug_queries": True, "disable_paid_fs": False},
            "object_storage": False,
            "buffer_conversion_seconds": 60,
        }

        preflight.update(options)

        return self.preflight_dict(preflight)

    def test_preflight_request_unauthenticated(self):
        """
        For security purposes, the information contained in an unauthenticated preflight request is minimal.
        """
        self.client.logout()
        with self.settings(MULTI_TENANCY=False, OBJECT_STORAGE_ENABLED=False):
            response = self.client.get("/_preflight/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), self.preflight_dict())

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

            self.assertEqual(response, self.preflight_authenticated_dict())
            self.assertDictContainsSubset({"Europe/Moscow": 3, "UTC": 0}, available_timezones)

    @patch("posthog.storage.object_storage._client")
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

            self.assertEqual(response, self.preflight_authenticated_dict({"object_storage": True}))
            self.assertDictContainsSubset({"Europe/Moscow": 3, "UTC": 0}, available_timezones)

    @pytest.mark.ee
    def test_cloud_preflight_request_unauthenticated(self):
        set_instance_setting("EMAIL_HOST", "localhost")
        set_instance_setting("SLACK_APP_CLIENT_ID", "slack-client-id")

        self.client.logout()  # make sure it works anonymously

        with self.settings(MULTI_TENANCY=True, OBJECT_STORAGE_ENABLED=False):
            response = self.client.get("/_preflight/")
            self.assertEqual(response.status_code, status.HTTP_200_OK)

            self.assertEqual(
                response.json(),
                self.preflight_dict(
                    {
                        "email_service_available": True,
                        "slack_service": {"available": True, "client_id": "slack-client-id"},
                        "can_create_org": True,
                        "cloud": True,
                        "realm": "cloud",
                        "region": "US",
                    }
                ),
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
                self.preflight_authenticated_dict(
                    {
                        "can_create_org": True,
                        "cloud": True,
                        "realm": "cloud",
                        "region": "US",
                        "instance_preferences": {"debug_queries": False, "disable_paid_fs": False},
                        "site_url": "https://app.posthog.com",
                    }
                ),
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
                self.preflight_authenticated_dict(
                    {
                        "can_create_org": True,
                        "cloud": True,
                        "realm": "cloud",
                        "region": "US",
                        "instance_preferences": {"debug_queries": False, "disable_paid_fs": True},
                        "site_url": "http://localhost:8000",
                        "available_social_auth_providers": {"google-oauth2": True, "github": False, "gitlab": False},
                        "email_service_available": True,
                    }
                ),
            )
            self.assertDictContainsSubset({"Europe/Moscow": 3, "UTC": 0}, available_timezones)

    @pytest.mark.skip_on_multitenancy
    def test_demo(self):
        self.client.logout()  # make sure it works anonymously

        with self.settings(DEMO=True, OBJECT_STORAGE_ENABLED=False):
            response = self.client.get("/_preflight/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), self.preflight_dict({"demo": True, "can_create_org": True, "realm": "demo"}))

    @pytest.mark.ee
    @pytest.mark.skip_on_multitenancy
    def test_ee_preflight_with_users_limit(self):
        try:
            from ee.models.license import License, LicenseManager
        except ImportError:
            pass
        else:
            super(LicenseManager, cast(LicenseManager, License.objects)).create(
                key="key_123", plan="free_clickhouse", valid_until=timezone.datetime(2038, 1, 19, 3, 14, 7), max_users=3
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

        try:
            from ee.models.license import License, LicenseManager
        except ImportError:
            pass
        else:
            super(LicenseManager, cast(LicenseManager, License.objects)).create(
                key="key_123", plan="enterprise", valid_until=timezone.datetime(2038, 1, 19, 3, 14, 7)
            )
            with self.settings(MULTI_ORG_ENABLED=True):
                response = self.client.get("/_preflight/")
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(response.json()["can_create_org"], True)

    @pytest.mark.ee
    def test_cloud_preflight_based_on_license(self):
        try:
            from ee.models.license import License, LicenseManager
        except ImportError:
            pass
        else:
            super(LicenseManager, cast(LicenseManager, License.objects)).create(
                key="key::123", plan="cloud", valid_until=timezone.datetime(2038, 1, 19, 3, 14, 7)
            )

            response = self.client.get("/_preflight/")
            assert response.status_code == status.HTTP_200_OK
            assert response.json()["realm"] == "cloud"
            assert response.json()["cloud"]
