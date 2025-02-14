# Generated by Django 4.2.18 on 2025-02-13 23:38

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import posthog.models.utils


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0668_hostdefinition_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="FileSystem",
            fields=[
                ("id", models.UUIDField(default=posthog.models.utils.uuid7, primary_key=True, serialize=False)),
                ("path", models.TextField()),
                ("type", models.CharField(blank=True, max_length=100)),
                ("ref", models.CharField(blank=True, max_length=100, null=True)),
                ("href", models.TextField(blank=True, null=True)),
                ("meta", models.JSONField(blank=True, default=dict, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "created_by",
                    models.ForeignKey(
                        null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL
                    ),
                ),
                ("team", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="posthog.team")),
            ],
        ),
    ]
