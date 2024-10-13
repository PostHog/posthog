# Generated by Django 4.2.15 on 2024-10-13 18:36

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0486_cohort_last_error_at"),
    ]

    operations = [
        migrations.AlterField(
            model_name="integration",
            name="kind",
            field=models.CharField(
                choices=[
                    ("slack", "Slack"),
                    ("salesforce", "Salesforce"),
                    ("hubspot", "Hubspot"),
                    ("google-pubsub", "Google Pubsub"),
                    ("google-cloud-storage", "Google Cloud Storage"),
                    ("google-ads", "Google Ads"),
                ],
                max_length=20,
            ),
        ),
    ]
