# Generated by Django 4.2.15 on 2024-10-10 17:48

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0486_cohort_last_error_at"),
    ]

    operations = [
        migrations.AddField(
            model_name="team",
            name="survey_config",
            field=models.JSONField(blank=True, null=True),
        ),
    ]
