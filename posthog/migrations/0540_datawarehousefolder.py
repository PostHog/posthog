# Generated by Django 4.2.15 on 2025-01-09 16:06

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone
import posthog.models.utils


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0539_user_role_at_organization"),
    ]

    operations = [
        migrations.CreateModel(
            name="DataWarehouseFolder",
            fields=[
                ("deleted", models.BooleanField(blank=True, default=False, null=True)),
                ("deleted_at", models.DateTimeField(blank=True, null=True)),
                (
                    "id",
                    models.UUIDField(
                        default=posthog.models.utils.UUIDT, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("name", models.CharField(max_length=255)),
                ("items", models.JSONField(default=list)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL
                    ),
                ),
                (
                    "parent",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="children",
                        to="posthog.datawarehousefolder",
                    ),
                ),
                (
                    "team",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE, related_name="warehouse_folders", to="posthog.team"
                    ),
                ),
            ],
            options={
                "ordering": ["name"],
                "unique_together": {("team", "name", "parent")},
            },
        ),
    ]
