from posthog.test.base import (
    APIBaseTest,
)


class TestAirbyteSource(APIBaseTest):
    pass
    # def test_create(self):
    #     response = self.client.post(
    #         f"/api/projects/{self.team.id}/airbyte_resources/",
    #         {"account_id": "123", "client_secret": "123"},
    #     )
    #     self.assertEqual(response.status_code, 201, response.content)
    #     airbyte_source = response.json()
    #     self.assertIsNotNone(airbyte_source["source_id"])

    # def test_get(self):
    #     resource = AirbyteResource.objects.create(
    #         team=self.team,
    #         source_id="dee29342-c42a-4236-9a91-1c35462c51fc",
    #         connection_id="41abd9cc-4668-4994-b71e-cadb03c0e045",
    #     )
    #     response = self.client.get(
    #         f"/api/projects/{self.team.id}/airbyte_resources/" + str(resource.pk),
    #     )
    #     self.assertEqual(response.status_code, 200, response.content)
    #     airbyte_source = response.json()
    #     self.assertIsNotNone(airbyte_source["source_id"])
    #     print(airbyte_source)
