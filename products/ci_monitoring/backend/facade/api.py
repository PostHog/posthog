"""
Facade for ci_monitoring.

This is the ONLY module other products are allowed to import.

Responsibilities:
- Accept frozen dataclasses as input parameters
- Call business logic (logic.py)
- Convert Django models to frozen dataclasses before returning
- Remain thin and stable

Do NOT:
- Implement business logic here (use logic.py)
- Import DRF, serializers, or HTTP concerns
- Return ORM instances or QuerySets
"""

from __future__ import annotations

import uuid

from django.utils import timezone

from .. import logic
from . import contracts

# --- Converters (model -> frozen dataclass) ---


def _to_repo(repo) -> contracts.Repo:
    return contracts.Repo(
        id=repo.id,
        team_id=repo.team_id,
        repo_external_id=repo.repo_external_id,
        repo_full_name=repo.repo_full_name,
        default_branch=repo.default_branch,
        created_at=repo.created_at,
    )


def _to_ci_run(run) -> contracts.CIRun:
    return contracts.CIRun(
        id=run.id,
        team_id=run.team_id,
        repo_id=run.repo_id,
        github_run_id=run.github_run_id,
        workflow_name=run.workflow_name,
        commit_sha=run.commit_sha,
        branch=run.branch,
        pr_number=run.pr_number,
        conclusion=run.conclusion,
        started_at=run.started_at,
        completed_at=run.completed_at,
        total_tests=run.total_tests,
        passed=run.passed,
        failed=run.failed,
        flaky=run.flaky,
        skipped=run.skipped,
        errored=run.errored,
        artifacts_ingested=run.artifacts_ingested,
        created_at=run.created_at,
    )


def _to_quarantine(q) -> contracts.Quarantine:
    return contracts.Quarantine(
        id=q.id,
        test_case_id=q.test_case_id,
        team_id=q.team_id,
        reason=q.reason,
        state=q.state,
        github_issue_url=q.github_issue_url,
        github_pr_url=q.github_pr_url,
        created_by_id=q.created_by_id,
        created_at=q.created_at,
        resolved_at=q.resolved_at,
        resolved_by_id=q.resolved_by_id,
    )


def _to_test_case(tc, *, quarantine=None) -> contracts.TestCase:
    return contracts.TestCase(
        id=tc.id,
        team_id=tc.team_id,
        repo_id=tc.repo_id,
        identifier=tc.identifier,
        suite=tc.suite,
        file_path=tc.file_path,
        team_area=tc.team_area,
        flake_score=tc.flake_score,
        total_runs=tc.total_runs,
        total_flakes=tc.total_flakes,
        first_seen_at=tc.first_seen_at,
        last_seen_at=tc.last_seen_at,
        last_flaked_at=tc.last_flaked_at,
        quarantine=quarantine,
    )


def _to_test_execution(ex) -> contracts.TestExecution:
    return contracts.TestExecution(
        id=ex.id,
        ci_run_id=ex.ci_run_id,
        test_case_id=ex.test_case_id,
        status=ex.status,
        duration_ms=ex.duration_ms,
        error_message=ex.error_message,
        retry_count=ex.retry_count,
        created_at=ex.created_at,
    )


def _to_main_streak(streak) -> contracts.MainStreak:
    now = timezone.now()
    is_broken = streak.current_streak_started_at is None
    current_days = 0 if is_broken else (now - streak.current_streak_started_at).days

    return contracts.MainStreak(
        repo_id=streak.repo_id,
        current_streak_days=current_days,
        current_streak_started_at=streak.current_streak_started_at,
        record_streak_days=streak.record_streak_days,
        record_streak_start=streak.record_streak_start,
        record_streak_end=streak.record_streak_end,
        last_broken_at=streak.last_broken_at,
        last_incident_workflows=streak.last_incident_workflows or [],
        is_broken_now=is_broken,
    )


# --- Public API ---


def create_repo(input: contracts.CreateRepoInput) -> contracts.Repo:
    repo = logic.create_repo(
        team_id=input.team_id,
        repo_external_id=input.repo_external_id,
        repo_full_name=input.repo_full_name,
        default_branch=input.default_branch,
    )
    return _to_repo(repo)


def get_repo(repo_id: uuid.UUID, team_id: int) -> contracts.Repo:
    repo = logic.get_repo(repo_id=repo_id, team_id=team_id)
    return _to_repo(repo)


def list_repos(team_id: int) -> list[contracts.Repo]:
    repos = logic.list_repos(team_id=team_id)
    return [_to_repo(r) for r in repos]


def list_ci_runs(
    team_id: int,
    repo_id: uuid.UUID | None = None,
    branch: str | None = None,
    workflow_name: str | None = None,
    limit: int = 50,
) -> list[contracts.CIRun]:
    runs = logic.list_ci_runs(
        team_id=team_id,
        repo_id=repo_id,
        branch=branch,
        workflow_name=workflow_name,
        limit=limit,
    )
    return [_to_ci_run(r) for r in runs]


def get_ci_run(run_id: uuid.UUID, team_id: int) -> contracts.CIRun:
    run = logic.get_ci_run(run_id=run_id, team_id=team_id)
    return _to_ci_run(run)


def list_tests_needing_attention(
    team_id: int,
    repo_id: uuid.UUID | None = None,
    suite: str | None = None,
    min_flake_score: float = 0.0,
    limit: int = 50,
) -> list[contracts.TestCase]:
    pairs = logic.list_tests_needing_attention(
        team_id=team_id,
        repo_id=repo_id,
        suite=suite,
        min_flake_score=min_flake_score,
        limit=limit,
    )
    return [_to_test_case(t, quarantine=_to_quarantine(q) if q else None) for t, q in pairs]


def get_test_case(test_case_id: uuid.UUID, team_id: int) -> contracts.TestCase:
    tc, q = logic.get_test_case_with_quarantine(test_case_id=test_case_id, team_id=team_id)
    return _to_test_case(tc, quarantine=_to_quarantine(q) if q else None)


def get_test_executions(
    test_case_id: uuid.UUID,
    team_id: int,
    limit: int = 100,
) -> list[contracts.TestExecution]:
    executions = logic.get_test_executions(test_case_id=test_case_id, team_id=team_id, limit=limit)
    return [_to_test_execution(e) for e in executions]


def get_ci_health(repo_id: uuid.UUID, team_id: int) -> contracts.CIHealth:
    repo = logic.get_repo(repo_id=repo_id, team_id=team_id)
    streak = logic.get_or_create_main_streak(repo_id=repo_id, team_id=team_id)
    stats = logic.get_health_stats(repo_id=repo_id, team_id=team_id)

    return contracts.CIHealth(
        repo=_to_repo(repo),
        streak=_to_main_streak(streak),
        flake_rate_7d=stats["flake_rate_7d"],
        total_runs_7d=stats["total_runs_7d"],
        total_flaky_tests_7d=stats["total_flaky_tests_7d"],
        tests_needing_attention=stats["tests_needing_attention"],
        active_quarantines=stats["active_quarantines"],
    )


def create_quarantine(input: contracts.CreateQuarantineInput) -> contracts.Quarantine:
    q = logic.create_quarantine(
        team_id=input.team_id,
        test_case_id=input.test_case_id,
        reason=input.reason,
        created_by_id=input.created_by_id,
        create_github_issue=input.create_github_issue,
    )
    return _to_quarantine(q)


def resolve_quarantine(input: contracts.ResolveQuarantineInput) -> contracts.Quarantine:
    q = logic.resolve_quarantine(
        quarantine_id=input.quarantine_id,
        team_id=input.team_id,
        resolved_by_id=input.resolved_by_id,
    )
    return _to_quarantine(q)
