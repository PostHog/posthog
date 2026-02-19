import django.db.models.deletion
import django.contrib.postgres.fields
from django.conf import settings
from django.db import migrations, models

import posthog.models.utils


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1013_eventdefinition_enforcement_mode_db_default"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="HogFunctionUserTemplate",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=posthog.models.utils.UUIDT,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("name", models.CharField(max_length=400)),
                ("description", models.TextField(blank=True, default="")),
                ("icon_url", models.TextField(blank=True, null=True)),
                (
                    "tags",
                    django.contrib.postgres.fields.ArrayField(
                        base_field=models.CharField(max_length=255),
                        blank=True,
                        default=list,
                        size=None,
                    ),
                ),
                (
                    "scope",
                    models.CharField(
                        choices=[("team", "Only team"), ("organization", "Organization")],
                        default="team",
                        max_length=24,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("type", models.CharField(max_length=50)),
                ("hog", models.TextField()),
                ("inputs_schema", models.JSONField(default=list)),
                ("inputs", models.JSONField(blank=True, null=True)),
                ("filters", models.JSONField(blank=True, null=True)),
                ("mappings", models.JSONField(blank=True, null=True)),
                ("masking", models.JSONField(blank=True, null=True)),
                (
                    "team",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        to="posthog.team",
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
            ],
            options={
                "indexes": [
                    models.Index(fields=["team"], name="posthog_hogf_team_id_idx_ut"),
                ],
            },
        ),
    ]
