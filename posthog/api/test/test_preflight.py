from rest_framework import status

from .base import BaseTest


class TestPreflight(BaseTest):
    def test_preflight_request(self):
        self.client.logout()  # make sure it works anonymously

        response = self.client.get("/_status/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response = response.json()
        response = response["preflight_check"]
        self.assertEqual(response["django"], True)
        self.assertEqual(response["db"], True)

    def test_preflight_request_no_redis(self):

        with self.settings(REDIS_URL=None):
            response = self.client.get("/_status")  # Make sure the endpoint works with and without the trailing slash

        status_code = response.status_code
        response = response.json()
        response = response["preflight_check"]
        self.assertEqual(status_code, status.HTTP_200_OK)
        self.assertEqual(response, {"django": True, "redis": False, "db": True})
