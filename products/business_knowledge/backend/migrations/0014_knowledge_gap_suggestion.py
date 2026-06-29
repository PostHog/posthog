import django.db.models.deletion
from django.db import migrations, models

import posthog.models.utils


class Migration(migrations.Migration):
    dependencies = [
        ("business_knowledge", "0013_bk_source_always_include_index"),
        ("posthog", "1245_duckgres_sink_schema_state"),
    ]

    operations = [
        migrations.CreateModel(
            name="KnowledgeGapSuggestion",
            fields=[
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "id",
                    models.UUIDField(
                        default=posthog.models.utils.uuid7,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("ticket_id", models.UUIDField(db_index=True)),
                ("topic", models.TextField()),
                ("normalized_topic", models.CharField(max_length=255)),
                ("ticket_type", models.CharField(blank=True, default="", max_length=32)),
                ("outcome", models.CharField(blank=True, default="", max_length=32)),
                (
                    "status",
                    models.CharField(
                        choices=[("pending", "Pending"), ("accepted", "Accepted"), ("dismissed", "Dismissed")],
                        default="pending",
                        max_length=16,
                    ),
                ),
                (
                    "resolved_source",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to="business_knowledge.knowledgesource",
                    ),
                ),
                (
                    "team",
                    models.ForeignKey(
                        db_constraint=False,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="business_knowledge_gap_suggestions",
                        to="posthog.team",
                    ),
                ),
            ],
            options={
                "db_table": "posthog_business_knowledge_knowledgegapsuggestion",
                "constraints": [
                    models.UniqueConstraint(
                        fields=("team", "ticket_id", "normalized_topic"),
                        name="bk_gap_unique_per_ticket_topic",
                    ),
                ],
            },
        ),
    ]
