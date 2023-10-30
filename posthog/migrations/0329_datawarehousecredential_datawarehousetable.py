# Generated by Django 3.2.18 on 2023-06-20 19:20

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import encrypted_fields.fields
import posthog.models.utils


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0328_add_starter_feature_flag_template"),
    ]

    operations = [
        migrations.CreateModel(
            name="DataWarehouseCredential",
            fields=[
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "id",
                    models.UUIDField(
                        default=posthog.models.utils.UUIDT,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    "access_key",
                    encrypted_fields.fields.EncryptedTextField(max_length=500),
                ),
                (
                    "access_secret",
                    encrypted_fields.fields.EncryptedTextField(max_length=500),
                ),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "team",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="posthog.team"),
                ),
            ],
            options={
                "abstract": False,
            },
        ),
        migrations.CreateModel(
            name="DataWarehouseTable",
            fields=[
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("deleted", models.BooleanField(blank=True, null=True)),
                (
                    "id",
                    models.UUIDField(
                        default=posthog.models.utils.UUIDT,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("name", models.CharField(max_length=128)),
                (
                    "format",
                    models.CharField(choices=[("CSV", "CSV"), ("Parquet", "Parquet")], max_length=128),
                ),
                ("url_pattern", models.CharField(max_length=500)),
                (
                    "columns",
                    models.JSONField(
                        blank=True,
                        default=dict,
                        help_text="Dict of all columns with Clickhouse type (including Nullable())",
                        null=True,
                    ),
                ),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "credential",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        to="posthog.datawarehousecredential",
                    ),
                ),
                (
                    "team",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="posthog.team"),
                ),
            ],
            options={
                "abstract": False,
            },
        ),
    ]
