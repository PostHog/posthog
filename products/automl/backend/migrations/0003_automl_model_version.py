# Hand-written migration (env's makemigrations was broken at authoring time).
# Mirrors the shape Django would have generated from
# `products.automl.backend.models.AutoMLModelVersion` — verify with
# `python manage.py makemigrations automl --check --dry-run` once env is healthy.

import django.db.models.manager
import django.db.models.deletion
from django.db import migrations, models

import posthog.models.utils


class Migration(migrations.Migration):
    dependencies = [
        ("automl", "0002_automlpipeline_runtime"),
    ]

    operations = [
        migrations.AlterField(
            model_name="automlpipeline",
            name="runtime",
            field=models.JSONField(
                blank=True,
                default=dict,
                help_text=(
                    "System-managed runtime state. Holds pointers like the bootstrap task id, "
                    "the bootstrap error message, and the last inference timestamp. Model "
                    "version pointers (champion / challenger) live on `AutoMLModelVersion.role` "
                    "instead. Distinct from user-configured `config` so we never overwrite "
                    "user intent with system state."
                ),
            ),
        ),
        migrations.CreateModel(
            name="AutoMLModelVersion",
            fields=[
                ("team_id", models.BigIntegerField(db_index=True)),
                (
                    "id",
                    models.UUIDField(
                        default=posthog.models.utils.uuid7,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    "role",
                    models.CharField(
                        choices=[
                            ("champion", "champion"),
                            ("challenger", "challenger"),
                            ("archived", "archived"),
                        ],
                        default="challenger",
                        help_text=(
                            "Lifecycle role: champion (serves traffic), challenger (head-to-head, "
                            "event-only), archived (audit-only). At most one champion and one "
                            "challenger per pipeline."
                        ),
                        max_length=16,
                    ),
                ),
                (
                    "metrics",
                    models.JSONField(
                        blank=True,
                        default=dict,
                        help_text="Scalar metrics dict, e.g. {'roc_auc': 0.85, 'log_loss': 0.42}.",
                    ),
                ),
                (
                    "leaderboard",
                    models.JSONField(
                        blank=True,
                        default=list,
                        help_text="AutoGluon leaderboard records (top-N models). One JSON object per model.",
                    ),
                ),
                (
                    "training_params",
                    models.JSONField(
                        blank=True,
                        default=dict,
                        help_text=(
                            "Training hyper-parameters (seed, presets, time_limit_s, val_fraction, test_fraction, ...)."
                        ),
                    ),
                ),
                (
                    "tracking_metadata",
                    models.JSONField(
                        blank=True,
                        default=dict,
                        help_text=(
                            "Flex hatch for external experiment-tracker linkage (mlflow_run_id, "
                            "wandb_run_id, etc.). Empty today; written if/when a tracking server "
                            "lands. Schemaless on purpose so we can add trackers without migration."
                        ),
                    ),
                ),
                (
                    "eval_metric",
                    models.CharField(
                        blank=True,
                        default="",
                        help_text="AutoGluon eval metric name, e.g. 'roc_auc', 'rmse'.",
                        max_length=64,
                    ),
                ),
                (
                    "problem_type",
                    models.CharField(
                        blank=True,
                        default="",
                        help_text="AutoGluon problem type: 'binary', 'multiclass', 'regression', etc.",
                        max_length=32,
                    ),
                ),
                (
                    "artifact_uri",
                    models.TextField(
                        blank=True,
                        default="",
                        help_text=(
                            "URI of the serialized model artifact. Empty when the producer has no "
                            "durable storage (e.g. sandbox runs before S3 wiring lands). Schemes vary "
                            "by producer (file://, s3://, ...) — load-side decides how to resolve."
                        ),
                    ),
                ),
                (
                    "features_hash",
                    models.CharField(
                        blank=True,
                        default="",
                        help_text="Hash of the training feature set. Matches `$features_hash` on emitted predictions.",
                        max_length=64,
                    ),
                ),
                (
                    "rows_train",
                    models.IntegerField(
                        blank=True,
                        help_text="Rows in the training split (provenance).",
                        null=True,
                    ),
                ),
                (
                    "rows_val",
                    models.IntegerField(
                        blank=True,
                        help_text="Rows in the validation split (provenance).",
                        null=True,
                    ),
                ),
                (
                    "rows_test",
                    models.IntegerField(
                        blank=True,
                        help_text="Rows in the held-out test split (provenance).",
                        null=True,
                    ),
                ),
                (
                    "training_task_id",
                    models.UUIDField(
                        blank=True,
                        help_text=(
                            "Back-reference to the ``tasks.Task`` row that produced this version. "
                            "Plain UUID instead of FK — keeps us free to move products to separate "
                            "databases later (per products/architecture.md)."
                        ),
                        null=True,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "pipeline",
                    models.ForeignKey(
                        help_text="The pipeline this model version belongs to.",
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="+",
                        to="automl.automlpipeline",
                    ),
                ),
            ],
            options={
                "abstract": False,
                "default_manager_name": "all_teams",
                "indexes": [
                    models.Index(
                        fields=["team_id", "pipeline", "-created_at"],
                        name="automl_auto_team_id_fd9fae_idx",
                    ),
                ],
                "constraints": [
                    models.UniqueConstraint(
                        condition=models.Q(("role__in", ["champion", "challenger"])),
                        fields=("pipeline", "role"),
                        name="automl_one_active_role_per_pipeline",
                    ),
                ],
            },
            managers=[
                ("all_teams", django.db.models.manager.Manager()),
            ],
        ),
    ]
