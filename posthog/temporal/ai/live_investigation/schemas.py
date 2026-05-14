"""Pydantic schemas for the live investigation primitive.

Kept free of Django imports so workflow code can import these directly
(workflow modules can't pull in heavy ORM machinery at definition time).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class LiveInvestigationBrief(BaseModel):
    """Handoff doc the calling agent writes when starting an investigation.

    Read by the followup agent when probe data has accumulated and analysis runs.
    The brief is what bridges across the agent-run boundary, not the calling
    agent's conversation history.
    """

    hypothesis: str = Field(description="One-sentence hypothesis the probes are meant to confirm or refute.")
    what_to_look_for: list[str] = Field(
        description="Specific patterns in probe events that would support or refute the hypothesis. "
        "Concrete and observable — 'session_id is non-null but user_id is null', "
        "not 'something is off in auth'."
    )
    instrumentation_rationale: str = Field(
        description="Why probes are placed where they are. The followup agent reads this to understand "
        "what the calling agent expected to see, so it can recognize when reality diverges."
    )
    signal_summary: str = Field(
        description="What triggered this investigation. Free-form summary of the originating signal — "
        "preserves context that doesn't live in PostHog."
    )
    parent_summary: str | None = Field(
        default=None,
        description="Set when this investigation is a chained followup. The parent investigation's "
        "findings summary, so this run knows what its predecessor concluded.",
    )


FindingsStatus = Literal[
    "definitive",
    "needs_more_data",
    "needs_different_probe",
    "spawned_followup",
    "gave_up",
]

HypothesisOutcome = Literal["confirmed", "refuted", "partial", "unrelated", "inconclusive"]


class LiveInvestigationFindings(BaseModel):
    """Structured output the followup agent emits as its final message."""

    status: FindingsStatus
    summary: str = Field(description="1–3 sentence plain-English conclusion.")
    confidence: float = Field(ge=0.0, le=1.0, description="Agent's self-assessed confidence.")
    hypothesis_outcome: HypothesisOutcome
    evidence_event_ids: list[str] = Field(
        default_factory=list,
        description="UUIDs of probe events that drove the conclusion. Used by downstream "
        "renderers to link back to raw evidence.",
    )
    next_step_rationale: str | None = Field(
        default=None,
        description="Required when status is needs_more_data, needs_different_probe, or spawned_followup.",
    )
    spawned_followup_id: str | None = Field(
        default=None,
        description="Set when status=spawned_followup. The child LiveInvestigation.id the agent created.",
    )


@dataclass
class LiveInvestigationWorkflowInput:
    """Input to LiveInvestigationWorkflow."""

    investigation_id: str
    program_id: str
    max_duration_seconds: int


@dataclass
class AnalyzeInput:
    """Input to analyze_live_investigation_activity."""

    investigation_id: str


@dataclass
class UninstallInput:
    """Input to uninstall_program_activity."""

    program_id: str


@dataclass
class MarkCancelledInput:
    """Input to mark_investigation_cancelled_activity."""

    investigation_id: str


class StartLiveInvestigationArgs(BaseModel):
    """Tool-call args for any agent that wants to start a live investigation."""

    hogtrace_code: str = Field(description="The hogtrace program source to install.")
    brief: LiveInvestigationBrief = Field(
        description="Hypothesis, what to look for, instrumentation rationale. "
        "Read by the followup agent when probe data arrives."
    )
    min_events: int = Field(default=20, ge=1, le=500)
    max_duration_minutes: int = Field(default=120, ge=5, le=24 * 60)
    parent_investigation_id: UUID | None = Field(
        default=None,
        description="Set when chaining from an existing investigation's findings.",
    )
