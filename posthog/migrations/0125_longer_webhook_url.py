# Generated by Django 3.0.11 on 2021-02-11 11:32

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0124_unset_is_calculating_static_cohorts"),
    ]

    operations = [
        migrations.AlterField(
            model_name="team",
            name="slack_incoming_webhook",
            field=models.CharField(blank=True, max_length=500, null=True),
        ),
    ]
