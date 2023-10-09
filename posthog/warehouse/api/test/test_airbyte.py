from posthog.test.base import (
    APIBaseTest,
)


class TestAirbyteSource(APIBaseTest):
    def test_create(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/airbyte_resources/",
            {"account_id": "123", "client_secret": "123"},
        )
        self.assertEqual(response.status_code, 201, response.content)
        airbyte_source = response.json()
        self.assertIsNotNone(airbyte_source["source_id"])
