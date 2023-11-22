# Generated by Django 3.2.19 on 2023-11-17 15:56

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import posthog.models.utils


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0366_alter_action_created_by"),
    ]

    operations = [
        migrations.AddField(
            model_name="externaldatasource",
            name="job_inputs",
            field=models.JSONField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name="team",
            name="timezone",
            field=models.CharField(
                choices=posthog.models.team.TIMEZONES,
                default="UTC",
                max_length=240,
            ),
        ),
        migrations.CreateModel(
            name="ExternalDataJob",
            fields=[
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "id",
                    models.UUIDField(
                        default=posthog.models.utils.UUIDT, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("status", models.CharField(max_length=400)),
                ("rows_synced", models.BigIntegerField(blank=True, null=True)),
                (
                    "latest_error",
                    models.TextField(help_text="The latest error that occurred during this run.", null=True),
                ),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL
                    ),
                ),
                (
                    "pipeline",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="posthog.externaldatasource"),
                ),
                ("team", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="posthog.team")),
            ],
            options={
                "abstract": False,
            },
        ),
    ]
