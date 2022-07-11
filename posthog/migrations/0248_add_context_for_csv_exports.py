# Generated by Django 3.2.13 on 2022-06-28 14:17

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("posthog", "0247_feature_flags_experience_continuity"),
    ]

    operations = [
        migrations.AddField(
            model_name="exportedasset",
            name="content_location",
            field=models.TextField(blank=True, max_length=1000, null=True),
        ),
        migrations.AddField(
            model_name="exportedasset", name="export_context", field=models.JSONField(blank=True, null=True),
        ),
    ]
