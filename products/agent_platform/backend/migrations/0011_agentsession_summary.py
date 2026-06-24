from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("agent_platform", "0010_agentsession_search_text_turn_count"),
    ]

    operations = [
        migrations.AddField(
            model_name="agentsession",
            name="summary",
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="agentsession",
            name="summary_topic",
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="agentsession",
            name="summary_outcome",
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="agentsession",
            name="summary_generated_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
