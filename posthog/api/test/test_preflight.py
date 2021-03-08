from rest_framework import status

from posthog.models import User

from .base import BaseTest


class TestPreflight(BaseTest):
    def test_preflight_request(self):
        with self.settings(MULTI_TENANCY=False):
            response = self.client.get("/_preflight/")
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            response = response.json()
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
                    "available_social_auth_providers": {"google-oauth2": False, "github": False, "gitlab": False},
                },
            )

    def test_cloud_preflight_request(self):

        self.client.logout()  # make sure it works anonymously
        User.objects.all().delete()

        with self.settings(MULTI_TENANCY=True):
            response = self.client.get("/_preflight/")
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            response = response.json()
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
                    "available_social_auth_providers": {"google-oauth2": False, "github": False, "gitlab": False},
                },
            )

    def test_cloud_preflight_request_with_social_auth_providers(self):

        self.client.logout()  # make sure it works anonymously
        User.objects.all().delete()

        with self.settings(
            SOCIAL_AUTH_GOOGLE_OAUTH2_KEY="test_key",
            SOCIAL_AUTH_GOOGLE_OAUTH2_SECRET="test_secret",
            MULTI_TENANCY=True,
        ):
            response = self.client.get("/_preflight/")
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            response = response.json()
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
                    "available_social_auth_providers": {"google-oauth2": True, "github": False, "gitlab": False},
                },
            )
