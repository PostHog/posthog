# Generated manually for detector config fields

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0952_add_billable_action_to_hogflows"),
    ]

    operations = [
        migrations.AddField(
            model_name="alertconfiguration",
            name="detector_config",
            field=models.JSONField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="alertcheck",
            name="anomaly_scores",
            field=models.JSONField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="alertcheck",
            name="triggered_points",
            field=models.JSONField(blank=True, null=True),
        ),
    ]
