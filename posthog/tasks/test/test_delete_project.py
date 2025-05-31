from unittest.mock import patch

from django.test import TestCase

from posthog.models import Project, User, Team, Organization, OrganizationMembership
from posthog.models.async_deletion import AsyncDeletion, DeletionType
from posthog.tasks.delete_project import delete_project_async


class TestDeleteProjectTask(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(name="Test Org")
        self.user = User.objects.create_user(email="test@example.com", password="testpass")
        OrganizationMembership.objects.create(
            user=self.user, organization=self.organization, level=OrganizationMembership.Level.ADMIN
        )

        # Create a project with teams
        self.project = Project.objects.create(
            name="Test Project",
            organization=self.organization,
        )
        self.team1 = Team.objects.create(
            name="Team 1",
            organization=self.organization,
            project=self.project,
        )
        self.team2 = Team.objects.create(
            name="Team 2",
            organization=self.organization,
            project=self.project,
        )

    @patch("posthog.tasks.delete_project.delete_bulky_postgres_data")
    @patch("posthog.tasks.delete_project.delete_batch_exports")
    @patch("posthog.tasks.delete_project.log_activity")
    @patch("posthog.tasks.delete_project.report_user_action")
    def test_delete_project_async_success(
        self, mock_report_user_action, mock_log_activity, mock_delete_batch_exports, mock_delete_bulky_postgres_data
    ):
        # Call the task
        delete_project_async(
            project_id=self.project.id,
            organization_id=self.organization.id,
            project_name=self.project.name,
            user_id=self.user.id,
            was_impersonated=False,
        )

        # Verify project was deleted
        self.assertFalse(Project.objects.filter(id=self.project.id).exists())

        # Verify teams were deleted
        self.assertFalse(Team.objects.filter(project=self.project).exists())

        # Verify bulk deletion functions were called
        mock_delete_bulky_postgres_data.assert_called_once()
        mock_delete_batch_exports.assert_called_once()

        # Verify AsyncDeletion entries were created
        async_deletions = AsyncDeletion.objects.filter(deletion_type=DeletionType.Team, created_by=self.user)
        self.assertEqual(async_deletions.count(), 2)

        # Verify activity logging
        self.assertEqual(mock_log_activity.call_count, 3)  # 2 teams + 1 project
        self.assertEqual(mock_report_user_action.call_count, 3)  # 2 teams + 1 project

    @patch("posthog.tasks.delete_project.logger")
    def test_delete_project_async_already_deleted(self, mock_logger):
        # Delete the project first
        project_id = self.project.id
        self.project.delete()

        # Call the task
        delete_project_async(
            project_id=project_id,
            organization_id=self.organization.id,
            project_name="Test Project",
            user_id=self.user.id,
            was_impersonated=False,
        )

        # Verify warning was logged
        mock_logger.warning.assert_called_once_with("Project already deleted", project_id=project_id)

    @patch("posthog.tasks.delete_project.logger")
    def test_delete_project_async_user_not_found(self, mock_logger):
        # Call the task with non-existent user
        delete_project_async(
            project_id=self.project.id,
            organization_id=self.organization.id,
            project_name=self.project.name,
            user_id=99999,
            was_impersonated=False,
        )

        # Verify error was logged
        mock_logger.error.assert_called_once_with(
            "User not found for project deletion", user_id=99999, project_id=self.project.id
        )

        # Verify project was still deleted
        self.assertFalse(Project.objects.filter(id=self.project.id).exists())

        # Verify no AsyncDeletion entries were created (since user is None)
        self.assertEqual(AsyncDeletion.objects.count(), 0)
