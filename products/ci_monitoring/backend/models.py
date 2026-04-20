"""Django models for ci_monitoring."""

from __future__ import annotations

import uuid

from django.db import models

from .facade.enums import CIRunConclusion, QuarantineState, TestExecutionStatus, TestSuite


class Repo(models.Model):
    """
    A monitored repository tied to a GitHub repository.

    Identity is the GitHub numeric repo ID (survives renames and org transfers).
    repo_full_name is kept for API calls and display.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # References posthog.Team in the main DB — plain integer for cross-DB isolation.
    team_id = models.BigIntegerField(db_index=True)

    repo_external_id = models.BigIntegerField()
    repo_full_name = models.CharField(max_length=255)
    default_branch = models.CharField(max_length=255, default="main")

    codeowners_cache = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["team_id", "repo_external_id"], name="ci_mon_unique_repo_per_team"),
        ]

    def __str__(self) -> str:
        return self.repo_full_name


class CIRun(models.Model):
    """A single CI workflow run with aggregated test results."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    team_id = models.BigIntegerField(db_index=True)
    repo = models.ForeignKey(Repo, on_delete=models.CASCADE, related_name="ci_runs")

    github_run_id = models.BigIntegerField()
    workflow_name = models.CharField(max_length=255)
    commit_sha = models.CharField(max_length=40)
    branch = models.CharField(max_length=255)
    pr_number = models.IntegerField(null=True, blank=True)

    conclusion = models.CharField(max_length=20, choices=[(s.value, s.value) for s in CIRunConclusion])

    started_at = models.DateTimeField()
    completed_at = models.DateTimeField()

    # Aggregated test counts (populated after artifact ingestion)
    total_tests = models.IntegerField(default=0)
    passed = models.IntegerField(default=0)
    failed = models.IntegerField(default=0)
    flaky = models.IntegerField(default=0)
    skipped = models.IntegerField(default=0)
    errored = models.IntegerField(default=0)

    artifacts_ingested = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["repo", "github_run_id"], name="ci_mon_unique_run_per_repo"),
        ]
        indexes = [
            models.Index(fields=["repo", "-completed_at"], name="ci_mon_run_repo_completed"),
            models.Index(fields=["branch", "-completed_at"], name="ci_mon_run_branch_completed"),
        ]

    def __str__(self) -> str:
        return f"{self.workflow_name} #{self.github_run_id}"


class TestCase(models.Model):
    """
    A unique test tracked across CI runs.

    The identifier is the fully qualified test name
    (e.g., "test_module.TestClass.test_method" for pytest,
    "spec > describe > it" for Playwright).
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    team_id = models.BigIntegerField(db_index=True)
    repo = models.ForeignKey(Repo, on_delete=models.CASCADE, related_name="test_cases")

    identifier = models.CharField(max_length=1024)
    suite = models.CharField(max_length=50, choices=[(s.value, s.value) for s in TestSuite], default=TestSuite.OTHER)
    file_path = models.CharField(max_length=1024, null=True, blank=True)
    line_number = models.IntegerField(null=True, blank=True)

    # From CODEOWNERS
    team_area = models.CharField(max_length=255, default="", blank=True)

    # Rolling 30-day flake score (0-100)
    flake_score = models.FloatField(default=0.0)
    total_runs = models.IntegerField(default=0)
    total_flakes = models.IntegerField(default=0)

    first_seen_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(auto_now=True)
    last_flaked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["repo", "identifier"], name="ci_mon_unique_test_per_repo"),
        ]
        indexes = [
            models.Index(fields=["repo", "-flake_score"], name="ci_mon_test_flake_score"),
            models.Index(fields=["suite", "-flake_score"], name="ci_mon_test_suite_flake"),
        ]

    def __str__(self) -> str:
        return self.identifier


class TestExecution(models.Model):
    """A single execution of a test case within a CI run."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    ci_run = models.ForeignKey(CIRun, on_delete=models.CASCADE, related_name="executions")
    test_case = models.ForeignKey(TestCase, on_delete=models.CASCADE, related_name="executions")

    status = models.CharField(max_length=20, choices=[(s.value, s.value) for s in TestExecutionStatus])
    duration_ms = models.IntegerField(null=True, blank=True)
    error_message = models.TextField(null=True, blank=True)
    retry_count = models.IntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["ci_run", "test_case"], name="ci_mon_unique_exec_per_run"),
        ]
        indexes = [
            models.Index(fields=["test_case", "-created_at"], name="ci_mon_exec_test_created"),
        ]


class Quarantine(models.Model):
    """
    A quarantine record for a flaky test.

    While active, the test still runs but failures don't block CI.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    team_id = models.BigIntegerField(db_index=True)
    test_case = models.ForeignKey(TestCase, on_delete=models.CASCADE, related_name="quarantines")

    reason = models.TextField()
    state = models.CharField(
        max_length=20, choices=[(s.value, s.value) for s in QuarantineState], default=QuarantineState.ACTIVE
    )

    github_issue_url = models.URLField(max_length=500, null=True, blank=True)
    github_pr_url = models.URLField(max_length=500, null=True, blank=True)

    # References posthog.User ids in the main DB — plain integer, null on user deletion handled in app code.
    created_by_id = models.BigIntegerField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by_id = models.BigIntegerField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["test_case", "state"], name="ci_mon_quarantine_test_state"),
        ]


class MainStreak(models.Model):
    """
    Tracks the "days since last broken main" streak per repo.

    current_streak_started_at is null when the default branch is currently broken.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    team_id = models.BigIntegerField(db_index=True)
    repo = models.OneToOneField(Repo, on_delete=models.CASCADE, related_name="main_streak")

    current_streak_started_at = models.DateTimeField(null=True, blank=True)
    record_streak_days = models.IntegerField(default=0)
    record_streak_start = models.DateTimeField(null=True, blank=True)
    record_streak_end = models.DateTimeField(null=True, blank=True)

    last_broken_at = models.DateTimeField(null=True, blank=True)
    last_incident_workflows = models.JSONField(default=list, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["team_id", "repo"], name="ci_mon_unique_main_streak_per_repo"),
        ]
