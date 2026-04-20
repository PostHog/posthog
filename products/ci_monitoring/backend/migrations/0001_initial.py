import uuid

import django.db.models.deletion
from django.db import migrations, models

import products.ci_monitoring.backend.facade.enums


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="Repo",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("team_id", models.BigIntegerField(db_index=True)),
                ("repo_external_id", models.BigIntegerField()),
                ("repo_full_name", models.CharField(max_length=255)),
                ("default_branch", models.CharField(default="main", max_length=255)),
                ("codeowners_cache", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
        ),
        migrations.CreateModel(
            name="TestCase",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("team_id", models.BigIntegerField(db_index=True)),
                ("identifier", models.CharField(max_length=1024)),
                (
                    "suite",
                    models.CharField(
                        choices=[
                            ("backend", "backend"),
                            ("e2e", "e2e"),
                            ("storybook", "storybook"),
                            ("nodejs", "nodejs"),
                            ("rust", "rust"),
                            ("other", "other"),
                        ],
                        default=products.ci_monitoring.backend.facade.enums.TestSuite["OTHER"],
                        max_length=50,
                    ),
                ),
                ("file_path", models.CharField(blank=True, max_length=1024, null=True)),
                ("line_number", models.IntegerField(blank=True, null=True)),
                ("team_area", models.CharField(blank=True, default="", max_length=255)),
                ("flake_score", models.FloatField(default=0.0)),
                ("total_runs", models.IntegerField(default=0)),
                ("total_flakes", models.IntegerField(default=0)),
                ("first_seen_at", models.DateTimeField(auto_now_add=True)),
                ("last_seen_at", models.DateTimeField(auto_now=True)),
                ("last_flaked_at", models.DateTimeField(blank=True, null=True)),
                (
                    "repo",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="test_cases",
                        to="ci_monitoring.repo",
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="Quarantine",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("team_id", models.BigIntegerField(db_index=True)),
                ("reason", models.TextField()),
                (
                    "state",
                    models.CharField(
                        choices=[("active", "active"), ("resolved", "resolved")],
                        default=products.ci_monitoring.backend.facade.enums.QuarantineState["ACTIVE"],
                        max_length=20,
                    ),
                ),
                (
                    "github_issue_url",
                    models.URLField(blank=True, max_length=500, null=True),
                ),
                (
                    "github_pr_url",
                    models.URLField(blank=True, max_length=500, null=True),
                ),
                ("created_by_id", models.BigIntegerField(null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("resolved_at", models.DateTimeField(blank=True, null=True)),
                ("resolved_by_id", models.BigIntegerField(blank=True, null=True)),
                (
                    "test_case",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="quarantines",
                        to="ci_monitoring.testcase",
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="MainStreak",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("team_id", models.BigIntegerField(db_index=True)),
                (
                    "current_streak_started_at",
                    models.DateTimeField(blank=True, null=True),
                ),
                ("record_streak_days", models.IntegerField(default=0)),
                ("record_streak_start", models.DateTimeField(blank=True, null=True)),
                ("record_streak_end", models.DateTimeField(blank=True, null=True)),
                ("last_broken_at", models.DateTimeField(blank=True, null=True)),
                ("last_incident_workflows", models.JSONField(blank=True, default=list)),
                (
                    "repo",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="main_streak",
                        to="ci_monitoring.repo",
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="CIRun",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("team_id", models.BigIntegerField(db_index=True)),
                ("github_run_id", models.BigIntegerField()),
                ("workflow_name", models.CharField(max_length=255)),
                ("commit_sha", models.CharField(max_length=40)),
                ("branch", models.CharField(max_length=255)),
                ("pr_number", models.IntegerField(blank=True, null=True)),
                (
                    "conclusion",
                    models.CharField(
                        choices=[
                            ("success", "success"),
                            ("failure", "failure"),
                            ("cancelled", "cancelled"),
                            ("timed_out", "timed_out"),
                        ],
                        max_length=20,
                    ),
                ),
                ("started_at", models.DateTimeField()),
                ("completed_at", models.DateTimeField()),
                ("total_tests", models.IntegerField(default=0)),
                ("passed", models.IntegerField(default=0)),
                ("failed", models.IntegerField(default=0)),
                ("flaky", models.IntegerField(default=0)),
                ("skipped", models.IntegerField(default=0)),
                ("errored", models.IntegerField(default=0)),
                ("artifacts_ingested", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "repo",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="ci_runs",
                        to="ci_monitoring.repo",
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="TestExecution",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("passed", "passed"),
                            ("failed", "failed"),
                            ("flaky", "flaky"),
                            ("skipped", "skipped"),
                            ("error", "error"),
                        ],
                        max_length=20,
                    ),
                ),
                ("duration_ms", models.IntegerField(blank=True, null=True)),
                ("error_message", models.TextField(blank=True, null=True)),
                ("retry_count", models.IntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "ci_run",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="executions",
                        to="ci_monitoring.cirun",
                    ),
                ),
                (
                    "test_case",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="executions",
                        to="ci_monitoring.testcase",
                    ),
                ),
            ],
            options={
                "indexes": [
                    models.Index(
                        fields=["test_case", "-created_at"],
                        name="ci_mon_exec_test_created",
                    )
                ],
            },
        ),
        migrations.AddConstraint(
            model_name="testexecution",
            constraint=models.UniqueConstraint(fields=("ci_run", "test_case"), name="ci_mon_unique_exec_per_run"),
        ),
        migrations.AddIndex(
            model_name="testcase",
            index=models.Index(fields=["repo", "-flake_score"], name="ci_mon_test_flake_score"),
        ),
        migrations.AddIndex(
            model_name="testcase",
            index=models.Index(fields=["suite", "-flake_score"], name="ci_mon_test_suite_flake"),
        ),
        migrations.AddConstraint(
            model_name="testcase",
            constraint=models.UniqueConstraint(fields=("repo", "identifier"), name="ci_mon_unique_test_per_repo"),
        ),
        migrations.AddConstraint(
            model_name="repo",
            constraint=models.UniqueConstraint(
                fields=("team_id", "repo_external_id"), name="ci_mon_unique_repo_per_team"
            ),
        ),
        migrations.AddIndex(
            model_name="quarantine",
            index=models.Index(fields=["test_case", "state"], name="ci_mon_quarantine_test_state"),
        ),
        migrations.AddConstraint(
            model_name="mainstreak",
            constraint=models.UniqueConstraint(fields=("team_id", "repo"), name="ci_mon_unique_main_streak_per_repo"),
        ),
        migrations.AddIndex(
            model_name="cirun",
            index=models.Index(fields=["repo", "-completed_at"], name="ci_mon_run_repo_completed"),
        ),
        migrations.AddIndex(
            model_name="cirun",
            index=models.Index(fields=["branch", "-completed_at"], name="ci_mon_run_branch_completed"),
        ),
        migrations.AddConstraint(
            model_name="cirun",
            constraint=models.UniqueConstraint(fields=("repo", "github_run_id"), name="ci_mon_unique_run_per_repo"),
        ),
    ]
