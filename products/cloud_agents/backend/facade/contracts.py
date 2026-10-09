"""
Contract types for cloud_agents.

Frozen dataclasses and typed errors that define what this product exposes.
No Django or DRF imports. The facade takes and returns these types.
"""

from __future__ import annotations

from dataclasses import field
from datetime import datetime
from decimal import Decimal
from typing import Any, ClassVar
from uuid import UUID

from posthog.dataclasses import frozen

from .enums import (
    BillingMode,
    CallerKind,
    CloudAgentReasoningEffort,
    CloudAgentRunStatus,
    CloudAgentRunStatusReason,
    CloudAgentSessionStatus,
    InferenceBilling,
    InferenceMode,
    SizeName,
    UsageGroupBy,
    size_shape,
)


@frozen
class CallerIdentity:
    """Who started an operation. `user_id` is None for a caller that is not a person."""

    user_id: int | None
    distinct_id: str | None
    kind: CallerKind
    billable: bool
    product: str | None = None


@frozen
class SizeSpec:
    """A sandbox size and its public price for one hour."""

    name: SizeName
    vcpu: int
    memory_gib: int
    price_per_hour_usd: Decimal

    @classmethod
    def from_name(cls, name: SizeName, *, price_per_hour_usd: Decimal) -> SizeSpec:
        shape = size_shape(name)
        return cls(name=name, vcpu=shape.vcpu, memory_gib=shape.memory_gib, price_per_hour_usd=price_per_hour_usd)


@frozen
class RepositoryRef:
    """A GitHub repository, as `owner/name`, and the branch that the agent starts from.

    With no `initial_branch`, the agent starts from the default branch of the repository.
    """

    name: str
    initial_branch: str | None = None

    def to_json(self) -> dict[str, Any]:
        return {"name": self.name, "initial_branch": self.initial_branch}

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> RepositoryRef:
        return cls(name=data["name"], initial_branch=data.get("initial_branch"))


@frozen
class RunCreateInput:
    """One request to start a run. `preset` is a preset id or a preset name."""

    prompt: str
    repositories: list[RepositoryRef] | None = None
    preset: str | None = None
    model: str | None = None
    reasoning_effort: CloudAgentReasoningEffort | None = None
    size: SizeName | None = None
    inference: InferenceMode | None = None
    instructions: str | None = None
    create_pr: bool | None = None
    idle_minutes: int | None = None
    output_schema: dict[str, Any] | None = None
    tags: list[str] | None = None
    metadata: dict[str, Any] | None = None
    idempotency_key: str | None = None


@frozen
class PresetDTO:
    id: UUID
    name: str
    description: str
    repositories: list[RepositoryRef] | None
    model: str | None
    reasoning_effort: CloudAgentReasoningEffort | None
    size: SizeName | None
    inference: InferenceMode | None
    instructions: str | None
    create_pr: bool | None
    idle_minutes: int | None
    output_schema: dict[str, Any] | None
    tags: list[str]
    created_by_id: int | None
    created_at: datetime
    updated_at: datetime


@frozen
class PresetCreateInput:
    name: str
    description: str = ""
    repositories: list[RepositoryRef] | None = None
    model: str | None = None
    reasoning_effort: CloudAgentReasoningEffort | None = None
    size: SizeName | None = None
    inference: InferenceMode | None = None
    instructions: str | None = None
    create_pr: bool | None = None
    idle_minutes: int | None = None
    output_schema: dict[str, Any] | None = None
    tags: list[str] = field(default_factory=list)


@frozen
class TeamSettingsDTO:
    """Project defaults for runs. The limits are the effective values, after any override."""

    repositories: list[RepositoryRef] | None
    model: str | None
    reasoning_effort: CloudAgentReasoningEffort | None
    size: SizeName | None
    inference: InferenceMode | None
    instructions: str | None
    create_pr: bool | None
    idle_minutes: int | None
    output_schema: dict[str, Any] | None
    default_preset_id: UUID | None
    max_concurrent_runs: int
    create_rate_per_hour: int
    updated_at: datetime | None


@frozen
class ResolvedRunConfig:
    """The configuration a run uses, after the call, the preset, the project and the product defaults are merged."""

    repositories: list[RepositoryRef]
    model: str | None
    reasoning_effort: CloudAgentReasoningEffort | None
    size: SizeName
    inference: InferenceMode
    instructions: str | None
    create_pr: bool
    idle_minutes: int
    output_schema: dict[str, Any] | None
    tags: list[str]
    preset_id: UUID | None

    def to_json(self) -> dict[str, Any]:
        return {
            "repositories": [repository.to_json() for repository in self.repositories],
            "model": self.model,
            "reasoning_effort": None if self.reasoning_effort is None else self.reasoning_effort.value,
            "size": self.size.value,
            "inference": self.inference.value,
            "instructions": self.instructions,
            "create_pr": self.create_pr,
            "idle_minutes": self.idle_minutes,
            "output_schema": self.output_schema,
            "tags": list(self.tags),
            "preset_id": None if self.preset_id is None else str(self.preset_id),
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> ResolvedRunConfig:
        reasoning_effort = data.get("reasoning_effort")
        preset_id = data.get("preset_id")
        return cls(
            repositories=[RepositoryRef.from_json(repository) for repository in data["repositories"]],
            model=data.get("model"),
            reasoning_effort=None if reasoning_effort is None else CloudAgentReasoningEffort(reasoning_effort),
            size=SizeName(data["size"]),
            inference=InferenceMode(data["inference"]),
            instructions=data.get("instructions"),
            create_pr=data["create_pr"],
            idle_minutes=data["idle_minutes"],
            output_schema=data.get("output_schema"),
            tags=list(data.get("tags") or []),
            preset_id=None if preset_id is None else UUID(str(preset_id)),
        )


@frozen
class AgentSessionDTO:
    index: int
    task_run_id: UUID
    status: CloudAgentSessionStatus
    started_at: datetime | None
    ended_at: datetime | None


@frozen
class RunResultDTO:
    """`output` is the result that matches the output schema of the run. None for a run with no schema."""

    pr_url: str | None
    pr_urls: list[str]
    summary: str | None
    output: dict[str, Any] | None


@frozen
class RunCostDTO:
    compute_usd: Decimal | None
    inference_usd: Decimal | None
    total_usd: Decimal | None
    vcpu_seconds: Decimal | None
    gib_seconds: Decimal | None
    billing_mode: BillingMode
    inference_billing: InferenceBilling | None
    final: bool


@frozen
class RunDTO:
    id: UUID
    status: CloudAgentRunStatus
    status_reason: CloudAgentRunStatusReason | None
    status_detail: str | None
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None
    ended_at: datetime | None
    prompt: str
    repositories: list[RepositoryRef]
    preset_id: UUID | None
    preset_name: str | None
    config: ResolvedRunConfig
    size: SizeSpec
    result: RunResultDTO
    cost: RunCostDTO
    agent_sessions: list[AgentSessionDTO]
    tags: list[str]
    metadata: dict[str, Any]
    created_by_id: int | None
    created_by_email: str | None
    caller_kind: CallerKind


@frozen
class MessageResult:
    """`resumed` is True when the message started a new agent session, and False when a live session got it."""

    resumed: bool
    run: RunDTO


@frozen
class RunListFilters:
    status: CloudAgentRunStatus | None = None
    preset_id: UUID | None = None
    repository: str | None = None
    tag: str | None = None
    created_after: datetime | None = None
    created_before: datetime | None = None


@frozen
class SandboxSessionUsageDTO:
    """One sandbox of a run and its compute charge. A waived session has a zero charge."""

    vcpu: Decimal
    memory_gib: Decimal
    started_at: datetime
    ended_at: datetime | None
    seconds: int
    cost_usd: Decimal
    waived: bool


@frozen
class RunUsageDTO:
    run_id: UUID
    cost: RunCostDTO
    sessions: list[SandboxSessionUsageDTO]


@frozen
class RunEventsDTO:
    """`truncated` is True when the log is too large. `events` then holds the earliest sessions that fit."""

    events: list[dict[str, Any]]
    truncated: bool


@frozen
class RunEventStream:
    """One client connection to the live events of a run. `source` is an opaque handle for the stream body."""

    run: RunDTO
    source: object


@frozen
class ModelDTO:
    id: str
    name: str
    runtime_adapter: str
    is_default: bool


@frozen
class RateCardDTO:
    vcpu_hour_usd: Decimal
    memory_gib_hour_usd: Decimal
    version: str


@frozen
class LimitsDTO:
    max_concurrent_runs: int
    create_rate_per_hour: int


@frozen
class CatalogDTO:
    sizes: list[SizeSpec]
    models: list[ModelDTO]
    inference_modes: list[InferenceMode]
    rates: RateCardDTO
    limits: LimitsDTO


@frozen
class EstimateDTO:
    size: SizeName
    minutes: int
    price_per_hour_usd: Decimal
    estimate_usd: Decimal


@frozen
class UsageTotalsDTO:
    """Costs are sums over the runs that have a cost. A run on the customer's own credential adds no inference cost."""

    runs: int
    compute_usd: Decimal
    inference_usd: Decimal
    total_usd: Decimal
    vcpu_seconds: Decimal
    gib_seconds: Decimal


@frozen
class UsageBucketDTO:
    """`key` is a date for `group_by=day`, and a preset id or None for `group_by=preset`."""

    key: str | None
    label: str | None
    usage: UsageTotalsDTO


@frozen
class UsageSummaryDTO:
    date_from: datetime
    date_to: datetime
    group_by: UsageGroupBy
    totals: UsageTotalsDTO
    buckets: list[UsageBucketDTO]


class CloudAgentsError(Exception):
    """Base class for errors a caller can act on. `message` is safe to show to the caller."""

    code: ClassVar[str] = "cloud_agents_error"
    status_code: ClassVar[int] = 400
    default_message: ClassVar[str] = "The request could not be completed."

    def __init__(self, message: str | None = None) -> None:
        self.message = message or self.default_message
        super().__init__(self.message)


class InvalidInput(CloudAgentsError):
    code = "invalid_input"
    default_message = "The request is not valid."

    def __init__(self, message: str | None = None, *, attr: str | None = None) -> None:
        super().__init__(message)
        self.attr = attr


class RunNotFound(CloudAgentsError):
    code = "run_not_found"
    status_code = 404
    default_message = "This run does not exist in this project."


class PresetNotFound(CloudAgentsError):
    code = "preset_not_found"
    status_code = 404
    default_message = "This preset does not exist in this project."


class RepositoryRequired(InvalidInput):
    code = "repository_required"
    default_message = "Set a repository on the run, on its preset, or in the project settings."

    def __init__(self) -> None:
        super().__init__(attr="repositories")


class IdempotencyKeyReused(CloudAgentsError):
    code = "idempotency_key_reused"
    status_code = 422
    default_message = "This idempotency key was used with a different request. Use a new key."


class RunStopping(CloudAgentsError):
    code = "run_stopping"
    status_code = 409
    default_message = "This run is stopping. Wait until it stops, then try again."


class RunDone(CloudAgentsError):
    code = "run_done"
    status_code = 409
    default_message = "This run is done and cannot continue. Start a new run."


class RunNotResumable(CloudAgentsError):
    code = "run_not_resumable"
    status_code = 409
    default_message = "This run cannot be resumed. Start a new run."


class UsageLimited(CloudAgentsError):
    code = "usage_limited"
    status_code = 429
    default_message = "This project reached its usage limit. Raise the limit in billing settings, then try again."

    def __init__(self, message: str | None = None, *, retry_after: int | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class OrganizationDeactivated(CloudAgentsError):
    code = "organization_deactivated"
    status_code = 403
    default_message = "This organization is deactivated, so it cannot run cloud agents. Contact support."


class CredentialOwnerRequired(CloudAgentsError):
    code = "credential_owner_required"
    status_code = 403
    default_message = "This run uses the subscription of the user who started it. Only that user can send it a message."


class RunNotReady(CloudAgentsError):
    code = "run_not_ready"
    status_code = 409
    default_message = "This run is still starting. Try again in a few seconds."


class RunCancelUnavailable(CloudAgentsError):
    code = "cancel_unavailable"
    status_code = 503
    default_message = "The run could not be cancelled now. Try again in a few seconds."
    retry_after: ClassVar[int] = 5


class ConcurrencyLimited(CloudAgentsError):
    code = "concurrency_limited"
    status_code = 429
    retry_after: ClassVar[int] = 30

    def __init__(self, *, limit: int, active: int) -> None:
        super().__init__(
            f"This project runs {active} agents and the limit is {limit}. Wait until a run stops, then try again."
        )
        self.limit = limit
        self.active = active


class CreateRateLimited(CloudAgentsError):
    code = "create_rate_limited"
    status_code = 429

    def __init__(self, *, retry_after: int) -> None:
        super().__init__(f"This project starts runs too quickly. Try again in {retry_after} seconds.")
        self.retry_after = retry_after
