"""Tests for content articles API endpoints."""

from freezegun import freeze_time
from posthog.test.base import APIBaseTest

from rest_framework import status

from products.conversations.backend.models import ContentArticle


class TestContentArticleViewSet(APIBaseTest):
    """Tests for authenticated content article API endpoints."""

    def setUp(self):
        super().setUp()
        self.url = f"/api/projects/{self.team.id}/conversations/content/"

    def test_list_articles(self):
        """Should list all articles for the team."""
        article1 = ContentArticle.objects.create(
            team=self.team,
            title="Getting Started",
            body="Welcome to our product!",
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
        article1 = ContentArticle.objects.create(
            team=self.team,
            title="Team 1 Article",
            body="Content for team 1",
            is_enabled=True,
            created_by=self.user,
        )

        # Create article in another team
        other_team = self.organization.teams.create()
        ContentArticle.objects.create(
            team=other_team,
            title="Team 2 Article",
            body="Content for team 2",
            is_enabled=True,
            created_by=self.user,
        )

        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(len(data["results"]), 1)
        self.assertEqual(data["results"][0]["id"], str(article1.id))

    def test_retrieve_article(self):
        """Should retrieve a specific article."""
        article = ContentArticle.objects.create(
            team=self.team,
            title="Test Article",
            body="This is the article body",
            is_enabled=True,
            channels=["widget", "email"],
            created_by=self.user,
        )

        response = self.client.get(f"{self.url}{article.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(data["id"], str(article.id))
        self.assertEqual(data["title"], "Test Article")
        self.assertEqual(data["body"], "This is the article body")
        self.assertTrue(data["is_enabled"])
        self.assertEqual(data["channels"], ["widget", "email"])
        self.assertEqual(data["created_by"]["id"], self.user.id)

    def test_cannot_retrieve_article_from_another_team(self):
        """Should not be able to retrieve article from another team."""
        other_team = self.organization.teams.create()
        article = ContentArticle.objects.create(
            team=other_team,
            title="Other Team Article",
            body="Content",
            is_enabled=True,
            created_by=self.user,
        )

        response = self.client.get(f"{self.url}{article.id}/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_create_article(self):
        """Should be able to create a new article."""
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
        self.assertTrue(data["is_enabled"])
        self.assertEqual(data["channels"], ["widget"])

        # Verify article was created in database
        article = ContentArticle.objects.get(id=data["id"])
        self.assertEqual(article.title, "New Article")
        self.assertEqual(article.team, self.team)

    def test_created_by_is_set_automatically(self):
        """created_by should be set to current user on create."""
        response = self.client.post(
            self.url,
            data={
                "title": "New Article",
                "body": "Content",
                "is_enabled": True,
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        data = response.json()
        self.assertEqual(data["created_by"]["id"], self.user.id)

        # Verify in database
        article = ContentArticle.objects.get(id=data["id"])
        self.assertEqual(article.created_by, self.user)

    def test_cannot_override_created_by(self):
        """Should not be able to override created_by field."""
        other_user = self.organization.members.create(email="other@example.com")

        response = self.client.post(
            self.url,
            data={
                "title": "New Article",
                "body": "Content",
                "is_enabled": True,
                "created_by": other_user.id,  # Try to override
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        data = response.json()
        # Should still be current user, not other_user
        self.assertEqual(data["created_by"]["id"], self.user.id)

    def test_update_article(self):
        """Should be able to update an article."""
        article = ContentArticle.objects.create(
            team=self.team,
            title="Original Title",
            body="Original body",
            is_enabled=True,
            created_by=self.user,
        )

        response = self.client.patch(
            f"{self.url}{article.id}/",
            data={
                "title": "Updated Title",
                "body": "Updated body",
            },
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(data["title"], "Updated Title")
        self.assertEqual(data["body"], "Updated body")

        # Verify in database
        article.refresh_from_db()
        self.assertEqual(article.title, "Updated Title")
        self.assertEqual(article.body, "Updated body")

    def test_update_is_enabled_flag(self):
        """Should be able to enable/disable articles."""
        article = ContentArticle.objects.create(
            team=self.team,
            title="Test Article",
            body="Content",
            is_enabled=True,
            created_by=self.user,
        )

        response = self.client.patch(
            f"{self.url}{article.id}/",
            data={"is_enabled": False},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        article.refresh_from_db()
        self.assertFalse(article.is_enabled)

    def test_update_channels(self):
        """Should be able to update channels."""
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
            data={"channels": ["widget", "email", "chat"]},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        article.refresh_from_db()
        self.assertEqual(article.channels, ["widget", "email", "chat"])

    def test_cannot_update_readonly_fields(self):
        """Should not be able to update read-only fields."""
        article = ContentArticle.objects.create(
            team=self.team,
            title="Test Article",
            body="Content",
            is_enabled=True,
            created_by=self.user,
        )

        with freeze_time("2024-01-01"):
            original_created_at = article.created_at

        with freeze_time("2024-02-01"):
            response = self.client.patch(
                f"{self.url}{article.id}/",
                data={
                    "created_at": "2024-12-31T00:00:00Z",
                    "updated_at": "2024-12-31T00:00:00Z",
                },
            )
            self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Fields should not have changed
        article.refresh_from_db()
        self.assertEqual(article.created_at, original_created_at)

    def test_delete_article(self):
        """Should be able to delete an article."""
        article = ContentArticle.objects.create(
            team=self.team,
            title="Test Article",
            body="Content",
            is_enabled=True,
            created_by=self.user,
        )

        response = self.client.delete(f"{self.url}{article.id}/")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

        self.assertFalse(ContentArticle.objects.filter(id=article.id).exists())

    def test_filter_by_is_enabled_true(self):
        """Should filter articles by is_enabled=true."""
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

        response = self.client.get(f"{self.url}?is_enabled=true")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(len(data["results"]), 1)
        self.assertEqual(data["results"][0]["title"], "Enabled Article")

    def test_filter_by_is_enabled_false(self):
        """Should filter articles by is_enabled=false."""
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
        ContentArticle.objects.create(
            team=self.team,
            title="Getting Advanced Features",
            body="Content",
            is_enabled=True,
            created_by=self.user,
        )

        response = self.client.get(f"{self.url}?search=getting")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(len(data["results"]), 2)
        titles = [a["title"] for a in data["results"]]
        self.assertIn("Getting Started Guide", titles)
        self.assertIn("Getting Advanced Features", titles)

    def test_search_is_case_insensitive(self):
        """Search should be case-insensitive."""
        ContentArticle.objects.create(
            team=self.team,
            title="Getting Started Guide",
            body="Content",
            is_enabled=True,
            created_by=self.user,
        )

        response = self.client.get(f"{self.url}?search=GETTING")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(len(data["results"]), 1)

    def test_ordering_by_created_at_desc(self):
        """Articles should be ordered by created_at descending."""
        with freeze_time("2024-01-01"):
            article1 = ContentArticle.objects.create(
                team=self.team,
                title="Oldest Article",
                body="Content",
                is_enabled=True,
                created_by=self.user,
            )

        with freeze_time("2024-01-03"):
            article2 = ContentArticle.objects.create(
                team=self.team,
                title="Newest Article",
                body="Content",
                is_enabled=True,
                created_by=self.user,
            )

        with freeze_time("2024-01-02"):
            article3 = ContentArticle.objects.create(
                team=self.team,
                title="Middle Article",
                body="Content",
                is_enabled=True,
                created_by=self.user,
            )

        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        article_ids = [a["id"] for a in data["results"]]

        # Should be ordered by most recent first
        self.assertEqual(article_ids[0], str(article2.id))
        self.assertEqual(article_ids[1], str(article3.id))
        self.assertEqual(article_ids[2], str(article1.id))

    def test_pagination_default_limit(self):
        """Should paginate with default limit of 100."""
        # Create 150 articles
        for i in range(150):
            ContentArticle.objects.create(
                team=self.team,
                title=f"Article {i}",
                body="Content",
                is_enabled=True,
                created_by=self.user,
            )

        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(len(data["results"]), 100)
        self.assertIsNotNone(data["next"])

    def test_pagination_custom_limit(self):
        """Should support custom limit parameter."""
        # Create 50 articles
        for i in range(50):
            ContentArticle.objects.create(
                team=self.team,
                title=f"Article {i}",
                body="Content",
                is_enabled=True,
                created_by=self.user,
            )

        response = self.client.get(f"{self.url}?limit=25")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(len(data["results"]), 25)

    def test_pagination_offset(self):
        """Should support offset parameter."""
        with freeze_time("2024-01-01"):
            article1 = ContentArticle.objects.create(
                team=self.team,
                title="First Article",
                body="Content",
                is_enabled=True,
                created_by=self.user,
            )

        with freeze_time("2024-01-02"):
            ContentArticle.objects.create(
                team=self.team,
                title="Second Article",
                body="Content",
                is_enabled=True,
                created_by=self.user,
            )

        # Get second page (offset=1, limit=1)
        response = self.client.get(f"{self.url}?limit=1&offset=1")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(len(data["results"]), 1)
        self.assertEqual(data["results"][0]["id"], str(article1.id))

    def test_pagination_max_limit(self):
        """Should respect max limit of 1000."""
        # Create 1500 articles
        for i in range(1500):
            ContentArticle.objects.create(
                team=self.team,
                title=f"Article {i}",
                body="Content",
                is_enabled=True,
                created_by=self.user,
            )

        # Try to request 2000, should be capped at 1000
        response = self.client.get(f"{self.url}?limit=2000")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(len(data["results"]), 1000)

    def test_unauthenticated_request_fails(self):
        """Unauthenticated requests should fail."""
        self.client.logout()

        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_combined_filters(self):
        """Should support multiple filters at once."""
        ContentArticle.objects.create(
            team=self.team,
            title="Getting Started",
            body="Content",
            is_enabled=True,
            created_by=self.user,
        )
        ContentArticle.objects.create(
            team=self.team,
            title="Getting Advanced",
            body="Content",
            is_enabled=False,
            created_by=self.user,
        )
        ContentArticle.objects.create(
            team=self.team,
            title="FAQ",
            body="Content",
            is_enabled=True,
            created_by=self.user,
        )

        # Filter by is_enabled AND search
        response = self.client.get(f"{self.url}?is_enabled=true&search=getting")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(len(data["results"]), 1)
        self.assertEqual(data["results"][0]["title"], "Getting Started")

    def test_embeddings_field(self):
        """Should be able to store and retrieve embeddings."""
        embeddings_data = [0.1, 0.2, 0.3, 0.4, 0.5]

        response = self.client.post(
            self.url,
            data={
                "title": "Article with embeddings",
                "body": "Content",
                "is_enabled": True,
                "embeddings": embeddings_data,
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        data = response.json()
        self.assertEqual(data["embeddings"], embeddings_data)

        # Verify in database
        article = ContentArticle.objects.get(id=data["id"])
        self.assertEqual(article.embeddings, embeddings_data)

    def test_channels_field_accepts_list(self):
        """channels field should accept a list of strings."""
        channels = ["widget", "email", "chat", "api"]

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

    def test_empty_channels_allowed(self):
        """channels can be empty or null."""
        response = self.client.post(
            self.url,
            data={
                "title": "No channel article",
                "body": "Content",
                "is_enabled": True,
                "channels": [],
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        data = response.json()
        self.assertEqual(data["channels"], [])

    def test_created_by_includes_user_details(self):
        """created_by should include user details via UserBasicSerializer."""
        article = ContentArticle.objects.create(
            team=self.team,
            title="Test Article",
            body="Content",
            is_enabled=True,
            created_by=self.user,
        )

        response = self.client.get(f"{self.url}{article.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertIn("created_by", data)
        self.assertIn("id", data["created_by"])
        self.assertIn("email", data["created_by"])
        self.assertEqual(data["created_by"]["id"], self.user.id)
        self.assertEqual(data["created_by"]["email"], self.user.email)
