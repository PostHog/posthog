# Generated manually for Deployments GitHub repository uniqueness.

from django.db import migrations, models


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("deployments", "0006_deploymentproject_github_indexes_concurrent"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddConstraint(
                    model_name="deploymentproject",
                    constraint=models.UniqueConstraint(
                        condition=models.Q(("github_repo_id__isnull", False))
                        & (models.Q(("deleted", False)) | models.Q(("deleted__isnull", True))),
                        fields=("team_id", "github_repo_id"),
                        name="deploy_project_team_repo_uniq",
                    ),
                ),
            ],
            database_operations=[
                migrations.RunSQL(
                    sql="""
                    CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS "deploy_project_team_repo_uniq"
                    ON "deployments_deploymentproject" ("team_id", "github_repo_id")
                    WHERE ("github_repo_id" IS NOT NULL AND (NOT "deleted" OR "deleted" IS NULL));
                    """,
                    reverse_sql='DROP INDEX CONCURRENTLY IF EXISTS "deploy_project_team_repo_uniq";',
                ),
            ],
        ),
    ]
