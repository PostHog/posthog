import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

import posthog.models.utils
from posthog.migration_helpers import AddForeignKeyNotValid


class Migration(migrations.Migration):
    dependencies = [
        ("customer_analytics", "0017_announcement_validate_fks"),
        ("posthog", "1238_ducklakebackfill_earliest_event_date"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="CustomPropertySyncRun",
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
                ("schema_id", models.UUIDField(blank=True, null=True)),
                ("job_id", models.CharField(blank=True, max_length=400, null=True)),
                (
                    "trigger",
                    models.CharField(
                        choices=[("scheduled", "scheduled"), ("manual", "manual"), ("backfill", "backfill")],
                        max_length=20,
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[("running", "running"), ("completed", "completed"), ("failed", "failed")],
                        default="running",
                        max_length=20,
                    ),
                ),
                ("started_at", models.DateTimeField(blank=True, null=True)),
                ("finished_at", models.DateTimeField(blank=True, null=True)),
                ("rows_read", models.PositiveIntegerField(default=0)),
                ("changed", models.PositiveIntegerField(default=0)),
                ("existing", models.PositiveIntegerField(default=0)),
                ("produced", models.PositiveIntegerField(default=0)),
                ("skipped_missing_person", models.PositiveIntegerField(default=0)),
                ("error", models.TextField(blank=True, null=True)),
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
                    "source",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="sync_runs",
                        to="customer_analytics.custompropertysource",
                    ),
                ),
                (
                    "team",
                    models.ForeignKey(
                        db_constraint=False,
                        on_delete=django.db.models.deletion.CASCADE,
                        to="posthog.team",
                    ),
                ),
            ],
            options={
                "indexes": [
                    models.Index(
                        fields=["team", "source", "-created_at"],
                        name="cpsr_team_source_created_idx",
                    )
                ],
            },
        ),
        AddForeignKeyNotValid(
            model_name="custompropertysyncrun",
            name="custompropertysyncrun_team_id_fk",
            column="team_id",
            to_table="posthog_team",
            to_column="id",
        ),
        AddForeignKeyNotValid(
            model_name="custompropertysyncrun",
            name="custompropertysyncrun_created_by_id_fk",
            column="created_by_id",
            to_table="posthog_user",
            to_column="id",
        ),
    ]
