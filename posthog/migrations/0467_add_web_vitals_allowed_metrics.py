# Generated by Django 4.2.15 on 2024-09-08 10:10

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0466_alter_externaldatasource_source_type"),
    ]

    operations = [
        migrations.AddField(
            model_name="team",
            name="autocapture_web_vitals_allowed_metrics",
            field=models.JSONField(blank=True, null=True),
        ),
    ]
