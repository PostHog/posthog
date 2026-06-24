from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("agent_platform", "0009_agentsession_agenttoolapprovalrequest_is_preview"),
    ]

    operations = [
        migrations.AddField(
            model_name="agentsession",
            name="search_text",
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="agentsession",
            name="turn_count",
            field=models.IntegerField(db_default=0, default=0),
        ),
    ]
