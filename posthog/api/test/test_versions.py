from rest_framework import status

from posthog.test.base import APIBaseTest


class TestVersions(APIBaseTest):
    def test_create_version(self):
        response = self.client.post("/api/versions/", {"instance_key": "184"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        response_data = response.json()
        self.assertEqual(response_data["id"], 1)
        self.assertEqual(response_data["instance_key"], "184")
