from typing import Any

from posthog.test.base import NonAtomicTestMigrations

from django.db import connection
from django.db.migrations.executor import MigrationExecutor


# Non-atomic: the ALTER TABLE in 0026 cannot run in the same transaction as the FK-bearing
# fixture inserts (pending trigger events).
class RemoveTrialEvaluationsMigrationTest(NonAtomicTestMigrations):
    migrate_from = "0023_llmpromptlabel"
    migrate_to = "0026_retire_trial_columns"

    CLASS_DATA_LEVEL_SETUP = False

    @property
    def app(self) -> str:
        return "ai_observability"

    def setUpBeforeMigration(self, apps: Any) -> None:
        Organization = apps.get_model("posthog", "Organization")
        Project = apps.get_model("posthog", "Project")
        Team = apps.get_model("posthog", "Team")
        Evaluation = apps.get_model("ai_observability", "Evaluation")
        EvaluationConfig = apps.get_model("ai_observability", "EvaluationConfig")

        org = Organization.objects.create(name="Test Organization")
        project = Project.objects.create(id=999_998, organization=org, name="Test Project")
        team = Team.objects.create(organization=org, project=project, name="Test Team")
        self.team_id = team.id
        self.organization_id = org.id
        self.project_id = project.id

        EvaluationConfig.objects.create(team=team, trial_eval_limit=100, trial_evals_used=50)

        def create_evaluation(name: str, status_reason: str, detail: str) -> Any:
            return Evaluation.objects.create(
                team=team,
                name=name,
                evaluation_type="llm_judge",
                output_type="boolean",
                enabled=False,
                status="error",
                status_reason=status_reason,
                status_reason_detail=detail,
            )

        self.trial_limit_eval_id = create_evaluation(
            "trial limit", "trial_limit_reached", "Trial evaluation limit reached."
        ).id
        self.model_not_allowed_eval_id = create_evaluation(
            "model not allowed", "model_not_allowed", "Model not on the trial plan."
        ).id
        self.control_eval_id = create_evaluation("control", "provider_key_deleted", "Key was deleted.").id

    def test_migration(self) -> None:
        assert self.apps is not None
        Evaluation = self.apps.get_model("ai_observability", "Evaluation")
        EvaluationConfig = self.apps.get_model("ai_observability", "EvaluationConfig")
        Team = self.apps.get_model("posthog", "Team")

        for eval_id in (self.trial_limit_eval_id, self.model_not_allowed_eval_id):
            migrated = Evaluation.objects.get(id=eval_id)
            self.assertEqual(migrated.status_reason, "provider_key_required")
            self.assertIsNone(migrated.status_reason_detail)

        control = Evaluation.objects.get(id=self.control_eval_id)
        self.assertEqual(control.status_reason, "provider_key_deleted")
        self.assertEqual(control.status_reason_detail, "Key was deleted.")

        # New configs no longer know about the retired columns, so the insert must be absorbed by
        # their DB defaults — pods on the previous release read these columns and must never see NULL.
        post_migration_team = Team.objects.create(
            organization_id=self.organization_id, project_id=self.project_id, name="Post-migration team"
        )
        EvaluationConfig.objects.create(team=post_migration_team)
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT trial_eval_limit, trial_evals_used FROM llm_analytics_evaluationconfig WHERE team_id = %s",
                [post_migration_team.id],
            )
            self.assertEqual(cursor.fetchone(), (100, 0))

        # Reverse (SET NOT NULL) must not trip over rows created after the columns were retired.
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate([(self.app, self.migrate_from)])

        old_apps = executor.loader.project_state([(self.app, self.migrate_from)]).apps
        OldEvaluationConfig = old_apps.get_model("ai_observability", "EvaluationConfig")
        self.assertEqual(OldEvaluationConfig.objects.get(team_id=post_migration_team.id).trial_eval_limit, 100)
        self.assertEqual(OldEvaluationConfig.objects.get(team_id=self.team_id).trial_evals_used, 50)
