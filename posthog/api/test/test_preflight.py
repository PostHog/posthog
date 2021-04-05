from typing import cast

from rest_framework import status

from posthog.constants import RDBMS
from posthog.models import User
from posthog.test.base import APIBaseTest


class TestPreflight(APIBaseTest):
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
                    "db_backend": "postgres",
                    "available_social_auth_providers": {"google-oauth2": False, "github": False, "gitlab": False},
                },
            )
            self.assertDictContainsSubset({"Europe/Moscow": 3, "UTC": 0}, available_timezones)

    def test_cloud_preflight_request(self):

        self.client.logout()  # make sure it works anonymously
        User.objects.all().delete()

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
                    "initiated": False,
                    "cloud": True,
                    "db_backend": "clickhouse",
                    "available_social_auth_providers": {"google-oauth2": False, "github": False, "gitlab": False},
                },
            )
            self.assertDictContainsSubset({"Europe/Moscow": 3, "UTC": 0}, available_timezones)

    def test_cloud_preflight_request_with_social_auth_providers(self):

        self.client.logout()  # make sure it works anonymously
        User.objects.all().delete()

        with self.settings(
            SOCIAL_AUTH_GOOGLE_OAUTH2_KEY="test_key",
            SOCIAL_AUTH_GOOGLE_OAUTH2_SECRET="test_secret",
            MULTI_TENANCY=True,
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
                    "initiated": False,
                    "cloud": True,
                    "db_backend": "clickhouse",
                    "available_social_auth_providers": {"google-oauth2": True, "github": False, "gitlab": False},
                },
            )
            self.assertDictContainsSubset({"Europe/Moscow": 3, "UTC": 0}, available_timezones)
