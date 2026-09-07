"""Inputs and outputs crossing the workflow/activity boundary.

Flat, JSON-friendly dataclasses: workflow inputs also arrive from the management-command CLI as a
single JSON object, so nested dataclasses would not survive ``parse_inputs``.
"""

import dataclasses

from posthog.dataclasses import frozen

from ..facade.enums import SuiteRunStatus, SuiteRunTrigger


@frozen
class RunCheckSuiteInputs:
    """What to run. Exactly one selector is expected; a suite with no matching checks is not an error.

    ``node_ids`` is the materialization path: the DAG workflow knows nodes, not saved queries, and
    the mapping is resolved inside the prepare activity so the workflow stays deterministic.
    ``table_ids`` is the source-sync path, keyed on the table so it works with or without a DAG.
    """

    team_id: int
    trigger: SuiteRunTrigger
    saved_query_ids: list[str] = dataclasses.field(default_factory=list)
    table_ids: list[str] = dataclasses.field(default_factory=list)
    check_ids: list[str] = dataclasses.field(default_factory=list)
    node_ids: list[str] = dataclasses.field(default_factory=list)
    suite_run_id: str | None = None
    data_modeling_job_id: str | None = None
    created_by_id: int | None = None
    # Audits the staged folder rather than the published table. Needs exactly one saved query.
    staged_queryable_folder: str | None = None


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
