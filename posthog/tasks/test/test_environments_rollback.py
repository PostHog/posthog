from django.test import TransactionTestCase

from posthog.models import Team, User, Insight, Dashboard, FeatureFlag, Annotation, EarlyAccessFeature
from posthog.models.organization import Organization, OrganizationMembership
from posthog.tasks.environments_rollback import environments_rollback_migration


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

    def test_environments_rollback_task_success(self) -> None:
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

    def test_environments_rollback_task_multiple_sources_to_one_target(self) -> None:
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

    def test_environments_rollback_task_multiple_projects_same_project_pairs(self) -> None:
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

    def test_environments_rollback_task_same_source_and_target(self) -> None:
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

    def test_environments_rollback_task_nonexistent_organization(self) -> None:
        nonexistent_organization_id = 99999
        with self.assertRaises(Organization.DoesNotExist):
            environments_rollback_migration(
                organization_id=nonexistent_organization_id,
                environment_mappings={"1": 2},
                user_id=self.user.id,
            )

    def test_environments_rollback_task_nonexistent_user(self) -> None:
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

    def test_environments_rollback_task_prevents_cross_project_migration(self) -> None:
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
