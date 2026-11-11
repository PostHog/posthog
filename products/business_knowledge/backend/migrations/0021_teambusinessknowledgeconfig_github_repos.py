from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("business_knowledge", "0020_playground_chat"),
    ]

    operations = [
        migrations.AddField(
            model_name="teambusinessknowledgeconfig",
            name="github_integration_id",
            field=models.IntegerField(
                blank=True,
                help_text="GitHub integration id for this environment. Null when GitHub is not connected.",
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="teambusinessknowledgeconfig",
            name="github_repos",
            field=models.JSONField(
                blank=True,
                db_default=[],
                default=list,
                help_text="Lowercased owner/repo names this environment allows business knowledge to read.",
            ),
        ),
    ]
