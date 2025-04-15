# Generated by Django 4.2.18 on 2025-04-15 08:14

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0708_add_trigger_match_type"),
    ]

    operations = [
        migrations.AddField(
            model_name="alertconfiguration",
            name="notification_destinations",
            field=models.ManyToManyField(
                blank=True,
                help_text="Hog functions to trigger when the alert is fired",
                related_name="alert_configurations_notifications",
                to="posthog.hogfunction",
            ),
        ),
    ]
