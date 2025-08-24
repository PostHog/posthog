"""Test that bulk deletion operations can be disabled via environment variable."""

from unittest.mock import patch

from rest_framework import status

from posthog.models import Team, Organization
from posthog.models.project import Project
from posthog.test.base import APIBaseTest


class TestBulkDeletionDisabled(APIBaseTest):
    def setUp(self):
        super().setUp()
        # Create additional team for testing
        self.additional_team = Team.objects.create(organization=self.organization, name="Test Team for Deletion")

    @patch("posthog.api.team.settings.DISABLE_BULK_DELETES", True)
    def test_team_deletion_disabled(self):
        """Test that team deletion returns 400 when DISABLE_BULK_DELETES is True."""
        response = self.client.delete(f"/api/environments/{self.additional_team.id}/")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("temporarily disabled", response.json()["detail"])

        # Verify team still exists
        self.assertTrue(Team.objects.filter(id=self.additional_team.id).exists())

    @patch("posthog.api.team.settings.DISABLE_BULK_DELETES", False)
    def test_team_deletion_enabled(self):
        """Test that team deletion works when DISABLE_BULK_DELETES is False."""
        response = self.client.delete(f"/api/environments/{self.additional_team.id}/")

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

        # Verify team is deleted
        self.assertFalse(Team.objects.filter(id=self.additional_team.id).exists())

    @patch("posthog.api.project.settings.DISABLE_BULK_DELETES", True)
    def test_project_deletion_disabled(self):
        """Test that project deletion returns 400 when DISABLE_BULK_DELETES is True."""
        # Create a test project
        test_project = Project.objects.create(organization=self.organization, name="Test Project for Deletion")

        response = self.client.delete(f"/api/projects/{test_project.id}/")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("temporarily disabled", response.json()["detail"])

        # Verify project still exists
        self.assertTrue(Project.objects.filter(id=test_project.id).exists())

    @patch("posthog.api.organization.settings.DISABLE_BULK_DELETES", True)
    def test_organization_deletion_disabled(self):
        """Test that organization deletion returns 400 when DISABLE_BULK_DELETES is True."""
        # Create a test organization
        test_org = Organization.objects.create(name="Test Org for Deletion")
        self.organization_membership = test_org.add_user(self.user, level=15)

        response = self.client.delete(f"/api/organizations/{test_org.id}/")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("temporarily disabled", response.json()["detail"])

        # Verify organization still exists
        self.assertTrue(Organization.objects.filter(id=test_org.id).exists())
