# Generated by Django 4.2.15 on 2024-11-19 12:03

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("posthog", "0521_alter_errortrackingstackframe_context")]

    operations = [
        migrations.AddField(
            model_name="hogfunction",
            name="transpiled",
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name="hogfunction",
            name="type",
            field=models.CharField(
                blank=True,
                choices=[
                    ("destination", "Destination"),
                    ("site_destination", "Site Destination"),
                    ("site_app", "Site App"),
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
    ]
