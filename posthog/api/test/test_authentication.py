import random

from rest_framework import status

from .base import APIBaseTest


class TestAuthenticationAPI(APIBaseTest):
    def test_social_auth_endpoint_default_off(self):
        """
        Tests the endpoint to obtain which backends are available.
        """

        # Same results for authenticated or unauthenticated users
        if random.randint(0, 1):
            self.client.logout()

        response = self.client.get("/api/authentication/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.json(), {"available_backends": {"google-oauth2": False, "github": False, "gitlab": False}}
        )

    def test_social_auth_with_backend_enabled(self):
        # Same results for authenticated or unauthenticated users
        if random.randint(0, 1):
            self.client.logout()

        with self.settings(
            SOCIAL_AUTH_GOOGLE_OAUTH2_KEY="test_key", SOCIAL_AUTH_GOOGLE_OAUTH2_SECRET="test_secret", MULTI_TENANCY=True
        ):
            response = self.client.get("/api/authentication/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.json(), {"available_backends": {"google-oauth2": True, "github": False, "gitlab": False}}
        )
