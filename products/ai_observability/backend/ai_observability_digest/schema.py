from __future__ import annotations

from pydantic import BaseModel, Field


class OverviewSection(BaseModel):
    """One topic of the AI observability overview (errors, costly users, evals, …)."""

    title: str = Field(
        max_length=120,
        description="Short section title, e.g. 'Errors', 'Costliest users', 'Evaluation pass rates', 'LLM latency'.",
    )
    body: str = Field(
        description="Markdown summary of this section, grounded in retrieved data. Include concrete numbers.",
    )


class AIObservabilityOverview(BaseModel):
    """Structured status of a team's AI observability, produced by the digest agent."""

    headline: str = Field(
        max_length=150,
        description="One-line headline summarizing overall AI observability health for the day.",
    )
    summary: str = Field(
        description="A short (2-4 sentence) executive summary of the team's AI observability status.",
    )
    sections: list[OverviewSection] = Field(
        default_factory=list,
        description=(
            "Per-topic sections (errors, costliest users, tool usage/errors, evaluation pass rates, "
            "cluster results, LLM latencies, …). Include only sections you actually have data for."
        ),
    )
