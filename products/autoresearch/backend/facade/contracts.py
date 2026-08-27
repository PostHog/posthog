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
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic.dataclasses import dataclass


class PipelineNotFound(LookupError):
    """No pipeline with that id in this team."""


class AutoresearchConflict(ValueError):
    """The request is well-formed but the pipeline or run is in the wrong state for it.

    The viewset maps it to a 400 with the message as-is, so the message is user-facing copy.
    """


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
