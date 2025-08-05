# Generated migration to move Vercel models to EE

from django.db import migrations, models
import django.db.models.deletion
import posthog.models.utils


class Migration(migrations.Migration):
    dependencies = [("ee", "0026_conversation_created_at_conversation_title_and_more")]

    operations = [
        migrations.CreateModel(
            name="VercelInstallation",
            fields=[
                ("updated_at", models.DateTimeField(auto_now=True, null=True)),
                (
                    "id",
                    models.UUIDField(
                        default=posthog.models.utils.UUIDT, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("installation_id", models.CharField(max_length=255, unique=True)),
                ("billing_plan_id", models.CharField(blank=True, max_length=255, null=True)),
                ("upsert_data", models.JSONField(default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "organization",
                    models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, to="posthog.organization"),
                ),
            ],
            options={
                "abstract": False,
            },
        ),
        migrations.CreateModel(
            name="VercelResource",
            fields=[
                ("updated_at", models.DateTimeField(auto_now=True, null=True)),
                (
                    "id",
                    models.UUIDField(
                        default=posthog.models.utils.UUIDT, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("resource_id", models.CharField(max_length=255, unique=True)),
                ("config", models.JSONField(default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "installation",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="resources",
                        to="ee.vercelinstallation",
                    ),
                ),
                ("team", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, to="posthog.team")),
            ],
            options={
                "abstract": False,
            },
        ),
    ]
