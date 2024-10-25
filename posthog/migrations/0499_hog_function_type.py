# Generated by Django 4.2.15 on 2024-10-24 11:05

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0498_errortrackingissuefingerprint_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="hogfunction",
            name="type",
            field=models.CharField(
                blank=True,
                choices=[
                    ("destination", "Destination"),
                    ("email", "Email"),
                    ("sms", "Sms"),
                    ("push", "Push"),
                    ("activity", "Activity"),
                    ("alert", "Alert"),
                    ("broadcast", "Broadcast"),
                ],
                max_length=24,
                null=True,
            ),
        ),
        migrations.RunSQL("UPDATE posthog_hogfunction SET type = 'destination' WHERE type IS NULL", "SELECT 1"),
    ]
