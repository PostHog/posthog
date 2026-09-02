import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

import posthog.models.utils


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("posthog", "1314_callable_choices"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="AEOPrompt",
            fields=[
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True, null=True)),
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
                    "prompt",
                    models.TextField(help_text="The question to ask the answer engines, as a user would phrase it."),
                ),
                (
                    "prompt_hash",
                    models.CharField(
                        help_text="SHA-256 of the normalized prompt text; dedupe key and the stable join key on citation-check events.",
                        max_length=64,
                    ),
                ),
                (
                    "prompt_source",
                    models.CharField(
                        choices=[
                            ("user_reported", "User reported"),
                            ("ai_entry_page", "AI entry page"),
                            ("crawled_content", "Crawled content"),
                            ("gsc_query", "Search console query"),
                            ("imported", "Imported"),
                            ("manual", "Manual"),
                        ],
                        help_text="Where this prompt came from — the seeded-vs-manual comparison is the POC's main experiment.",
                        max_length=32,
                    ),
                ),
                (
                    "evidence",
                    models.JSONField(
                        blank=True,
                        default=dict,
                        help_text="Why this prompt made the set (signup counts, entry paths, crawl counts, query clicks).",
                    ),
                ),
                (
                    "rank",
                    models.FloatField(
                        default=0, help_text="Seeding score; higher runs first when the set is truncated."
                    ),
                ),
                (
                    "active",
                    models.BooleanField(default=True, help_text="Only active prompts are executed by the runner."),
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
                "db_table": "posthog_aeo_prompt",
            },
        ),
        migrations.AddConstraint(
            model_name="aeoprompt",
            constraint=models.UniqueConstraint(fields=("team", "prompt_hash"), name="aeo_prompt_unique_team_hash"),
        ),
        migrations.AddIndex(
            model_name="aeoprompt",
            index=models.Index(fields=["team_id", "active"], name="aeo_prompt_team_active_idx"),
        ),
    ]
