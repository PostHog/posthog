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
    ]
