from posthog.test.base import APIBaseTest

from rest_framework import status


class TestGuidanceRuleViewSet(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.url = f"/api/projects/{self.team.id}/conversations/guidance/"

    def test_crud(self):
        # Create
        response = self.client.post(
            self.url,
            data={"rule_type": "tone", "name": "Test", "content": "Content", "is_active": True, "channels": ["widget"]},
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        rule_id = response.json()["id"]

        # Read
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()["results"]), 1)

        # Update
        response = self.client.patch(f"{self.url}{rule_id}/", data={"name": "Updated"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Delete
        response = self.client.delete(f"{self.url}{rule_id}/")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
