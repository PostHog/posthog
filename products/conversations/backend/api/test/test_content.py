from posthog.test.base import APIBaseTest

from rest_framework import status


class TestContentArticleViewSet(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.url = f"/api/projects/{self.team.id}/conversations/content/"

    def test_crud(self):
        # Create
        response = self.client.post(
            self.url,
            data={"title": "Test", "body": "Content", "is_enabled": True, "channels": ["widget"]},
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        article_id = response.json()["id"]

        # Read
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()["results"]), 1)

        # Update
        response = self.client.patch(f"{self.url}{article_id}/", data={"title": "Updated"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Delete
        response = self.client.delete(f"{self.url}{article_id}/")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
