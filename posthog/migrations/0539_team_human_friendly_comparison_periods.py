# Generated by Django 4.2.15 on 2024-12-27 19:22

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0538_experiment_stats_config"),
    ]

    operations = [
        migrations.AddField(
            model_name="team",
            name="human_friendly_comparison_periods",
            field=models.BooleanField(default=False, null=True, blank=True),
        ),
    ]
