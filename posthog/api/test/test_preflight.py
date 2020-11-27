from rest_framework import status

from posthog.models import User

from .base import BaseTest


class TestPreflight(BaseTest):
    def test_preflight_request(self):
        with self.settings(MULTI_TENANCY=False):
            response = self.client.get("/_preflight/")
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            response = response.json()
            self.assertEqual(response["django"], True)
            self.assertEqual(response["db"], True)
            self.assertEqual(response["initiated"], True)
            self.assertEqual(response["cloud"], False)

    def test_preflight_request_bis(self):
        self.client.logout()  # make sure it works anonymously
        User.objects.all().delete()
        with self.settings(MULTI_TENANCY=True):
            response = self.client.get("/_preflight/")
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            response = response.json()
            self.assertEqual(response["django"], True)
            self.assertEqual(response["db"], True)
            self.assertEqual(response["initiated"], False)
            self.assertEqual(response["cloud"], True)
