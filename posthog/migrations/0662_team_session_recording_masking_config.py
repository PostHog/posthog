# Generated by Django 4.2.18 on 2025-02-12 11:08

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0661_errortrackingissuefingerprintv2_first_seen"),
    ]

    operations = [
        migrations.AddField(
            model_name="team",
            name="session_recording_masking_config",
            field=models.JSONField(blank=True, null=True),
        ),
    ]
