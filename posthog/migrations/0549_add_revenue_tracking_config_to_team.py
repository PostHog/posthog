# Generated by Django 4.2.15 on 2025-01-15 21:53

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0548_migrate_early_access_features"),
    ]

    operations = [
        migrations.AddField(
            model_name="team",
            name="revenue_tracking_config",
            field=models.JSONField(blank=True, null=True),
        ),
    ]
