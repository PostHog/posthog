# Generated manually for Deployments GitHub repository tracking indexes.

from django.db import migrations, models

from posthog.migration_helpers import CreateIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("deployments", "0005_deploymentproject_github_tracking"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddIndex(
                    model_name="deploymentproject",
                    index=models.Index(fields=("team_id", "github_integration_id"), name="deploy_project_team_int_idx"),
                ),
            ],
            database_operations=[
                CreateIndexConcurrently(
                    index_name="deploy_project_team_int_idx",
                    table_name="deployments_deploymentproject",
                    columns="(team_id, github_integration_id)",
                ),
            ],
        ),
    ]
