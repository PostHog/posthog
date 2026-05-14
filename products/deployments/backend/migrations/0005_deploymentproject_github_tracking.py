# Generated manually for Deployments GitHub repository tracking.

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("deployments", "0004_alter_deploymentevent_managers_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="deploymentproject",
            name="github_repo_id",
            field=models.BigIntegerField(blank=True, null=True),
        ),
        migrations.AddIndex(
            model_name="deploymentproject",
            index=models.Index(fields=("team_id", "github_integration_id"), name="deploy_project_team_int_idx"),
        ),
        migrations.AddConstraint(
            model_name="deploymentproject",
            constraint=models.UniqueConstraint(
                condition=models.Q(("github_repo_id__isnull", False))
                & (models.Q(("deleted", False)) | models.Q(("deleted__isnull", True))),
                fields=("team_id", "github_repo_id", "default_branch"),
                name="deploy_project_team_repo_branch_uniq",
            ),
        ),
    ]
