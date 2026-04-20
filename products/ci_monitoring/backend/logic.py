"""
Business logic for ci_monitoring.

Validation, calculations, business rules, ORM queries.
Called by facade/api.py.
"""

from __future__ import annotations

import uuid
import datetime

from django.db.models import QuerySet
from django.utils import timezone

import structlog

from .facade.enums import CIRunConclusion, QuarantineState, TestExecutionStatus
from .models import CIRun, MainStreak, Quarantine, Repo, TestCase, TestExecution

logger = structlog.get_logger(__name__)


class RepoNotFoundError(Exception):
    pass


# --- Repo ---


def create_repo(
    *,
    team_id: int,
    repo_external_id: int,
    repo_full_name: str,
    default_branch: str = "main",
) -> Repo:
    repo, _ = Repo.objects.update_or_create(
        team_id=team_id,
        repo_external_id=repo_external_id,
        defaults={
            "repo_full_name": repo_full_name,
            "default_branch": default_branch,
        },
    )
    return repo


def get_repo(*, repo_id: uuid.UUID, team_id: int) -> Repo:
    return Repo.objects.get(id=repo_id, team_id=team_id)


def list_repos(*, team_id: int) -> QuerySet[Repo]:
    return Repo.objects.filter(team_id=team_id).order_by("repo_full_name")


# --- Webhook Ingestion ---


def create_ci_run_from_webhook(
    *,
    repo_external_id: int,
    repo_full_name: str,
    github_run_id: int,
    workflow_name: str,
    commit_sha: str,
    branch: str,
    conclusion: CIRunConclusion,
    started_at: str | None,
    completed_at: str | None,
    pr_number: int | None,
) -> CIRun:
    """Create a CIRun from a GitHub workflow_run webhook payload."""
    from django.utils.dateparse import parse_datetime

    repo = Repo.objects.filter(repo_external_id=repo_external_id).first()
    if not repo:
        raise RepoNotFoundError(f"No repo with external_id={repo_external_id}")

    parsed_started = parse_datetime(started_at) if started_at else timezone.now()
    parsed_completed = parse_datetime(completed_at) if completed_at else timezone.now()

    ci_run, created = CIRun.objects.update_or_create(
        repo=repo,
        github_run_id=github_run_id,
        defaults={
            "team_id": repo.team_id,
            "workflow_name": workflow_name,
            "commit_sha": commit_sha,
            "branch": branch,
            "conclusion": conclusion,
            "started_at": parsed_started,
            "completed_at": parsed_completed,
            "pr_number": pr_number,
        },
    )

    return ci_run


def ingest_test_results(
    *,
    ci_run: CIRun,
    parsed_results: list,
) -> None:
    """Create TestCase and TestExecution records from parsed test results."""
    from .junit_parser import ParsedTestResult

    counts = {"total": 0, "passed": 0, "failed": 0, "flaky": 0, "skipped": 0, "error": 0}

    for result in parsed_results:
        result: ParsedTestResult
        test_case, _ = TestCase.objects.get_or_create(
            repo=ci_run.repo,
            identifier=result.identifier,
            defaults={
                "team_id": ci_run.team_id,
                "suite": _infer_suite(result),
                "file_path": result.file_path,
            },
        )

        if result.file_path and not test_case.file_path:
            test_case.file_path = result.file_path
            test_case.save(update_fields=["file_path"])

        TestExecution.objects.update_or_create(
            ci_run=ci_run,
            test_case=test_case,
            defaults={
                "status": result.status,
                "duration_ms": result.duration_ms,
                "error_message": result.error_message,
                "retry_count": result.retry_count,
            },
        )

        if result.status == TestExecutionStatus.FLAKY and (
            test_case.last_flaked_at is None or test_case.last_flaked_at < ci_run.completed_at
        ):
            test_case.last_flaked_at = ci_run.completed_at
            test_case.save(update_fields=["last_flaked_at"])

        counts["total"] += 1
        status_key = result.status.value
        if status_key in counts:
            counts[status_key] += 1

    ci_run.total_tests = counts["total"]
    ci_run.passed = counts["passed"]
    ci_run.failed = counts["failed"]
    ci_run.flaky = counts["flaky"]
    ci_run.skipped = counts["skipped"]
    ci_run.errored = counts["error"]
    ci_run.artifacts_ingested = True
    ci_run.save(
        update_fields=[
            "total_tests",
            "passed",
            "failed",
            "flaky",
            "skipped",
            "errored",
            "artifacts_ingested",
        ]
    )


def _infer_suite(result) -> str:
    """Infer the test suite from file path or classname."""
    from .facade.enums import TestSuite

    fp = result.file_path or result.classname or ""
    fp_lower = fp.lower()

    if "e2e" in fp_lower or "playwright" in fp_lower:
        return TestSuite.E2E
    if "storybook" in fp_lower:
        return TestSuite.STORYBOOK
    if fp_lower.endswith(".rs"):
        return TestSuite.RUST
    if "node" in fp_lower or fp_lower.endswith((".ts", ".js")):
        return TestSuite.NODEJS
    if fp_lower.endswith(".py") or "test_" in fp_lower:
        return TestSuite.BACKEND
    return TestSuite.OTHER


# --- GitHub API ---


# --- CI Runs ---


def list_ci_runs(
    *,
    team_id: int,
    repo_id: uuid.UUID | None = None,
    branch: str | None = None,
    workflow_name: str | None = None,
    limit: int = 50,
) -> QuerySet[CIRun]:
    qs = CIRun.objects.filter(team_id=team_id)
    if repo_id:
        qs = qs.filter(repo_id=repo_id)
    if branch:
        qs = qs.filter(branch=branch)
    if workflow_name:
        qs = qs.filter(workflow_name=workflow_name)
    return qs.order_by("-completed_at")[:limit]


def get_ci_run(*, run_id: uuid.UUID, team_id: int) -> CIRun:
    return CIRun.objects.get(id=run_id, team_id=team_id)


# --- Test Cases ---


def list_tests_needing_attention(
    *,
    team_id: int,
    repo_id: uuid.UUID | None = None,
    suite: str | None = None,
    min_flake_score: float = 0.0,
    limit: int = 50,
) -> list[tuple[TestCase, Quarantine | None]]:
    """Return flaky test cases paired with their active quarantine (if any)."""
    qs = TestCase.objects.filter(team_id=team_id, flake_score__gt=min_flake_score)
    if repo_id:
        qs = qs.filter(repo_id=repo_id)
    if suite:
        qs = qs.filter(suite=suite)
    tests = list(qs.order_by("-flake_score")[:limit])
    active = {
        q.test_case_id: q
        for q in Quarantine.objects.filter(
            test_case_id__in=[t.id for t in tests],
            state=QuarantineState.ACTIVE,
        )
    }
    return [(t, active.get(t.id)) for t in tests]


def get_test_case_with_quarantine(*, test_case_id: uuid.UUID, team_id: int) -> tuple[TestCase, Quarantine | None]:
    tc = TestCase.objects.get(id=test_case_id, team_id=team_id)
    q = Quarantine.objects.filter(test_case=tc, state=QuarantineState.ACTIVE).first()
    return tc, q


def get_test_case(*, test_case_id: uuid.UUID, team_id: int) -> TestCase:
    return TestCase.objects.get(id=test_case_id, team_id=team_id)


def get_test_executions(*, test_case_id: uuid.UUID, team_id: int, limit: int = 100) -> QuerySet[TestExecution]:
    return (
        TestExecution.objects.filter(test_case_id=test_case_id, ci_run__team_id=team_id)
        .select_related("ci_run")
        .order_by("-created_at")[:limit]
    )


# --- Flake Score ---


def update_flake_scores(*, repo_id: uuid.UUID, team_id: int) -> None:
    """Recompute rolling 30-day flake scores for all tests in a repo."""
    from django.db.models import Count, Q

    cutoff = timezone.now() - datetime.timedelta(days=30)

    annotated = (
        TestCase.objects.filter(repo_id=repo_id, team_id=team_id)
        .annotate(
            recent_total=Count("executions", filter=Q(executions__created_at__gte=cutoff)),
            recent_flaky=Count(
                "executions",
                filter=Q(executions__created_at__gte=cutoff, executions__status=TestExecutionStatus.FLAKY),
            ),
        )
        .filter(recent_total__gt=0)
    )

    to_update = []
    for tc in annotated:
        tc.flake_score = round((tc.recent_flaky / tc.recent_total) * 100, 2)
        tc.total_runs = tc.recent_total
        tc.total_flakes = tc.recent_flaky
        to_update.append(tc)

    if to_update:
        TestCase.objects.bulk_update(to_update, ["flake_score", "total_runs", "total_flakes"])


# --- Master Streak ---


def get_or_create_main_streak(*, repo_id: uuid.UUID, team_id: int) -> MainStreak:
    streak, _ = MainStreak.objects.get_or_create(
        repo_id=repo_id,
        team_id=team_id,
    )
    return streak


def record_main_branch_run(*, repo_id: uuid.UUID, team_id: int, conclusion: str, workflow_name: str) -> MainStreak:
    """Update the master streak based on a completed run on the default branch."""
    streak = get_or_create_main_streak(repo_id=repo_id, team_id=team_id)
    now = timezone.now()

    if conclusion in ("failure", "timed_out"):
        # Master is broken
        if streak.current_streak_started_at is not None:
            # Was healthy — record the ending streak
            streak_days = (now - streak.current_streak_started_at).days
            if streak_days > streak.record_streak_days:
                streak.record_streak_days = streak_days
                streak.record_streak_start = streak.current_streak_started_at
                streak.record_streak_end = now

        streak.current_streak_started_at = None
        streak.last_broken_at = now
        workflows = streak.last_incident_workflows or []
        if workflow_name not in workflows:
            workflows.append(workflow_name)
        streak.last_incident_workflows = workflows

    elif conclusion == "success":
        if streak.current_streak_started_at is None:
            # Was broken — now recovered
            streak.current_streak_started_at = now
            streak.last_incident_workflows = []

    streak.save()
    return streak


# --- Health Stats ---


def get_health_stats(*, repo_id: uuid.UUID, team_id: int) -> dict:
    cutoff = timezone.now() - datetime.timedelta(days=7)

    runs_7d = CIRun.objects.filter(repo_id=repo_id, team_id=team_id, completed_at__gte=cutoff)
    total_runs = runs_7d.count()

    flaky_executions_7d = TestExecution.objects.filter(
        ci_run__repo_id=repo_id,
        ci_run__team_id=team_id,
        created_at__gte=cutoff,
        status=TestExecutionStatus.FLAKY,
    )
    total_flaky = flaky_executions_7d.values("test_case_id").distinct().count()

    total_executions_7d = TestExecution.objects.filter(
        ci_run__repo_id=repo_id,
        ci_run__team_id=team_id,
        created_at__gte=cutoff,
    ).count()

    flake_rate = flaky_executions_7d.count() / total_executions_7d if total_executions_7d > 0 else 0.0

    tests_needing_attention = TestCase.objects.filter(repo_id=repo_id, team_id=team_id, flake_score__gt=0).count()

    active_quarantines = Quarantine.objects.filter(
        team_id=team_id, test_case__repo_id=repo_id, state=QuarantineState.ACTIVE
    ).count()

    return {
        "flake_rate_7d": round(flake_rate, 4),
        "total_runs_7d": total_runs,
        "total_flaky_tests_7d": total_flaky,
        "tests_needing_attention": tests_needing_attention,
        "active_quarantines": active_quarantines,
    }


# --- Quarantine ---


def create_quarantine(
    *,
    team_id: int,
    test_case_id: uuid.UUID,
    reason: str,
    created_by_id: int,
    create_github_issue: bool = True,
) -> Quarantine:
    test_case = TestCase.objects.get(id=test_case_id, team_id=team_id)

    q = Quarantine.objects.create(
        team_id=team_id,
        test_case=test_case,
        reason=reason,
        created_by_id=created_by_id,
        state=QuarantineState.ACTIVE,
    )

    # GitHub issue creation is handled asynchronously via Celery task
    if create_github_issue:
        from .tasks.tasks import create_quarantine_github_issue

        create_quarantine_github_issue.delay(quarantine_id=str(q.id))

    return q


def resolve_quarantine(*, quarantine_id: uuid.UUID, team_id: int, resolved_by_id: int) -> Quarantine:
    q = Quarantine.objects.get(id=quarantine_id, team_id=team_id)
    q.state = QuarantineState.RESOLVED
    q.resolved_at = timezone.now()
    q.resolved_by_id = resolved_by_id
    q.save(update_fields=["state", "resolved_at", "resolved_by_id"])
    return q
