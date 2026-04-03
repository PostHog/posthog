# Generated manually for detector config fields

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1053_backfill_experiment_saved_metric_uuids"),
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
        migrations.AddField(
            model_name="alertcheck",
            name="triggered_dates",
            field=models.JSONField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="alertcheck",
            name="interval",
            field=models.CharField(blank=True, max_length=10, null=True),
        ),
    ]
