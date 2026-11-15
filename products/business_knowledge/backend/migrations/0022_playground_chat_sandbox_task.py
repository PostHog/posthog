from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("business_knowledge", "0021_teambusinessknowledgeconfig_github_repos"),
    ]

    operations = [
        migrations.AddField(
            model_name="playgroundchat",
            name="task_id",
            field=models.UUIDField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="playgroundturn",
            name="run_id",
            field=models.UUIDField(blank=True, null=True),
        ),
        migrations.RemoveConstraint(
            model_name="playgroundturn",
            name="bk_pg_turn_task_id",
        ),
    ]
