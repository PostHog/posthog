import django.db.models.deletion
from django.db import migrations, models

import posthog.models.utils


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0711_externaldatasource_revenue_analytics_enabled"),
    ]

    operations = [
        migrations.CreateModel(
            name="MessageTemplate",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=posthog.models.utils.UUIDT, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("name", models.CharField(max_length=400)),
                ("description", models.TextField(blank=True, default="")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("content", models.JSONField(default=dict)),
                ("type", models.CharField(blank=True, max_length=24, default="email")),
                ("deleted", models.BooleanField(default=False)),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to="posthog.user"
                    ),
                ),
                ("team", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="posthog.team")),
            ],
        ),
    ]
