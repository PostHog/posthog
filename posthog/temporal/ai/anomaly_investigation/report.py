from typing import Literal

from pydantic import BaseModel, Field


class InvestigationHypothesis(BaseModel):
    """A single hypothesis proposed by the agent, with supporting evidence."""

    title: str = Field(description="Short name of the hypothesis, e.g. 'Bot traffic spike'.")
    rationale: str = Field(description="Why the agent thinks this hypothesis explains the anomaly.")
    evidence: list[str] = Field(
        default_factory=list,
        description="Bullet points of concrete evidence. Keep each line short and factual.",
    )


class InvestigationReport(BaseModel):
    """Structured output the agent emits as its final message. Rendered into a Notebook."""

    verdict: Literal["true_positive", "false_positive", "inconclusive"] = Field(
        description=(
            "Agent's validation call on the alert firing. Use 'true_positive' when the anomaly "
            "is real and business-relevant, 'false_positive' when it's a data/release artifact "
            "or noise that shouldn't have fired, or 'inconclusive' when there isn't enough "
            "evidence to decide."
        ),
    )
    summary: str = Field(description="1-3 sentence plain-English summary of what happened.")
    hypotheses: list[InvestigationHypothesis] = Field(
        default_factory=list,
        description="Ordered by likelihood; top 2-3 hypotheses.",
    )
    recommendations: list[str] = Field(
        default_factory=list,
        description="Suggested next actions for the on-call engineer or product owner.",
    )
    tool_calls_used: int = Field(default=0, description="Number of tool calls the agent made, for audit.")
