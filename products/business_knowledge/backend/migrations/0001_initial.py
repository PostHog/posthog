import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

import posthog.models.utils


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("posthog", "1112_datadeletionrequest_delete_all_events"),
    ]

    operations = [
        migrations.CreateModel(
            name="KnowledgeSource",
            fields=[
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True, null=True)),
                (
                    "id",
                    models.UUIDField(
                        default=posthog.models.utils.uuid7,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("name", models.CharField(max_length=255)),
                (
                    "source_type",
                    models.CharField(
                        choices=[("text", "Text"), ("url", "URL"), ("file", "File")],
                        max_length=16,
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Pending"),
                            ("processing", "Processing"),
                            ("ready", "Ready"),
                            ("error", "Error"),
                        ],
                        default="pending",
                        max_length=16,
                    ),
                ),
                ("error_message", models.TextField(blank=True, default="")),
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
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="business_knowledge_sources",
                        to="posthog.team",
                    ),
                ),
            ],
            options={
                "db_table": "posthog_business_knowledge_knowledgesource",
                "ordering": ["-created_at"],
            },
        ),
        migrations.CreateModel(
            name="KnowledgeDocument",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=posthog.models.utils.uuid7,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("stable_id", models.CharField(max_length=512)),
                ("title", models.CharField(blank=True, default="", max_length=512)),
                ("content", models.TextField()),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "source",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="documents",
                        to="business_knowledge.knowledgesource",
                    ),
                ),
                (
                    "team",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="+",
                        to="posthog.team",
                    ),
                ),
            ],
            options={
                "db_table": "posthog_business_knowledge_knowledgedocument",
            },
        ),
        migrations.CreateModel(
            name="KnowledgeChunk",
            fields=[
                ("id", models.UUIDField(editable=False, primary_key=True, serialize=False)),
                ("heading_path", models.CharField(blank=True, default="", max_length=1024)),
                ("ordinal", models.IntegerField()),
                ("content", models.TextField()),
                ("char_count", models.IntegerField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "document",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="chunks",
                        to="business_knowledge.knowledgedocument",
                    ),
                ),
                (
                    "source",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="chunks",
                        to="business_knowledge.knowledgesource",
                    ),
                ),
                (
                    "team",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="+",
                        to="posthog.team",
                    ),
                ),
            ],
            options={
                "db_table": "posthog_business_knowledge_knowledgechunk",
            },
        ),
        migrations.AddIndex(
            model_name="knowledgesource",
            index=models.Index(fields=["team", "-created_at"], name="bk_source_team_created"),
        ),
        migrations.AddIndex(
            model_name="knowledgesource",
            index=models.Index(fields=["team", "source_type"], name="bk_source_team_type"),
        ),
        migrations.AddIndex(
            model_name="knowledgedocument",
            index=models.Index(fields=["team", "source"], name="bk_doc_team_source"),
        ),
        migrations.AddIndex(
            model_name="knowledgedocument",
            index=models.Index(fields=["source"], name="bk_doc_source"),
        ),
        migrations.AddConstraint(
            model_name="knowledgedocument",
            constraint=models.UniqueConstraint(fields=("source", "stable_id"), name="bk_doc_unique_per_source"),
        ),
        migrations.AddIndex(
            model_name="knowledgechunk",
            index=models.Index(fields=["team", "source"], name="bk_chunk_team_source"),
        ),
        migrations.AddIndex(
            model_name="knowledgechunk",
            index=models.Index(fields=["document", "ordinal"], name="bk_chunk_doc_ordinal"),
        ),
        migrations.AddConstraint(
            model_name="knowledgechunk",
            constraint=models.UniqueConstraint(
                fields=("document", "heading_path", "ordinal"),
                name="bk_chunk_unique_position",
            ),
        ),
    ]
