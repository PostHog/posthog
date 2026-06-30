import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

import posthog.models.utils


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1244_team_event_retention_months"),
    ]

    operations = [
        migrations.CreateModel(
            name="DuckgresSinkSchemaState",
            fields=[
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True, null=True)),
                (
                    "id",
                    models.UUIDField(
                        default=posthog.models.utils.uuid7, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("schema_id", models.UUIDField(unique=True)),
                (
                    "state",
                    models.CharField(
                        choices=[
                            ("pending_backfill", "Pending backfill"),
                            ("backfilling", "Backfilling"),
                            ("primed", "Primed"),
                            ("needs_resync", "Needs resync"),
                        ],
                        default="pending_backfill",
                        max_length=32,
                    ),
                ),
                ("snapshot_version", models.BigIntegerField(blank=True, null=True)),
                ("plan_cutoff", models.DateTimeField(blank=True, null=True)),
                ("backfill_run_uuid", models.CharField(blank=True, max_length=200, null=True)),
                ("chunk_count", models.IntegerField(blank=True, null=True)),
                ("chunks_applied", models.IntegerField(default=0)),
                ("last_error", models.TextField(blank=True, null=True)),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        db_constraint=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "team",
                    models.ForeignKey(
                        db_constraint=False,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="duckgres_sink_schema_states",
                        to="posthog.team",
                    ),
                ),
            ],
            options={
                "verbose_name": "Duckgres sink schema state",
                "verbose_name_plural": "Duckgres sink schema states",
                "db_table": "posthog_duckgressinkschemastate",
            },
        ),
        migrations.AddIndex(
            model_name="duckgressinkschemastate",
            index=models.Index(fields=["team", "state"], name="duckgres_sink_team_state_idx"),
        ),
    ]
