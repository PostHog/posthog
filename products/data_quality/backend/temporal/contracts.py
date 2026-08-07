"""Inputs and outputs crossing the workflow/activity boundary.

Flat, JSON-friendly dataclasses: workflow inputs also arrive from the management-command CLI as a
single JSON object, so nested dataclasses would not survive ``parse_inputs``.
"""

import dataclasses


@dataclasses.dataclass
class RunCheckSuiteInputs:
    """What to run. Exactly one selector is expected; a suite with no matching checks is not an error.

    ``node_ids`` is the materialization path: the DAG workflow knows nodes, not saved queries, and
    the mapping is resolved inside the prepare activity so the workflow stays deterministic.
    """

    team_id: int
    trigger: str
    subject_type: str = ""
    subject_uuids: list[str] = dataclasses.field(default_factory=list)
    check_ids: list[str] = dataclasses.field(default_factory=list)
    node_ids: list[str] = dataclasses.field(default_factory=list)
    # Set when the caller already created the row so it could hand back a pollable handle.
    suite_run_id: str | None = None
    data_modeling_job_id: str | None = None
    created_by_id: int | None = None


@dataclasses.dataclass
class PreparedSuite:
    suite_run_id: str
    batches: list[list[str]]


@dataclasses.dataclass
class RunCheckBatchInputs:
    team_id: int
    suite_run_id: str
    check_ids: list[str]


@dataclasses.dataclass
class BatchOutcome:
    passed: int = 0
    failed: int = 0
    errored: int = 0
    skipped: int = 0
    newly_failing_check_ids: list[str] = dataclasses.field(default_factory=list)


@dataclasses.dataclass
class FinalizeCheckSuiteInputs:
    team_id: int
    suite_run_id: str
    outcomes: list[BatchOutcome]


@dataclasses.dataclass
class MarkSuiteFailedInputs:
    team_id: int
    suite_run_id: str
    error: str


@dataclasses.dataclass
class DueCheckGroup:
    """Checks on one subject that came due together, so they share a single suite run."""

    team_id: int
    subject_type: str
    subject_uuid: str
    check_ids: list[str]


@dataclasses.dataclass
class CleanupOutcome:
    compiled_queries_cleared: int = 0
    check_runs_deleted: int = 0
    suite_runs_deleted: int = 0


@dataclasses.dataclass
class CheckSuiteResult:
    suite_run_id: str
    status: str
    checks_passed: int = 0
    checks_failed: int = 0
    checks_errored: int = 0
    checks_skipped: int = 0
