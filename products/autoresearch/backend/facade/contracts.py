"""
Contract types for autoresearch.

Stable, framework-free frozen dataclasses that define what this product exposes to
the rest of the codebase, and what its own presentation layer serializes. No Django
imports.

These use ``pydantic.dataclasses.dataclass`` rather than the stdlib variant — same
syntax and ``is_dataclass()`` compatibility, but with runtime validation on
construction, so structural mistakes from mappers surface at the facade boundary
instead of producing a malformed payload deeper in a caller.

Some contracts use the stdlib variant instead. A contract a ``DataclassSerializer``
constructs from a partial request body needs defaults on every field and no runtime
validation of the half-built value, which pydantic would reject.
"""

from dataclasses import (
    dataclass as stdlib_dataclass,
    field,
)
from datetime import date, datetime
from typing import Any
from uuid import UUID

from pydantic.dataclasses import dataclass


class PipelineNotFound(LookupError):
    """No pipeline with that id in this team."""


class TrainingRunNotFound(LookupError):
    """No training run with that id in this team."""


class SuggestionNotFound(LookupError):
    """No suggestion with that id on this pipeline."""


class AutoresearchConflict(ValueError):
    """The request is well-formed but the pipeline or run is in the wrong state for it.

    The viewset maps it to a 400 with the message as-is, so the message is user-facing copy.
    """


class ArtifactNotFound(LookupError):
    """No artifact at that path in the run's bundle."""


class InvalidArtifactPath(ValueError):
    """The artifact path escapes the bundle prefix or is otherwise unusable."""


# ── Model-backed read contracts ────────────────────────────────────────────


@dataclass(frozen=True, config={"arbitrary_types_allowed": True})
class Pipeline:
    """One prediction pipeline: a target, a population, and a horizon.

    ``created_by`` carries the core ``User`` row rather than a projection of it, so the
    presentation layer keeps serializing it through core's ``UserBasicSerializer`` and the
    generated ``UserBasic`` component stays as it was.
    """

    id: UUID
    name: str
    description: str
    target_event: str
    target_definition: dict[str, Any]
    horizon_days: int
    training_lookback_days: int
    training_population: dict[str, Any]
    inference_population: dict[str, Any]
    cadence_days: int
    iteration_budget: int
    iteration_budget_remaining: int
    success_auc: float | None
    plateau_iterations: int
    output_person_property: str
    status: str
    created_by: Any
    created_at: datetime
    updated_at: datetime
    last_scored_at: datetime | None
    champion_holdout_auc: float | None
    champion_realized_auc: float | None


@dataclass(frozen=True)
class Model:
    """A persisted, versioned champion or challenger recipe."""

    id: UUID
    pipeline: UUID
    role: str
    recipe_hash: str
    model_recipe: dict[str, Any]
    model_explanation: dict[str, Any]
    holdout_score: float | None
    realized_score: float | None
    calibration_error: float | None
    metrics: dict[str, Any]
    source_training_run: UUID | None
    agent_description: str
    trained_on_start: date | None
    trained_on_end: date | None
    is_preliminary: bool
    promoted_at: datetime | None
    archived_at: datetime | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class IterationTrailEntry:
    """Compact view of one iteration, for the history feed and the Training tab."""

    iteration_number: int
    status: str
    holdout_score: float | None
    train_score: float | None
    agent_description: str
    model_spec: dict[str, Any]


@dataclass(frozen=True)
class TrainingRunSummaryLadderItem:
    iteration_number: int
    holdout_score: float | None
    model_class: str
    agent_description: str


@dataclass(frozen=True)
class TrainingRunSummary:
    """Tier-1 distilled summary of a completed run — what a new run reads first."""

    target_event: str
    horizon_days: int
    best_holdout_score: float | None
    champion_promoted: bool
    champion_model_class: str
    kept_ladder: list[TrainingRunSummaryLadderItem]
    dead_ends: list[TrainingRunSummaryLadderItem]
    recommended_next: str
    distillation: str


@dataclass(frozen=True)
class TrainingRun:
    """One bounded training session backed by a Task/TaskRun sandbox."""

    id: UUID
    pipeline: UUID
    task_id: UUID | None
    task_run_id: UUID | None
    task_url: str | None
    status: str
    iteration_budget: int
    iteration_count: int
    best_holdout_score: float | None
    summary: dict[str, Any] | None
    iterations: list[IterationTrailEntry]
    error: str
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime


@dataclass(frozen=True)
class Iteration:
    """One recipe attempt within a training run."""

    id: UUID
    pipeline: UUID
    training_run: UUID
    iteration_number: int
    recipe_hash: str
    recipe_snapshot: dict[str, Any]
    model_spec: dict[str, Any]
    train_score: float | None
    holdout_score: float | None
    status: str
    agent_description: str
    agent_confidence: float | None
    parent_suggestion: UUID | None
    created_at: datetime


@dataclass(frozen=True, config={"arbitrary_types_allowed": True})
class Suggestion:
    """A free-text hypothesis injected into a running pipeline by a user or agent."""

    id: UUID
    pipeline: UUID
    prompt: str
    priority: str
    status: str
    source: str
    agent_response: str
    created_by: Any
    linked_iteration_ids: list[UUID]
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class Run:
    """Generic operational run: inference or validation."""

    id: UUID
    pipeline: UUID
    model: UUID | None
    run_type: str
    status: str
    rows_scored: int | None
    metrics: dict[str, Any]
    error: str
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime


# ── Write contracts ────────────────────────────────────────────────────────


@stdlib_dataclass(frozen=True)
class PipelineWrite:
    """A create or update body for a pipeline.

    Stdlib dataclass with a default on every field, so the wrapping ``DataclassSerializer``
    can build it from a partial (PATCH) body. Which fields are actually applied is decided
    by the raw request keys, not by these defaults.
    """

    name: str = ""
    description: str = ""
    target_event: str = ""
    target_definition: dict[str, Any] = field(default_factory=dict)
    horizon_days: int = 7
    training_lookback_days: int = 180
    training_population: dict[str, Any] = field(default_factory=dict)
    inference_population: dict[str, Any] = field(default_factory=dict)
    cadence_days: int = 1
    iteration_budget: int = 50
    success_auc: float | None = None
    plateau_iterations: int = 10
    output_person_property: str = ""


# ── Validation and template contracts ──────────────────────────────────────


@dataclass(frozen=True)
class ValidationWarning:
    code: str
    message: str
    severity: str


@dataclass(frozen=True)
class PipelineValidation:
    """Volume, base rate, and warnings for a proposed pipeline definition."""

    can_proceed: bool
    requires_acknowledgement: bool
    estimated_training_rows: int | None
    positive_count: int | None
    negative_count: int | None
    base_rate: float | None
    inference_population_size: int | None
    warnings: list[ValidationWarning]
    error: str | None


@dataclass(frozen=True)
class TemplateInfo:
    key: str
    display_name: str
    description: str
    default_horizon_days: int
    requires_user_event: bool
    requires_activity_resolution: bool
    notes: str


@dataclass(frozen=True)
class ResolvedTemplate:
    template_key: str
    display_name: str
    description: str
    suggested_name: str
    target_event: str
    resolved_activity_event: str | None
    activity_event_alternatives: list[str]
    horizon_days: int
    training_population: dict[str, Any]
    inference_population: dict[str, Any]
    output_person_property: str
    notes: str


# ── Training-run history ───────────────────────────────────────────────────


@dataclass(frozen=True)
class TrainingRunHistoryEntry:
    run_id: UUID
    pipeline_id: UUID
    is_current_pipeline: bool
    target_event: str
    horizon_days: int
    best_holdout_score: float | None
    iteration_count: int
    completed_at: datetime | None
    summary: dict[str, Any] | None
    iterations: list[IterationTrailEntry]


@dataclass(frozen=True)
class TrainingRunHistory:
    runs: list[TrainingRunHistoryEntry]


# ── Artifact bundle ────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ArtifactList:
    paths: list[str]
    count: int


@dataclass(frozen=True)
class StoredArtifact:
    path: str
    size_bytes: int
    sha256: str


@dataclass(frozen=True)
class ArtifactContent:
    path: str
    size_bytes: int
    sha256: str
    content_base64: str


@dataclass(frozen=True)
class ArtifactDeleteResult:
    path: str
    deleted: bool


# ── Feature materialization ────────────────────────────────────────────────


@dataclass(frozen=True)
class MaterializedFeatures:
    """Sandbox paths and shape of the parquet the agent reads with ``pd.read_parquet``."""

    train_features_path: str
    train_labels_path: str
    holdout_features_path: str
    holdout_labels_path: str
    n_train: int
    n_holdout: int
    n_features: int
    feature_cols: list[str]
