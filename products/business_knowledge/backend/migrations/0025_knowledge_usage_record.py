from django.db import migrations, models

import posthog.uuidt


class Migration(migrations.Migration):
    dependencies = [
        ("business_knowledge", "0024_knowledge_libraries"),
    ]

    operations = [
        migrations.CreateModel(
            name="KnowledgeUsageRecord",
            fields=[
                (
                    "id",
                    models.UUIDField(default=posthog.uuidt.uuid7, editable=False, primary_key=True, serialize=False),
                ),
                ("team_id", models.BigIntegerField()),
                (
                    "usage_key",
                    models.CharField(
                        choices=[
                            ("business_knowledge_chunks", "Chunks ingested"),
                            ("business_knowledge_queries", "Queries"),
                        ],
                        max_length=64,
                    ),
                ),
                ("quantity", models.PositiveIntegerField()),
                ("surface", models.CharField(blank=True, default="", max_length=32)),
                ("idempotency_key", models.CharField(blank=True, max_length=128, null=True)),
                ("source_id", models.UUIDField(blank=True, null=True)),
                ("document_id", models.UUIDField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "db_table": "posthog_business_knowledge_knowledgeusagerecord",
                "indexes": [
                    models.Index(fields=["created_at", "team_id"], name="bk_usage_created_team"),
                    models.Index(fields=["team_id", "usage_key", "created_at"], name="bk_usage_team_key_created"),
                ],
                "constraints": [
                    models.UniqueConstraint(
                        condition=models.Q(("idempotency_key__isnull", False)),
                        fields=("usage_key", "idempotency_key"),
                        name="bk_usage_idempotency_key",
                    )
                ],
            },
        ),
    ]
