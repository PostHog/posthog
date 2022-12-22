from rest_framework import status

from posthog.test.base import APIBaseTest


class TestPreflightAPI(APIBaseTest):
    def test_preflight_instance_tag(self):
        response = self.client.get("/_preflight")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.json()["instance_tag"],
            "default",
        )
