"""Inputs and outputs crossing the workflow/activity boundary.

Flat, JSON-friendly dataclasses: workflow inputs also arrive from the management-command CLI as a
single JSON object, so nested dataclasses would not survive ``parse_inputs``.
"""

import dataclasses

from posthog.dataclasses import frozen

from ..facade.contracts import RunCheckSuiteInputs as RunCheckSuiteInputs
from ..facade.enums import SuiteRunStatus


@frozen
class MaterializationGateInputs:
    team_id: int
    node_ids: list[str]


@frozen
class PreparedSuite:
    suite_run_id: str
    batches: list[list[str]]


@frozen
class RunCheckBatchInputs:
    team_id: int
    suite_run_id: str
    check_ids: list[str]
    staged_queryable_folder: str | None = None
    staged_saved_query_id: str | None = None


@frozen
class BatchOutcome:
    passed: int = 0
    failed: int = 0
    errored: int = 0
    skipped: int = 0
    failed_blocking: int = 0
    newly_failing_check_ids: list[str] = dataclasses.field(default_factory=list)


@frozen
class FinalizeCheckSuiteInputs:
    team_id: int
    suite_run_id: str
    outcomes: list[BatchOutcome]


@frozen
class MarkSuiteFailedInputs:
    team_id: int
    suite_run_id: str
    error: str


@frozen
class CleanupOutcome:
    compiled_queries_cleared: int = 0
    checks_deleted: int = 0
    check_runs_deleted: int = 0
    suite_runs_deleted: int = 0
    stale_suites_failed: int = 0


@frozen
class CheckSuiteResult:
    suite_run_id: str
    status: SuiteRunStatus
    checks_passed: int = 0
    checks_failed: int = 0
    checks_errored: int = 0
    checks_skipped: int = 0
    checks_failed_blocking: int = 0
