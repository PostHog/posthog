"""
Contract types for ci_monitoring.

Stable, framework-free frozen dataclasses that define what this
product exposes to the rest of the codebase.
"""

from __future__ import annotations

import uuid
import datetime
from dataclasses import dataclass, field

from .enums import CIRunConclusion, QuarantineState, TestExecutionStatus

# --- Inputs ---


@dataclass(frozen=True)
class CreateRepoInput:
    team_id: int
    repo_external_id: int
    repo_full_name: str
    default_branch: str = "main"


@dataclass(frozen=True)
class IngestCIRunInput:
    team_id: int
    repo_id: uuid.UUID
    github_run_id: int
    workflow_name: str
    commit_sha: str
    branch: str
    conclusion: CIRunConclusion
    started_at: datetime.datetime
    completed_at: datetime.datetime
    pr_number: int | None = None


@dataclass(frozen=True)
class CreateQuarantineInput:
    team_id: int
    test_case_id: uuid.UUID
    reason: str
    created_by_id: int
    create_github_issue: bool = True


@dataclass(frozen=True)
class ResolveQuarantineInput:
    quarantine_id: uuid.UUID
    team_id: int
    resolved_by_id: int


# --- Outputs ---


@dataclass(frozen=True)
class Repo:
    id: uuid.UUID
    team_id: int
    repo_external_id: int
    repo_full_name: str
    default_branch: str
    created_at: datetime.datetime


@dataclass(frozen=True)
class CIRun:
    id: uuid.UUID
    team_id: int
    repo_id: uuid.UUID
    github_run_id: int
    workflow_name: str
    commit_sha: str
    branch: str
    pr_number: int | None
    conclusion: CIRunConclusion
    started_at: datetime.datetime
    completed_at: datetime.datetime
    total_tests: int
    passed: int
    failed: int
    flaky: int
    skipped: int
    errored: int
    artifacts_ingested: bool
    created_at: datetime.datetime


@dataclass(frozen=True)
class TestCase:
    id: uuid.UUID
    team_id: int
    repo_id: uuid.UUID
    identifier: str
    suite: str
    file_path: str | None
    team_area: str
    flake_score: float
    total_runs: int
    total_flakes: int
    first_seen_at: datetime.datetime
    last_seen_at: datetime.datetime
    last_flaked_at: datetime.datetime | None
    quarantine: Quarantine | None = None


@dataclass(frozen=True)
class TestExecution:
    id: uuid.UUID
    ci_run_id: uuid.UUID
    test_case_id: uuid.UUID
    status: TestExecutionStatus
    duration_ms: int | None
    error_message: str | None
    retry_count: int
    created_at: datetime.datetime


@dataclass(frozen=True)
class Quarantine:
    id: uuid.UUID
    test_case_id: uuid.UUID
    team_id: int
    reason: str
    state: QuarantineState
    github_issue_url: str | None
    github_pr_url: str | None
    created_by_id: int
    created_at: datetime.datetime
    resolved_at: datetime.datetime | None
    resolved_by_id: int | None


@dataclass(frozen=True)
class MainStreak:
    repo_id: uuid.UUID
    current_streak_days: int
    current_streak_started_at: datetime.datetime | None
    record_streak_days: int
    record_streak_start: datetime.datetime | None
    record_streak_end: datetime.datetime | None
    last_broken_at: datetime.datetime | None
    last_incident_workflows: list[str] = field(default_factory=list)
    is_broken_now: bool = False


@dataclass(frozen=True)
class CIHealth:
    repo: Repo
    streak: MainStreak
    flake_rate_7d: float  # 0.0-1.0
    total_runs_7d: int
    total_flaky_tests_7d: int
    tests_needing_attention: int
    active_quarantines: int
