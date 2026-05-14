# Generated manually for Deployments GitHub repository tracking indexes.

from django.contrib.postgres.operations import AddIndexConcurrently
from django.db import migrations, models


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("deployments", "0005_deploymentproject_github_tracking"),
    ]

    operations = [
        AddIndexConcurrently(
            model_name="deploymentproject",
            index=models.Index(fields=("team_id", "github_integration_id"), name="deploy_project_team_int_idx"),
        ),
    ]
