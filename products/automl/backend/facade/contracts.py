"""
Contract types for AutoML.

Frozen dataclasses that define what this product exposes.
No Django imports. Used by the facade as inputs/outputs.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from .enums import AutonomyLevel, Cadence, ModelRole, PipelineStatus, RunKind, RunStatus, TaskType


class ValidationSeverity(StrEnum):
    """Severity tier for a validation finding.

    ``block`` findings prevent pipeline creation; ``warn`` surfaces requires-acknowledgement
    issues; ``info`` is annotative and never gates anything.
    """

    INFO = "info"
    WARN = "warn"
    BLOCK = "block"


@dataclass(frozen=True)
class AutoMLPipelineDTO:
    """The public shape of an AutoML pipeline."""

    id: UUID
    team_id: int
    name: str
    description: str
    task_type: TaskType
    status: PipelineStatus
    autonomy: AutonomyLevel
    config: dict[str, Any]
    training_population: dict[str, Any]
    inference_population: dict[str, Any]
    inference_cadence: Cadence
    retraining_cadence: Cadence
    output_property_name: str
    # System-managed runtime state (bootstrap_task_id, bootstrap_error, ...).
    # Model version pointers live on AutoMLModelVersion.role, not here.
    # Read-only from the API — populated by the facade's lifecycle methods.
    runtime: dict[str, Any]
    created_by_id: int | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class AutoMLModelVersionDTO:
    """The public shape of a trained model version on an AutoML pipeline.

    One row per training run. ``id`` is what lands on emitted predictions as
    ``$model_version_id``. ``role`` drives whether the version serves traffic
    (champion), runs head-to-head (challenger), or is audit-only (archived).
    """

    id: UUID
    pipeline_id: UUID
    team_id: int
    role: ModelRole
    metrics: dict[str, Any]
    leaderboard: list[dict[str, Any]]
    training_params: dict[str, Any]
    tracking_metadata: dict[str, Any]
    eval_metric: str
    problem_type: str
    artifact_uri: str
    features_hash: str
    rows_train: int | None
    rows_val: int | None
    rows_test: int | None
    training_task_id: UUID | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class RecordTrainingResultInput:
    """Inputs for persisting a completed training run as an ``AutoMLModelVersion``.

    Required: the metrics + leaderboard the trainer returned. Everything else is
    optional — defaults keep early bootstrap producers (where we don't yet have
    every field plumbed) viable without forcing them to fabricate values.

    ``role`` defaults to ``challenger`` so a newly trained model never auto-takes
    over from the existing champion. Promotion is a separate explicit step.
    """

    metrics: dict[str, Any]
    leaderboard: list[dict[str, Any]]
    role: ModelRole = ModelRole.CHALLENGER
    training_params: dict[str, Any] = field(default_factory=dict)
    tracking_metadata: dict[str, Any] = field(default_factory=dict)
    eval_metric: str = ""
    problem_type: str = ""
    artifact_uri: str = ""
    features_hash: str = ""
    rows_train: int | None = None
    rows_val: int | None = None
    rows_test: int | None = None
    training_task_id: UUID | None = None


@dataclass(frozen=True)
class CreatePipelineInput:
    """Request body for creating an AutoML pipeline.

    ``team_id`` and ``created_by_id`` are server-injected from the request scope
    and are not part of this DTO. Task-type-specific config lives in ``config``.
    """

    name: str
    task_type: TaskType
    config: dict[str, Any]
    training_population: dict[str, Any]
    inference_population: dict[str, Any]
    description: str = ""
    autonomy: AutonomyLevel = AutonomyLevel.CHAMPION_ONLY
    inference_cadence: Cadence = Cadence.DAILY
    retraining_cadence: Cadence = Cadence.DAILY
    output_property_name: str = ""


@dataclass(frozen=True)
class UpdatePipelineInput:
    """Partial-update body for an AutoML pipeline. None means leave unchanged.

    Status transitions go through dedicated facade methods (start / pause /
    resume / archive) so the lifecycle stays explicit.
    """

    name: str | None = None
    description: str | None = None
    autonomy: AutonomyLevel | None = None
    inference_cadence: Cadence | None = None
    retraining_cadence: Cadence | None = None
    output_property_name: str | None = None
    config: dict[str, Any] | None = None
    training_population: dict[str, Any] | None = None
    inference_population: dict[str, Any] | None = None
    extra: dict[str, Any] = field(default_factory=dict)


class PipelineNotFoundError(Exception):
    """Raised by the facade when a pipeline lookup misses."""


class PipelineStateTransitionError(Exception):
    """Raised when a status transition isn't allowed from the current state."""


class ModelVersionNotFoundError(Exception):
    """Raised by the facade when a model-version lookup misses (wrong team or wrong id)."""


class PipelineRunNotFoundError(Exception):
    """Raised by the facade when a pipeline-run lookup misses (wrong team or wrong id)."""


@dataclass(frozen=True)
class AutoMLPipelineRunDTO:
    """The public shape of a single pipeline run.

    One row per bootstrap / retrain / inference attempt, regardless of outcome.
    Durable home for the agent's outcome report, EDA summary, and failure
    reason — anything that lives inside the sandbox container and would
    otherwise die with it. ``id`` shows up on the pipeline detail page and
    in the retraining loop's iteration chain (``parent_run_id``).

    See `io-spec.md`'s "Per pipeline run (durable record)" section in the
    `/phs automl` skill for the full design rationale.
    """

    id: UUID
    pipeline_id: UUID
    team_id: int
    run_kind: RunKind
    status: RunStatus
    task_slug: str
    task_workspace_root: str
    cli_run_id: str
    agent_session_id: str
    task_id: UUID | None
    started_at: datetime
    completed_at: datetime | None
    outcome_report: str
    eda_result: dict[str, Any]
    training_result: dict[str, Any]
    failure_reason: str
    created_model_version_id: UUID | None
    parent_run_id: UUID | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class CreatePipelineRunInput:
    """Inputs for opening a new ``AutoMLPipelineRun`` row.

    Called by lifecycle helpers (bootstrap enqueue, scheduled retrain dispatch,
    scheduled inference dispatch) — not exposed via MCP. The row starts in
    ``status=running`` with the workspace + slug already pinned, so subsequent
    record_* calls just slot in their pieces.
    """

    run_kind: RunKind
    task_slug: str
    task_workspace_root: str
    task_id: UUID | None = None
    parent_run_id: UUID | None = None


@dataclass(frozen=True)
class RecordEdaResultInput:
    """Inputs for the ``automl-record-eda-result`` MCP tool.

    Called by the agent between EDA and training. Holds the structured EDA
    summary (class balance, top-signal features, dropped features, leakage
    warnings, full `eda_uri` from the CLI's `eda.yaml`). Schemaless on purpose
    — the CLI's output format will evolve and we don't want to gate updates
    on a migration.
    """

    eda_result: dict[str, Any]
    cli_run_id: str = ""


@dataclass(frozen=True)
class RecordBootstrapOutcomeInput:
    """Inputs for the ``automl-record-bootstrap-outcome`` MCP tool.

    Called by the agent as the final checkpoint of a bootstrap run. The agent
    writes the full markdown outcome report and a terminal status. Pipeline
    status transitions hang off this — ``succeeded`` with a champion lifts
    the pipeline into ``ACTIVE``; ``failed`` lifts it into ``FAILED``.
    """

    status: RunStatus
    outcome_report: str
    failure_reason: str = ""
    cli_run_id: str = ""
    agent_session_id: str = ""


@dataclass(frozen=True)
class ValidationFinding:
    """One result from preflight validation.

    Findings are emitted by the validate facade method against a proposed pipeline
    config. Callers should treat ``block`` as a hard gate before creating the pipeline,
    ``warn`` as an issue that requires user acknowledgement, and ``info`` as advisory.
    """

    severity: ValidationSeverity
    code: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ValidationSummary:
    """Quantitative summary of a validation run.

    Fields are best-effort: any number derived from a HogQL count query may be
    ``None`` if the underlying query failed or the population kind isn't supported.
    """

    task_type: TaskType
    training_population_kind: str
    estimated_training_rows: int | None = None
    estimated_inference_rows: int | None = None
    estimated_inference_events_per_day: int | None = None
    estimated_positive_count: int | None = None
    estimated_positive_rate: float | None = None
    target_event: str | None = None
    estimated_series_count: int | None = None
    estimated_rows_per_cluster: float | None = None


@dataclass(frozen=True)
class ValidationReport:
    """Result of running preflight validation against a proposed pipeline config.

    ``ok`` is derived from findings — true iff zero ``block`` findings are present.
    Callers should not mutate findings or summary; both are intended for direct
    serialization to the API response.
    """

    ok: bool
    findings: list[ValidationFinding]
    summary: ValidationSummary
