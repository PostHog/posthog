"""Test that bulk deletion operations can be disabled via environment variable."""

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from rest_framework import status

from posthog.models import Organization, OrganizationMembership, Team
from posthog.models.project import Project


class TestBulkDeletionDisabled(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.additional_team = Team.objects.create(organization=self.organization, name="Test Team for Deletion")

    @patch("posthog.api.team.settings.DISABLE_BULK_DELETES", True)
    def test_team_deletion_disabled(self):
        """Test that team deletion returns 400 when DISABLE_BULK_DELETES is True."""
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        response = self.client.delete(f"/api/environments/{self.additional_team.id}/")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("temporarily disabled", response.json()["detail"])

        self.assertTrue(Team.objects.filter(id=self.additional_team.id).exists())

    @patch("posthog.api.team.settings.DISABLE_BULK_DELETES", False)
    def test_team_deletion_enabled(self):
        """Test that team deletion works when DISABLE_BULK_DELETES is False."""
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        response = self.client.delete(f"/api/environments/{self.additional_team.id}/")

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

        self.assertFalse(Team.objects.filter(id=self.additional_team.id).exists())

    @patch("posthog.api.project.settings.DISABLE_BULK_DELETES", True)
    def test_project_deletion_disabled(self):
        """Test that project deletion returns 400 when DISABLE_BULK_DELETES is True."""
        # Set user as org admin first to ensure proper permissions
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        project_id = Team.objects.increment_id_sequence()
        test_project = Project.objects.create(
            id=project_id, organization=self.organization, name="Test Project for Deletion"
        )
        # Create the associated Team with the same ID so the user has permission to access the project
        Team.objects.create(
            id=project_id, project=test_project, organization=self.organization, name="Test Team for Deletion"
        )

        response = self.client.delete(f"/api/projects/{test_project.id}/")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("temporarily disabled", response.json()["detail"])

        self.assertTrue(Project.objects.filter(id=test_project.id).exists())

    @patch("posthog.api.organization.settings.DISABLE_BULK_DELETES", True)
    def test_organization_deletion_disabled(self):
        """Test that organization deletion returns 400 when DISABLE_BULK_DELETES is True."""
        test_org, org_membership, _ = Organization.objects.bootstrap(self.user, name="Test Org for Deletion")

        response = self.client.delete(f"/api/organizations/{test_org.id}/")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("temporarily disabled", response.json()["detail"])

        self.assertTrue(Organization.objects.filter(id=test_org.id).exists())
