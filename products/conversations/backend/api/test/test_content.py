"""Tests for content articles API endpoints."""

from posthog.test.base import APIBaseTest

from rest_framework import status

from products.conversations.backend.models import ContentArticle


class TestContentArticleViewSet(APIBaseTest):
    """Tests for content article API endpoints."""

    def setUp(self):
        super().setUp()
        self.url = f"/api/projects/{self.team.id}/conversations/content/"

    def test_list_content_articles(self):
        """Should list all content articles for the team."""
        article1 = ContentArticle.objects.create(
            team=self.team,
            title="Getting Started",
            body="Welcome to our product",
            is_enabled=True,
            created_by=self.user,
        )
        article2 = ContentArticle.objects.create(
            team=self.team,
            title="FAQ",
            body="Frequently asked questions",
            is_enabled=True,
            created_by=self.user,
        )

        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(len(data["results"]), 2)
        article_ids = [a["id"] for a in data["results"]]
        self.assertIn(str(article1.id), article_ids)
        self.assertIn(str(article2.id), article_ids)

    def test_articles_isolated_by_team(self):
        """Should only see articles from own team."""
        ContentArticle.objects.create(
            team=self.team,
            title="Team 1 Article",
            body="Content",
            is_enabled=True,
            created_by=self.user,
        )

        other_team = self.organization.teams.create()
        ContentArticle.objects.create(
            team=other_team,
            title="Other Team Article",
            body="Content",
            is_enabled=True,
        )

        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(len(data["results"]), 1)
        self.assertEqual(data["results"][0]["title"], "Team 1 Article")

    def test_create_content_article(self):
        """Should create a new content article."""
        response = self.client.post(
            self.url,
            data={
                "title": "New Article",
                "body": "Article content here",
                "is_enabled": True,
                "channels": ["widget"],
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        data = response.json()
        self.assertEqual(data["title"], "New Article")
        self.assertEqual(data["body"], "Article content here")
        self.assertEqual(data["channels"], ["widget"])

    def test_update_content_article(self):
        """Should update an existing article."""
        article = ContentArticle.objects.create(
            team=self.team,
            title="Original Title",
            body="Original body",
            is_enabled=True,
            created_by=self.user,
        )

        response = self.client.patch(
            f"{self.url}{article.id}/",
            data={"title": "Updated Title"},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        article.refresh_from_db()
        self.assertEqual(article.title, "Updated Title")

    def test_delete_content_article(self):
        """Should delete an article."""
        article = ContentArticle.objects.create(
            team=self.team,
            title="To Delete",
            body="Content",
            is_enabled=True,
            created_by=self.user,
        )

        response = self.client.delete(f"{self.url}{article.id}/")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(ContentArticle.objects.filter(id=article.id).exists())

    def test_filter_by_is_enabled(self):
        """Should filter articles by is_enabled."""
        ContentArticle.objects.create(
            team=self.team,
            title="Enabled Article",
            body="Content",
            is_enabled=True,
            created_by=self.user,
        )
        ContentArticle.objects.create(
            team=self.team,
            title="Disabled Article",
            body="Content",
            is_enabled=False,
            created_by=self.user,
        )

        response = self.client.get(f"{self.url}?is_enabled=false")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(len(data["results"]), 1)
        self.assertEqual(data["results"][0]["title"], "Disabled Article")

    def test_search_by_title(self):
        """Should search articles by title."""
        ContentArticle.objects.create(
            team=self.team,
            title="Getting Started Guide",
            body="Content",
            is_enabled=True,
            created_by=self.user,
        )
        ContentArticle.objects.create(
            team=self.team,
            title="FAQ",
            body="Content",
            is_enabled=True,
            created_by=self.user,
        )

        response = self.client.get(f"{self.url}?search=getting")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(len(data["results"]), 1)
        self.assertEqual(data["results"][0]["title"], "Getting Started Guide")

    def test_channels_field_accepts_list(self):
        """channels field should accept a list of valid channel strings."""
        channels = ["widget", "email", "slack"]

        response = self.client.post(
            self.url,
            data={
                "title": "Multi-channel article",
                "body": "Content",
                "is_enabled": True,
                "channels": channels,
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        data = response.json()
        self.assertEqual(data["channels"], channels)

    def test_update_channels(self):
        """Should update channels."""
        article = ContentArticle.objects.create(
            team=self.team,
            title="Test Article",
            body="Content",
            is_enabled=True,
            channels=["widget"],
            created_by=self.user,
        )

        response = self.client.patch(
            f"{self.url}{article.id}/",
            data={"channels": ["widget", "email", "slack"]},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        article.refresh_from_db()
        self.assertEqual(article.channels, ["widget", "email", "slack"])

    def test_empty_channels_allowed(self):
        """channels can be empty."""
        response = self.client.post(
            self.url,
            data={
                "title": "All channels article",
                "body": "Content",
                "is_enabled": True,
                "channels": [],
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        data = response.json()
        self.assertEqual(data["channels"], [])

    def test_created_by_is_set_automatically(self):
        """created_by should be set to current user."""
        response = self.client.post(
            self.url,
            data={
                "title": "Test Article",
                "body": "Content",
                "is_enabled": True,
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        data = response.json()
        self.assertEqual(data["created_by"]["id"], self.user.id)
