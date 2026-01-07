from posthog.test.base import BaseTest
from unittest import mock

from posthog.models.project import Project
from posthog.models.team.team import Team
import pytest


class TestProject(BaseTest):
    def test_create_project_with_team_no_team_fields(self):
        project, team = Project.objects.create_with_team(
            initiating_user=self.user,
            organization=self.organization,
            name="Test project",
        )

        assert project.id == team.id
        assert project.name == "Test project"
        assert project.organization == self.organization

        self.assertEqual(
            team.name,
            "Test project",  # TODO: When Environments are rolled out, ensure this says "Default environment"
        )
        assert team.organization == self.organization
        assert team.project == project

    def test_create_project_with_team_uses_team_id_sequence(self):
        expected_common_id = Team.objects.increment_id_sequence() + 1

        project, team = Project.objects.create_with_team(
            initiating_user=self.user,
            organization=self.organization,
            name="Test project",
            team_fields={"name": "Test team"},
        )

        assert project.id == expected_common_id
        assert project.name == "Test project"
        assert project.organization == self.organization

        assert team.id == expected_common_id
        assert team.name == "Test team"
        assert team.organization == self.organization
        assert team.project == project

    @mock.patch("posthog.models.team.team.Team.objects.create", side_effect=Exception)
    def test_create_project_with_team_does_not_create_if_team_fails(self, mock_create):
        initial_team_count = Team.objects.count()
        initial_project_count = Project.objects.count()

        with pytest.raises(Exception):
            Project.objects.create_with_team(
                initiating_user=self.user,
                organization=self.organization,
                name="Test project",
                team_fields={"name": "Test team"},
            )

        assert Team.objects.count() == initial_team_count
        assert Project.objects.count() == initial_project_count
