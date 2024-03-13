from posthog.models.project import Project
from posthog.models.team.team import Team
from posthog.test.base import BaseTest


class TestProject(BaseTest):
    def test_create_project_with_team_no_team_fields(self):
        project, team = Project.objects.create_with_team(
            organization=self.organization,
            name="Test project",
        )

        self.assertEqual(project.id, team.id)
        self.assertEqual(project.name, "Test project")
        self.assertEqual(project.organization, self.organization)

        self.assertEqual(
            team.name,
            "Default project",  # TODO: When Environments are rolled out, ensure this says "Default environment"
        )
        self.assertEqual(team.organization, self.organization)
        self.assertEqual(team.project, project)

    def test_create_project_with_team_with_team_fields(self):
        project, team = Project.objects.create_with_team(
            organization=self.organization,
            name="Test project",
            team_fields={"name": "Test team", "access_control": True},
        )

        self.assertEqual(project.id, team.id)
        self.assertEqual(project.name, "Test project")
        self.assertEqual(project.organization, self.organization)

        self.assertEqual(team.name, "Test team")
        self.assertEqual(team.organization, self.organization)
        self.assertEqual(team.project, project)
        self.assertEqual(team.access_control, True)

    def test_create_project_with_team_uses_team_id_sequence(self):
        expected_common_id = Team.objects.increment_id_sequence() + 1

        project, team = Project.objects.create_with_team(
            organization=self.organization,
            name="Test project",
            team_fields={"name": "Test team", "access_control": True},
        )

        self.assertEqual(project.id, expected_common_id)
        self.assertEqual(project.name, "Test project")
        self.assertEqual(project.organization, self.organization)

        self.assertEqual(team.id, expected_common_id)
        self.assertEqual(team.name, "Test team")
        self.assertEqual(team.organization, self.organization)
        self.assertEqual(team.project, project)
        self.assertEqual(team.access_control, True)
