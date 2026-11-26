import django.db.models.deletion
from django.db import migrations, models

import posthog.uuidt


class Migration(migrations.Migration):
    dependencies = [
        ("aeo", "0022_team_config"),
        ("posthog", "1453_disable_activitylog_detail_gin_fastupdate"),
    ]

    operations = [
        migrations.AddField(
            model_name="aeokeyword",
            name="history_matched_at",
            field=models.DateTimeField(
                blank=True,
                help_text="When the keyword's rows in `posthog_aeo_check_keyword` were written for every check recorded before it. Null until then.",
                null=True,
            ),
        ),
        migrations.CreateModel(
            name="AEOCheckKeyword",
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
                (
                    "created_at",
                    models.DateTimeField(
                        help_text="When the check ran. Copied from the check, so a window read needs no join."
                    ),
                ),
                (
                    "in_prompt",
                    models.BooleanField(help_text="The prompt contains the keyword, case ignored."),
                ),
                (
                    "in_searches",
                    models.BooleanField(help_text="One of the engine's searches contains the keyword, case ignored."),
                ),
                (
                    "uses",
                    models.PositiveIntegerField(
                        help_text="How many times the answer text contains the keyword, case ignored, counted without overlaps."
                    ),
                ),
                (
                    "citation_check",
                    models.ForeignKey(
                        db_index=False,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="+",
                        to="aeo.aeocitationcheck",
                    ),
                ),
                (
                    "keyword",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="+",
                        to="aeo.aeokeyword",
                    ),
                ),
                (
                    "team",
                    models.ForeignKey(
                        db_constraint=False,
                        db_index=False,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="+",
                        to="posthog.team",
                    ),
                ),
            ],
            options={
                "db_table": "posthog_aeo_check_keyword",
                "indexes": [
                    models.Index(
                        fields=["team_id", "created_at"],
                        include=(
                            "citation_check_id",
                            "keyword_id",
                            "in_prompt",
                            "in_searches",
                            "uses",
                        ),
                        name="aeo_check_keyword_window_idx",
                    )
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("citation_check", "keyword"),
                        name="aeo_check_keyword_unique_keyword",
                    )
                ],
            },
        ),
    ]
