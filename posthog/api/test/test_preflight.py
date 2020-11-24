from rest_framework import status

from .base import BaseTest


class TestPreflight(BaseTest):
    def test_preflight_request(self):
        self.client.logout()  # make sure it works anonymously

        response = self.client.get("/_preflight/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response = response.json()
        self.assertEqual(response["django"], True)
        self.assertEqual(response["db"], True)
