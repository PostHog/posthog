# Generated by Django 4.2.14 on 2024-09-06 12:14

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0468_integration_google_pubsub"),
    ]

    operations = [
        migrations.AddField(
            model_name="datawarehousesavedquery",
            name="last_run_at",
            field=models.DateTimeField(help_text="The timestamp of this SavedQuery's last run (if any).", null=True),
        ),
        migrations.AddField(
            model_name="datawarehousesavedquery",
            name="status",
            field=models.CharField(
                choices=[
                    ("Cancelled", "Cancelled"),
                    ("Completed", "Completed"),
                    ("Failed", "Failed"),
                    ("Running", "Running"),
                ],
                help_text="The status of when this SavedQuery last ran.",
                max_length=64,
                null=True,
            ),
        ),
    ]
