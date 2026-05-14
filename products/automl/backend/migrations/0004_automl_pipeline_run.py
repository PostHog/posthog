# Hand-written migration mirroring the shape Django would generate from
# `products.automl.backend.models.AutoMLPipelineRun`. Verify by running
# `python manage.py makemigrations automl --check --dry-run` once a healthy
# env is at hand; if Django suggests anything beyond auto-generated index
# names, surface those tweaks here.

import django.db.models.manager
import django.db.models.deletion
from django.db import migrations, models

import posthog.models.utils


class Migration(migrations.Migration):
    dependencies = [
        ("automl", "0003_automl_model_version"),
    ]

    operations = [
        migrations.CreateModel(
            name="AutoMLPipelineRun",
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
                    "run_kind",
                    models.CharField(
                        choices=[
                            ("bootstrap", "bootstrap"),
                            ("retrain", "retrain"),
                            ("inference", "inference"),
                        ],
                        help_text="Which workflow drove this run: bootstrap / retrain / inference.",
                        max_length=16,
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("running", "running"),
                            ("succeeded", "succeeded"),
                            ("failed", "failed"),
                            ("aborted", "aborted"),
                        ],
                        default="running",
                        help_text="Lifecycle: running / succeeded / failed / aborted.",
                        max_length=16,
                    ),
                ),
                (
                    "task_slug",
                    models.CharField(
                        help_text=(
                            "The ``--task`` name passed to the automl-cli; default is "
                            "``slugify(pipeline.name)``. Persisted so the workspace path is "
                            "reconstructable without parsing it back out of the brief."
                        ),
                        max_length=128,
                    ),
                ),
                (
                    "task_workspace_root",
                    models.TextField(
                        blank=True,
                        default="",
                        help_text=(
                            "The ``s3://automl/tasks/<task_slug>/`` prefix the CLI wrote to. "
                            "Workspace shape documented in ``automl-cli/CLAUDE.md``."
                        ),
                    ),
                ),
                (
                    "cli_run_id",
                    models.CharField(
                        blank=True,
                        default="",
                        help_text=(
                            "The CLI's ``runs/<run_id>/`` UTC timestamp, e.g. ``20260514T130000Z``. "
                            "Empty when the run failed before training started."
                        ),
                        max_length=32,
                    ),
                ),
                (
                    "agent_session_id",
                    models.CharField(
                        blank=True,
                        default="",
                        help_text=(
                            "Sandbox session id from the orchestrating Task; lets us replay the agent transcript."
                        ),
                        max_length=128,
                    ),
                ),
                (
                    "task_id",
                    models.UUIDField(
                        blank=True,
                        help_text="Back-reference to the ``tasks.Task`` row that drove this run.",
                        null=True,
                    ),
                ),
                (
                    "parent_run_id",
                    models.UUIDField(
                        blank=True,
                        help_text=(
                            "Predecessor run when this is a retraining iteration. Drives the "
                            "iteration chain for the retraining skill. Null for the first run "
                            "in a chain (bootstrap, the first retrain) and for inference runs."
                        ),
                        null=True,
                    ),
                ),
                (
                    "started_at",
                    models.DateTimeField(
                        auto_now_add=True,
                        help_text="When the run was opened (row created).",
                    ),
                ),
                (
                    "completed_at",
                    models.DateTimeField(
                        blank=True,
                        help_text="When the run reached a terminal state. Null while running.",
                        null=True,
                    ),
                ),
                (
                    "outcome_report",
                    models.TextField(
                        blank=True,
                        default="",
                        help_text=(
                            "Structured markdown report the agent writes at the end of the run. "
                            "Surfaced on the pipeline detail page; empty until the agent finishes."
                        ),
                    ),
                ),
                (
                    "eda_result",
                    models.JSONField(
                        blank=True,
                        default=dict,
                        help_text=(
                            "Output of ``automl-record-eda-result``: class balance, top-signal "
                            "features, dropped features, leakage warnings, full ``eda_uri``. "
                            "Empty until the agent runs EDA."
                        ),
                    ),
                ),
                (
                    "training_result",
                    models.JSONField(
                        blank=True,
                        default=dict,
                        help_text=(
                            "Compact summary of the ``automl-record-training-result`` call: "
                            "metrics, leaderboard top-5, gate verdict. Mirrors fields on the "
                            "full ``AutoMLModelVersion`` record but stays denormalized here so "
                            "the run-history view doesn't need to join."
                        ),
                    ),
                ),
                (
                    "failure_reason",
                    models.CharField(
                        blank=True,
                        default="",
                        help_text=(
                            "Compact tag (snapshot_fetch_failed / population_too_small / "
                            "training_crash / mcp_unavailable / task_create_failed / ...) when "
                            "``status`` is failed or aborted. Empty otherwise."
                        ),
                        max_length=128,
                    ),
                ),
                (
                    "created_model_version_id",
                    models.UUIDField(
                        blank=True,
                        help_text=(
                            "The ``AutoMLModelVersion`` this run produced, if any. Null for "
                            "runs that bailed before training landed a model. Plain UUID — "
                            "the relationship is one-shot and a FK would over-couple this "
                            "row to the model-version table's lifecycle."
                        ),
                        null=True,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "pipeline",
                    models.ForeignKey(
                        help_text="The pipeline this run belongs to.",
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
                        fields=["team_id", "pipeline", "-started_at"],
                        name="automl_auto_team_id_ac0ecd_idx",
                    ),
                    models.Index(
                        fields=["team_id", "status"],
                        name="automl_auto_team_id_deca45_idx",
                    ),
                ],
            },
            managers=[
                ("all_teams", django.db.models.manager.Manager()),
            ],
        ),
    ]
