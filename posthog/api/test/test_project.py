from unittest.mock import patch

from posthog.api.test.test_team import EnvironmentToProjectRewriteClient, team_api_test_factory
from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.personal_api_key import PersonalAPIKey, hash_key_value
from posthog.models.project import Project
from posthog.models.team import Team
from posthog.models.utils import generate_random_token_personal
from rest_framework import status


class TestProjectAPI(team_api_test_factory()):  # type: ignore
    """
    We inherit from TestTeamAPI, as previously /api/projects/ referred to the Team model, which used to mean "project".
    Now as Team means "environment" and Project is separate, we must ensure backward compatibility of /api/projects/.
    At the same time, this class is where we can continue adding `Project`-specific API tests.
    """

    client_class = EnvironmentToProjectRewriteClient

    def test_projects_outside_personal_api_key_scoped_organizations_not_listed(self):
        other_org, _, team_in_other_org = Organization.objects.bootstrap(self.user)
        personal_api_key = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="X",
            user=self.user,
            last_used_at="2021-08-25T21:09:14",
            secure_value=hash_key_value(personal_api_key),
            scoped_organizations=[other_org.id],
        )

        response = self.client.get("/api/projects/", HTTP_AUTHORIZATION=f"Bearer {personal_api_key}")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            {project["id"] for project in response.json()["results"]},
            {team_in_other_org.project.id},
            "Only the project belonging to the scoped organization should be listed, the other one should be excluded",
        )

    @patch("posthog.tasks.delete_project.delete_project_async.delay")
    def test_delete_project_queues_async_task(self, mock_delete_task):
        """Test that deleting a project queues an async task instead of deleting synchronously."""
        # Set user as admin to have delete permissions
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        # Create a second team for the project
        second_team = Team.objects.create(organization=self.organization, project=self.project, name="Second Team")

        # Store IDs before deletion
        project_id = self.project.id
        project_name = self.project.name
        organization_id = self.organization.id

        # Delete the project
        response = self.client.delete(f"/api/projects/{self.project.id}/")

        # Should return 204 No Content immediately
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

        # Verify the async task was queued with correct parameters
        mock_delete_task.assert_called_once_with(
            project_id=project_id,
            organization_id=organization_id,
            project_name=project_name,
            user_id=self.user.id,
            was_impersonated=False,
        )

        # Verify project still exists (since task is mocked)
        self.assertTrue(Project.objects.filter(id=project_id).exists())
        self.assertTrue(Team.objects.filter(id=self.team.id).exists())
        self.assertTrue(Team.objects.filter(id=second_team.id).exists())
