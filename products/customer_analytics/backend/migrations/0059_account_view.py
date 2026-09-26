import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

import posthog.uuidt


class Migration(migrations.Migration):
    dependencies = [
        (
            "customer_analytics",
            "0058_accountrelationshipdefinition_claim_saved_query_sha256",
        ),
        ("posthog", "1377_untrack_superseded_experiment_settings"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="AccountView",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=posthog.uuidt.uuid7,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("name", models.CharField(max_length=400)),
                (
                    "visibility",
                    models.CharField(
                        choices=[("private", "Personal"), ("team", "Team")],
                        default="private",
                        max_length=16,
                    ),
                ),
                ("content", models.JSONField()),
                ("text_content", models.TextField(db_default="", default="")),
                ("version", models.PositiveIntegerField(db_default=1, default=1)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("deleted_at", models.DateTimeField(blank=True, null=True)),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        db_constraint=False,
                        db_index=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "last_modified_by",
                    models.ForeignKey(
                        blank=True,
                        db_constraint=False,
                        db_index=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "team",
                    models.ForeignKey(
                        db_constraint=False,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="+",
                        to="posthog.team",
                    ),
                ),
            ],
            options={
                "indexes": [
                    models.Index(
                        fields=["team", "deleted_at", "visibility"],
                        name="ca_account_view_list_idx",
                    ),
                    models.Index(
                        fields=["team", "created_by", "deleted_at"],
                        name="ca_account_view_owner_idx",
                    ),
                ],
            },
        ),
    ]
