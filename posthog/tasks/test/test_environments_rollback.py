from unittest.mock import MagicMock, patch

from django.test import TransactionTestCase

from posthog.models import (
    Annotation,
    Dashboard,
    EventDefinition,
    FeatureFlag,
    Insight,
    Project,
    PropertyDefinition,
    Team,
    User,
)
from posthog.models.organization import Organization, OrganizationMembership
from posthog.tasks.environments_rollback import environments_rollback_migration
from posthog.test.test_utils import create_group_type_mapping_without_created_at

from products.early_access_features.backend.models import EarlyAccessFeature


class TestEnvironmentsRollbackTask(TransactionTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.organization = Organization.objects.create(name="Test Organization")
        self.user = User.objects.create_user(
            email="test@posthog.com",
            password="password123",
            first_name="Test",
            last_name="User",
        )
        self.organization_membership = OrganizationMembership.objects.create(
            organization=self.organization,
            user=self.user,
            level=OrganizationMembership.Level.ADMIN,
        )

    @patch("posthog.tasks.environments_rollback.get_client")
    def test_environments_rollback_task_success(self, mock_get_client: MagicMock) -> None:
        # Mock the PostHog client
        mock_posthog_client = MagicMock()
        mock_get_client.return_value = mock_posthog_client

        main_project = Team.objects.create(organization=self.organization, name="Main Project")
        production_env = Team.objects.create(
            organization=self.organization, name="Production", project_id=main_project.id
        )
        staging_env = Team.objects.create(organization=self.organization, name="Staging", project_id=main_project.id)

        staging_insight = Insight.objects.create(team=staging_env, name="Test Insight")
        staging_dashboard = Dashboard.objects.create(team=staging_env, name="Test Dashboard")
        staging_feature_flag = FeatureFlag.objects.create(team=staging_env, name="Test Flag", key="test-flag")
        staging_annotation = Annotation.objects.create(team=staging_env, content="Test Annotation")
        staging_early_access_feature = EarlyAccessFeature.objects.create(team=staging_env, name="Test EAF")

        environments_rollback_migration(
            organization_id=self.organization.id,
            environment_mappings={str(staging_env.id): production_env.id},
            user_id=self.user.id,
        )

        staging_insight.refresh_from_db()
        staging_dashboard.refresh_from_db()
        staging_feature_flag.refresh_from_db()
        staging_annotation.refresh_from_db()
        staging_early_access_feature.refresh_from_db()

        self.assertEqual(staging_insight.team_id, production_env.id)
        self.assertEqual(staging_dashboard.team_id, production_env.id)
        self.assertEqual(staging_feature_flag.team_id, production_env.id)
        self.assertEqual(staging_annotation.team_id, production_env.id)
        self.assertEqual(staging_early_access_feature.team_id, production_env.id)

        staging_env.refresh_from_db()
        self.assertNotEqual(staging_env.project_id, main_project.id)
        self.assertEqual(staging_env.project_id, staging_env.id)

        detached_project = Team.objects.get(id=staging_env.project_id)
        self.assertEqual(detached_project.name, staging_env.name)
        self.assertEqual(detached_project.organization, self.organization)

        mock_get_client.assert_called_once()
        mock_posthog_client.capture.assert_called_once()
        mock_posthog_client.flush.assert_called_once()
        mock_posthog_client.shutdown.assert_called_once()

    @patch("posthog.tasks.environments_rollback.get_client")
    def test_environments_rollback_task_multiple_sources_to_one_target(self, mock_get_client: MagicMock) -> None:
        # Mock the PostHog client
        mock_posthog_client = MagicMock()
        mock_get_client.return_value = mock_posthog_client

        main_project = Team.objects.create(organization=self.organization, name="Main Project")
        production_env = Team.objects.create(
            organization=self.organization, name="Production", project_id=main_project.id
        )
        staging_env = Team.objects.create(organization=self.organization, name="Staging", project_id=main_project.id)
        dev_env = Team.objects.create(organization=self.organization, name="Dev", project_id=main_project.id)

        staging_insight = Insight.objects.create(team=staging_env, name="Staging Insight")
        dev_insight = Insight.objects.create(team=dev_env, name="Dev Insight")
        staging_flag = FeatureFlag.objects.create(team=staging_env, name="Staging Flag", key="staging-flag")
        dev_flag = FeatureFlag.objects.create(team=dev_env, name="Dev Flag", key="dev-flag")

        environments_rollback_migration(
            organization_id=self.organization.id,
            environment_mappings={
                str(staging_env.id): production_env.id,
                str(dev_env.id): production_env.id,
            },
            user_id=self.user.id,
        )

        staging_insight.refresh_from_db()
        dev_insight.refresh_from_db()
        staging_flag.refresh_from_db()
        dev_flag.refresh_from_db()

        self.assertEqual(staging_insight.team_id, production_env.id)
        self.assertEqual(dev_insight.team_id, production_env.id)
        self.assertEqual(staging_flag.team_id, production_env.id)
        self.assertEqual(dev_flag.team_id, production_env.id)

        staging_env.refresh_from_db()
        dev_env.refresh_from_db()
        self.assertNotEqual(staging_env.project_id, main_project.id)
        self.assertNotEqual(dev_env.project_id, main_project.id)
        self.assertEqual(staging_env.project_id, staging_env.id)
        self.assertEqual(dev_env.project_id, dev_env.id)

        mock_get_client.assert_called_once()
        mock_posthog_client.capture.assert_called_once()
        mock_posthog_client.flush.assert_called_once()
        mock_posthog_client.shutdown.assert_called_once()

    @patch("posthog.tasks.environments_rollback.get_client")
    def test_environments_rollback_task_multiple_projects_same_project_pairs(self, mock_get_client: MagicMock) -> None:
        # Mock the PostHog client
        mock_posthog_client = MagicMock()
        mock_get_client.return_value = mock_posthog_client

        project_alpha = Team.objects.create(organization=self.organization, name="Project Alpha")
        project_beta = Team.objects.create(organization=self.organization, name="Project Beta")

        alpha_production_env = Team.objects.create(
            organization=self.organization, name="Alpha Production", project_id=project_alpha.id
        )
        alpha_staging_env = Team.objects.create(
            organization=self.organization, name="Alpha Staging", project_id=project_alpha.id
        )
        beta_production_env = Team.objects.create(
            organization=self.organization, name="Beta Production", project_id=project_beta.id
        )
        beta_staging_env = Team.objects.create(
            organization=self.organization, name="Beta Staging", project_id=project_beta.id
        )

        alpha_staging_insight = Insight.objects.create(team=alpha_staging_env, name="Alpha Staging Insight")
        beta_staging_insight = Insight.objects.create(team=beta_staging_env, name="Beta Staging Insight")
        alpha_staging_flag = FeatureFlag.objects.create(
            team=alpha_staging_env, name="Alpha Staging Flag", key="alpha-staging-flag"
        )
        beta_staging_flag = FeatureFlag.objects.create(
            team=beta_staging_env, name="Beta Staging Flag", key="beta-staging-flag"
        )

        environments_rollback_migration(
            organization_id=self.organization.id,
            environment_mappings={
                str(alpha_staging_env.id): alpha_production_env.id,
                str(beta_staging_env.id): beta_production_env.id,
            },
            user_id=self.user.id,
        )

        alpha_staging_insight.refresh_from_db()
        beta_staging_insight.refresh_from_db()
        alpha_staging_flag.refresh_from_db()
        beta_staging_flag.refresh_from_db()

        self.assertEqual(alpha_staging_insight.team_id, alpha_production_env.id)
        self.assertEqual(beta_staging_insight.team_id, beta_production_env.id)
        self.assertEqual(alpha_staging_flag.team_id, alpha_production_env.id)
        self.assertEqual(beta_staging_flag.team_id, beta_production_env.id)

        alpha_staging_env.refresh_from_db()
        beta_staging_env.refresh_from_db()
        self.assertNotEqual(alpha_staging_env.project_id, project_alpha.id)
        self.assertNotEqual(beta_staging_env.project_id, project_beta.id)
        self.assertEqual(alpha_staging_env.project_id, alpha_staging_env.id)
        self.assertEqual(beta_staging_env.project_id, beta_staging_env.id)

        mock_get_client.assert_called_once()
        mock_posthog_client.capture.assert_called_once()
        mock_posthog_client.flush.assert_called_once()
        mock_posthog_client.shutdown.assert_called_once()

    @patch("posthog.tasks.environments_rollback.get_client")
    def test_environments_rollback_task_same_source_and_target(self, mock_get_client: MagicMock) -> None:
        # Mock the PostHog client
        mock_posthog_client = MagicMock()
        mock_get_client.return_value = mock_posthog_client

        main_project = Team.objects.create(organization=self.organization, name="Main Project")
        production_env = Team.objects.create(
            organization=self.organization, name="Production", project_id=main_project.id
        )

        production_insight = Insight.objects.create(team=production_env, name="Test Insight")

        environments_rollback_migration(
            organization_id=self.organization.id,
            environment_mappings={str(production_env.id): production_env.id},
            user_id=self.user.id,
        )

        production_insight.refresh_from_db()
        self.assertEqual(production_insight.team_id, production_env.id)

        production_env.refresh_from_db()
        self.assertEqual(production_env.project_id, main_project.id)

        mock_get_client.assert_called_once()
        mock_posthog_client.capture.assert_called_once()
        mock_posthog_client.flush.assert_called_once()
        mock_posthog_client.shutdown.assert_called_once()

    @patch("posthog.tasks.environments_rollback.get_client")
    def test_environments_rollback_task_nonexistent_organization(self, mock_get_client: MagicMock) -> None:
        # Mock the PostHog client
        mock_posthog_client = MagicMock()
        mock_get_client.return_value = mock_posthog_client

        nonexistent_organization_id = 99999
        with self.assertRaises(Organization.DoesNotExist):
            environments_rollback_migration(
                organization_id=nonexistent_organization_id,
                environment_mappings={"1": 2},
                user_id=self.user.id,
            )

        mock_get_client.assert_called_once()
        mock_posthog_client.shutdown.assert_called_once()

    @patch("posthog.tasks.environments_rollback.get_client")
    def test_environments_rollback_task_nonexistent_user(self, mock_get_client: MagicMock) -> None:
        # Mock the PostHog client
        mock_posthog_client = MagicMock()
        mock_get_client.return_value = mock_posthog_client

        main_project = Team.objects.create(organization=self.organization, name="Main Project")
        production_env = Team.objects.create(
            organization=self.organization, name="Production", project_id=main_project.id
        )
        staging_env = Team.objects.create(organization=self.organization, name="Staging", project_id=main_project.id)

        nonexistent_user_id = 99999
        with self.assertRaises(User.DoesNotExist):
            environments_rollback_migration(
                organization_id=self.organization.id,
                environment_mappings={str(staging_env.id): production_env.id},
                user_id=nonexistent_user_id,
            )

        mock_get_client.assert_called_once()
        mock_posthog_client.shutdown.assert_called_once()

    @patch("posthog.tasks.environments_rollback.get_client")
    def test_environments_rollback_task_prevents_cross_project_migration(self, mock_get_client: MagicMock) -> None:
        # Mock the PostHog client
        mock_posthog_client = MagicMock()
        mock_get_client.return_value = mock_posthog_client

        project_alpha = Team.objects.create(organization=self.organization, name="Project Alpha")
        project_beta = Team.objects.create(organization=self.organization, name="Project Beta")

        alpha_env = Team.objects.create(organization=self.organization, name="Alpha Env", project_id=project_alpha.id)
        beta_env = Team.objects.create(organization=self.organization, name="Beta Env", project_id=project_beta.id)

        with self.assertRaises(ValueError) as context:
            environments_rollback_migration(
                organization_id=self.organization.id,
                environment_mappings={str(alpha_env.id): beta_env.id},
                user_id=self.user.id,
            )

        self.assertIn("Cannot migrate between different projects", str(context.exception))
        self.assertIn(f"source environment {alpha_env.id}", str(context.exception))
        self.assertIn(f"target environment {beta_env.id}", str(context.exception))

        mock_get_client.assert_called_once()
        mock_posthog_client.shutdown.assert_called_once()

    @patch("posthog.tasks.environments_rollback.get_client")
    def test_environments_rollback_task_main_env_to_secondary(self, mock_get_client: MagicMock) -> None:
        """Test migrating from main environment (team.id == project.id) to secondary environment"""
        mock_posthog_client = MagicMock()
        mock_get_client.return_value = mock_posthog_client

        # Get a unique ID from the sequence to avoid conflicts
        unique_id = Team.objects.increment_id_sequence()

        # Create project and team with the same ID to simulate main environment
        project = Project.objects.create(id=unique_id, organization=self.organization, name="Main Project")
        production_env = Team.objects.create(
            id=unique_id, organization=self.organization, name="Production", project_id=project.id
        )

        staging_env = Team.objects.create(organization=self.organization, name="Staging", project_id=project.id)

        production_insight = Insight.objects.create(team=production_env, name="Production Insight")
        production_dashboard = Dashboard.objects.create(team=production_env, name="Production Dashboard")
        production_feature_flag = FeatureFlag.objects.create(
            team=production_env, name="Production Flag", key="prod-flag"
        )

        environments_rollback_migration(
            organization_id=self.organization.id,
            environment_mappings={str(production_env.id): staging_env.id},
            user_id=self.user.id,
        )

        production_insight.refresh_from_db()
        production_dashboard.refresh_from_db()
        production_feature_flag.refresh_from_db()

        self.assertEqual(production_insight.team_id, staging_env.id)
        self.assertEqual(production_dashboard.team_id, staging_env.id)
        self.assertEqual(production_feature_flag.team_id, staging_env.id)

        staging_env.refresh_from_db()
        production_env.refresh_from_db()

        self.assertEqual(staging_env.project_id, staging_env.id)
        self.assertNotEqual(staging_env.project_id, project.id)

        self.assertEqual(production_env.project_id, project.id)

        staging_project = Project.objects.get(id=staging_env.id)
        self.assertEqual(staging_project.name, "Main Project (Staging)")
        self.assertEqual(staging_project.organization, self.organization)

        mock_get_client.assert_called_once()
        mock_posthog_client.capture.assert_called_once()
        mock_posthog_client.flush.assert_called_once()
        mock_posthog_client.shutdown.assert_called_once()

    @patch("posthog.tasks.environments_rollback.get_client")
    def test_environments_rollback_same_name_logic(self, mock_get_client: MagicMock) -> None:
        """Test that environments with same name as project keep their original names."""
        mock_posthog_client = MagicMock()
        mock_get_client.return_value = mock_posthog_client

        from posthog.models import Project

        # Create project with team that has the same name
        project1 = Project.objects.create(id=500, organization=self.organization, name="Default project")
        same_name_env = Team.objects.create(
            id=501, organization=self.organization, name="Default project", project_id=project1.id
        )
        different_name_env = Team.objects.create(
            id=502, organization=self.organization, name="Development", project_id=project1.id
        )

        # Create another project with different scenario
        project2 = Project.objects.create(id=600, organization=self.organization, name="Analytics")
        analytics_env = Team.objects.create(
            id=601, organization=self.organization, name="Analytics", project_id=project2.id
        )
        staging_env = Team.objects.create(
            id=602, organization=self.organization, name="Staging", project_id=project2.id
        )

        # Run migration
        environment_mappings = {"501": 502, "601": 602}
        environments_rollback_migration(self.organization.id, environment_mappings, self.user.id)

        # Refresh all teams and projects from database
        same_name_env.refresh_from_db()
        different_name_env.refresh_from_db()
        analytics_env.refresh_from_db()
        staging_env.refresh_from_db()
        project1.refresh_from_db()
        project2.refresh_from_db()

        # Verify teams with same name as project keep original names
        self.assertEqual(same_name_env.name, "Default project")
        self.assertEqual(
            same_name_env.project.name, "Default project"
        )  # Project name should be the same as the environment name
        self.assertNotEqual(same_name_env.project.id, project1.id)  # Should be in new project

        # Verify teams with different names get renamed
        self.assertEqual(different_name_env.name, "Default project (Development)")
        self.assertEqual(different_name_env.project.name, "Default project (Development)")
        self.assertEqual(different_name_env.project.id, project1.id)  # Should stay in original project

        # Verify second scenario: Analytics team keeps original name
        self.assertEqual(analytics_env.name, "Analytics")
        self.assertEqual(analytics_env.project.name, "Analytics")
        self.assertNotEqual(analytics_env.project.id, project2.id)  # Should be in new project

        # Verify staging team gets renamed
        self.assertEqual(staging_env.name, "Analytics (Staging)")
        self.assertEqual(staging_env.project.name, "Analytics (Staging)")
        self.assertEqual(staging_env.project.id, project2.id)  # Should stay in original project

        # Verify that the migration completed successfully
        mock_posthog_client.capture.assert_called()
        completion_calls = [
            call
            for call in mock_posthog_client.capture.call_args_list
            if "organization environments rollback completed" in str(call)
        ]
        self.assertEqual(len(completion_calls), 1)

    @patch("posthog.tasks.environments_rollback.get_client")
    def test_event_definition_project_id_update(self, mock_get_client: MagicMock) -> None:
        """Test that EventDefinition project_ids are updated when teams move to new projects"""
        mock_posthog_client = MagicMock()
        mock_get_client.return_value = mock_posthog_client

        main_project = Team.objects.create(organization=self.organization, name="Main Project")
        production_env = Team.objects.create(
            organization=self.organization, name="Production", project_id=main_project.id
        )
        staging_env = Team.objects.create(organization=self.organization, name="Staging", project_id=main_project.id)

        # Create event definitions in both environments
        staging_event = EventDefinition.objects.create(team=staging_env, name="user_signup", project_id=main_project.id)
        production_event = EventDefinition.objects.create(
            team=production_env, name="button_click", project_id=main_project.id
        )
        internal_event = EventDefinition.objects.create(team=staging_env, name="$pageview", project_id=main_project.id)

        environments_rollback_migration(
            organization_id=self.organization.id,
            environment_mappings={str(staging_env.id): production_env.id},
            user_id=self.user.id,
        )

        # Refresh all objects from database
        staging_event.refresh_from_db()
        production_event.refresh_from_db()
        internal_event.refresh_from_db()
        staging_env.refresh_from_db()
        production_env.refresh_from_db()

        # Verify EventDefinitions stay with their original teams but get correct project_ids
        # Staging events should remain on staging team (but staging team was moved to new project)
        self.assertEqual(staging_event.team_id, staging_env.id)  # Stays with original team
        self.assertEqual(internal_event.team_id, staging_env.id)  # Stays with original team
        self.assertEqual(production_event.team_id, production_env.id)  # Stays with original team

        # All EventDefinitions should have project_id matching their team's current project_id
        self.assertEqual(staging_event.project_id, staging_env.project_id)  # Follows team's new project
        self.assertEqual(internal_event.project_id, staging_env.project_id)  # Follows team's new project
        self.assertEqual(production_event.project_id, production_env.project_id)

        # Production team should stay in main project (so team.id != team.project_id in this case)
        self.assertEqual(production_env.project_id, main_project.id)

    @patch("posthog.tasks.environments_rollback.get_client")
    def test_property_definition_project_id_update(self, mock_get_client: MagicMock) -> None:
        """Test that PropertyDefinition project_ids are updated when teams move to new projects"""
        mock_posthog_client = MagicMock()
        mock_get_client.return_value = mock_posthog_client

        main_project = Team.objects.create(organization=self.organization, name="Main Project")
        production_env = Team.objects.create(
            organization=self.organization, name="Production", project_id=main_project.id
        )
        staging_env = Team.objects.create(organization=self.organization, name="Staging", project_id=main_project.id)

        # Create property definitions in both environments
        staging_prop = PropertyDefinition.objects.create(
            team=staging_env, name="user_id", type=PropertyDefinition.Type.EVENT, project_id=main_project.id
        )
        production_prop = PropertyDefinition.objects.create(
            team=production_env,
            name="session_duration",
            type=PropertyDefinition.Type.SESSION,
            project_id=main_project.id,
        )
        person_prop = PropertyDefinition.objects.create(
            team=staging_env, name="email", type=PropertyDefinition.Type.PERSON, project_id=main_project.id
        )

        environments_rollback_migration(
            organization_id=self.organization.id,
            environment_mappings={str(staging_env.id): production_env.id},
            user_id=self.user.id,
        )

        # Refresh all objects from database
        staging_prop.refresh_from_db()
        production_prop.refresh_from_db()
        person_prop.refresh_from_db()
        staging_env.refresh_from_db()
        production_env.refresh_from_db()

        # Verify PropertyDefinitions stay with their original teams but get correct project_ids
        self.assertEqual(staging_prop.team_id, staging_env.id)  # Stays with original team
        self.assertEqual(person_prop.team_id, staging_env.id)  # Stays with original team
        self.assertEqual(production_prop.team_id, production_env.id)  # Stays with original team

        # All PropertyDefinitions should have project_id matching their team's current project_id
        self.assertEqual(staging_prop.project_id, staging_env.project_id)  # Follows team's new project
        self.assertEqual(person_prop.project_id, staging_env.project_id)  # Follows team's new project
        self.assertEqual(production_prop.project_id, production_env.project_id)

        # Production team should stay in main project
        self.assertEqual(production_env.project_id, main_project.id)

    @patch("posthog.tasks.environments_rollback.get_client")
    def test_group_type_mapping_project_id_update(self, mock_get_client: MagicMock) -> None:
        """Test that GroupTypeMapping project_ids are updated when teams move to new projects"""
        mock_posthog_client = MagicMock()
        mock_get_client.return_value = mock_posthog_client

        main_project = Team.objects.create(organization=self.organization, name="Main Project")
        production_env = Team.objects.create(
            organization=self.organization, name="Production", project_id=main_project.id
        )
        staging_env = Team.objects.create(organization=self.organization, name="Staging", project_id=main_project.id)

        # Create group type mappings in both environments
        staging_org_group = create_group_type_mapping_without_created_at(
            team=staging_env,
            group_type="organization",
            group_type_index=0,
            name_singular="Organization",
            name_plural="Organizations",
            project_id=main_project.id,
        )
        staging_company_group = create_group_type_mapping_without_created_at(
            team=staging_env,
            group_type="company",
            group_type_index=1,
            name_singular="Company",
            name_plural="Companies",
            project_id=main_project.id,
        )
        production_workspace_group = create_group_type_mapping_without_created_at(
            team=production_env,
            group_type="workspace",
            group_type_index=2,  # Different index to avoid constraint violation
            name_singular="Workspace",
            name_plural="Workspaces",
            project_id=main_project.id,
        )

        environments_rollback_migration(
            organization_id=self.organization.id,
            environment_mappings={str(staging_env.id): production_env.id},
            user_id=self.user.id,
        )

        # Refresh all objects from database
        staging_org_group.refresh_from_db()
        staging_company_group.refresh_from_db()
        production_workspace_group.refresh_from_db()
        staging_env.refresh_from_db()
        production_env.refresh_from_db()

        # Verify GroupTypeMappings stay with their original teams but get correct project_ids
        self.assertEqual(staging_org_group.team_id, staging_env.id)  # Stays with original team
        self.assertEqual(staging_company_group.team_id, staging_env.id)  # Stays with original team
        self.assertEqual(production_workspace_group.team_id, production_env.id)  # Stays with original team

        # All GroupTypeMappings should have project_id matching their team's current project_id
        self.assertEqual(staging_org_group.project_id, staging_env.project_id)  # Follows team's new project
        self.assertEqual(staging_company_group.project_id, staging_env.project_id)  # Follows team's new project
        self.assertEqual(production_workspace_group.project_id, production_env.project_id)

        # Verify group type indices remain the same
        self.assertEqual(staging_org_group.group_type_index, 0)
        self.assertEqual(staging_company_group.group_type_index, 1)
        self.assertEqual(production_workspace_group.group_type_index, 2)

        # Production team should stay in main project
        self.assertEqual(production_env.project_id, main_project.id)
