from posthog.test.base import APIBaseTest

from rest_framework import status

from posthog.models import OrganizationMembership, Tag, Team
from posthog.models.feature_flag import TeamDefaultEvaluationTag


class TestTeamDefaultEvaluationTags(APIBaseTest):
    def setUp(self):
        super().setUp()
        # Make user an admin for DELETE operations
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        self.url = f"/api/environments/{self.team.id}/default_evaluation_tags/"

    def test_get_empty_default_evaluation_tags(self):
        """Test getting default evaluation tags when none exist"""
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), {"default_evaluation_tags": [], "enabled": False})

    def test_add_default_evaluation_tag(self):
        """Test adding a new default evaluation tag"""
        response = self.client.post(self.url, {"tag_name": "production"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.json()["created"])
        self.assertEqual(response.json()["name"], "production")

        # Verify it was created in the database
        self.assertTrue(TeamDefaultEvaluationTag.objects.filter(team=self.team, tag__name="production").exists())

    def test_add_duplicate_default_evaluation_tag(self):
        """Test that adding the same tag twice doesn't create duplicates"""
        # Add tag first time
        response1 = self.client.post(self.url, {"tag_name": "staging"}, format="json")
        self.assertTrue(response1.json()["created"])

        # Try to add same tag again
        response2 = self.client.post(self.url, {"tag_name": "staging"}, format="json")
        self.assertEqual(response2.status_code, status.HTTP_200_OK)
        self.assertFalse(response2.json()["created"])

        # Verify only one exists
        self.assertEqual(TeamDefaultEvaluationTag.objects.filter(team=self.team, tag__name="staging").count(), 1)

    def test_maximum_tags_limit(self):
        """Test that we can't add more than 10 default evaluation tags"""
        # Create 10 tags
        for i in range(10):
            tag = Tag.objects.create(name=f"tag-{i}", team=self.team)
            TeamDefaultEvaluationTag.objects.create(team=self.team, tag=tag)

        # Try to add 11th tag
        response = self.client.post(self.url, {"tag_name": "tag-11"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Maximum of 10", response.json()["error"])

    def test_remove_default_evaluation_tag(self):
        """Test removing a default evaluation tag"""
        # Create a tag first
        tag = Tag.objects.create(name="to-remove", team=self.team)
        TeamDefaultEvaluationTag.objects.create(team=self.team, tag=tag)

        # Remove it
        response = self.client.delete(self.url + "?tag_name=to-remove")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.json()["success"])

        # Verify it was removed
        self.assertFalse(TeamDefaultEvaluationTag.objects.filter(team=self.team, tag__name="to-remove").exists())

    def test_remove_nonexistent_tag(self):
        """Test removing a tag that doesn't exist"""
        response = self.client.delete(self.url + "?tag_name=nonexistent")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.json()["error"], "Tag not found")

    def test_tag_name_normalization(self):
        """Test that tag names are normalized (lowercased, trimmed)"""
        response = self.client.post(self.url, {"tag_name": "  PRODUCTION  "}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["name"], "production")

    def test_empty_tag_name_validation(self):
        """Test that empty tag names are rejected"""
        response = self.client.post(self.url, {"tag_name": "   "}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["error"], "tag_name is required")

    def test_get_with_enabled_setting(self):
        """Test that the enabled setting is returned correctly"""
        # Enable the feature
        self.team.default_evaluation_environments_enabled = True
        self.team.save()

        # Add some tags
        tag1 = Tag.objects.create(name="prod", team=self.team)
        tag2 = Tag.objects.create(name="dev", team=self.team)
        TeamDefaultEvaluationTag.objects.create(team=self.team, tag=tag1)
        TeamDefaultEvaluationTag.objects.create(team=self.team, tag=tag2)

        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertTrue(data["enabled"])
        self.assertEqual(len(data["default_evaluation_tags"]), 2)
        tag_names = [t["name"] for t in data["default_evaluation_tags"]]
        self.assertIn("prod", tag_names)
        self.assertIn("dev", tag_names)

    def test_cross_team_isolation(self):
        """Test that default evaluation tags are isolated between teams"""
        # Create tag for current team
        response1 = self.client.post(self.url, {"tag_name": "team1-tag"}, format="json")
        self.assertEqual(response1.status_code, status.HTTP_200_OK)

        # Create another team and try to access/modify tags
        other_team = Team.objects.create(organization=self.organization, name="Other Team")
        other_url = f"/api/environments/{other_team.id}/default_evaluation_tags/"

        # Verify other team has no tags
        response2 = self.client.get(other_url)
        self.assertEqual(response2.status_code, status.HTTP_200_OK)
        self.assertEqual(response2.json()["default_evaluation_tags"], [])

        # Add tag to other team
        response3 = self.client.post(other_url, {"tag_name": "team2-tag"}, format="json")
        self.assertEqual(response3.status_code, status.HTTP_200_OK)

        # Verify each team only sees its own tags
        self.assertEqual(TeamDefaultEvaluationTag.objects.filter(team=self.team).count(), 1)
        self.assertEqual(TeamDefaultEvaluationTag.objects.filter(team=other_team).count(), 1)
