# Generated by Django 3.2.19 on 2023-08-17 20:42

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("posthog", "0342_alter_featureflag_usage_dashboard"),
    ]

    operations = [
        migrations.AddField(
            model_name="team",
            name="has_completed_onboarding_for",
            field=models.JSONField(blank=True, null=True),
        ),
    ]
