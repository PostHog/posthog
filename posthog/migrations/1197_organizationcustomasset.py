import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

import posthog.models.utils


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1196_team_llm_gateway_enabled_at"),
    ]

    operations = [
        migrations.CreateModel(
            name="OrganizationCustomAsset",
            fields=[
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "id",
                    models.UUIDField(
                        default=posthog.models.utils.uuid7, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("key", models.CharField(max_length=200)),
                ("media_location", models.TextField(blank=True, max_length=1000, null=True)),
                ("content_type", models.TextField(blank=True, max_length=100, null=True)),
                ("file_name", models.TextField(blank=True, max_length=1000, null=True)),
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
                    "organization",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="custom_assets",
                        related_query_name="custom_asset",
                        to="posthog.organization",
                    ),
                ),
            ],
            options={
                "abstract": False,
            },
        ),
    ]
