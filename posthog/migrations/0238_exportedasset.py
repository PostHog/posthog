# Generated by Django 3.2.12 on 2022-05-25 13:59

import django.db.models.deletion
from django.db import migrations, models

import posthog.models.exported_asset


class Migration(migrations.Migration):

    dependencies = [
        ("posthog", "0237_remove_timezone_from_teams"),
    ]

    operations = [
        migrations.CreateModel(
            name="ExportedAsset",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "export_format",
                    models.CharField(
                        choices=[
                            ("image/png", "image/png"),
                            ("application/pdf", "application/pdf"),
                            ("text/csv", "text/csv"),
                        ],
                        max_length=16,
                    ),
                ),
                ("content", models.BinaryField(null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "access_token",
                    models.CharField(
                        blank=True,
                        default=posthog.models.exported_asset.get_default_access_token,
                        max_length=400,
                        null=True,
                    ),
                ),
                (
                    "dashboard",
                    models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, to="posthog.dashboard"),
                ),
                (
                    "insight",
                    models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, to="posthog.insight"),
                ),
                ("team", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="posthog.team")),
            ],
        ),
    ]
