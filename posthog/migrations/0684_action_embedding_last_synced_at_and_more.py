# Generated by Django 4.2.18 on 2025-03-10 18:45

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("posthog", "0683_externaldataschema_sync_time_of_day")]

    operations = [
        migrations.AddField(
            model_name="action",
            name="embedding_last_synced_at",
            field=models.DateTimeField(
                blank=True, help_text="The last time the action was synced to the vector database", null=True
            ),
        ),
        migrations.AddField(
            model_name="action",
            name="last_summarized_at",
            field=models.DateTimeField(
                blank=True, help_text="The last time the action was summarized by AI", null=True
            ),
        ),
        migrations.AddField(
            model_name="action",
            name="summary",
            field=models.TextField(blank=True, help_text="A summary of the action, generated by AI", null=True),
        ),
    ]
