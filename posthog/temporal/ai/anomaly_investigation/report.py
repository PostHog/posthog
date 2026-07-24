import re
import json
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

# Sonnet 5 (adaptive thinking) sometimes serializes a nested list argument as a single
# string with its internal text-tool-call syntax leaking in, e.g. a stray
# `<parameter name="hypothesis">` wrapping a JSON array. Strip the tag so the embedded
# JSON can be recovered instead of failing validation and collapsing to 'inconclusive'.
_LEAKED_PARAM_TAG_RE = re.compile(r"</?\s*parameter\b[^>]*>", re.IGNORECASE)


def _recover_stringified_list(value: Any) -> Any:
    """Coerce a list field the model emitted as a string back into a list.

    Returns the value unchanged when it isn't a string, so a well-formed list passes
    through untouched. When recovery fails, the original value is returned so pydantic
    raises its normal validation error rather than this masking the problem.
    """
    if not isinstance(value, str):
        return value
    cleaned = _LEAKED_PARAM_TAG_RE.sub("", value).strip()
    if not cleaned:
        return []
    start = cleaned.find("[")
    end = cleaned.rfind("]")
    if start != -1 and end > start:
        try:
            return json.loads(cleaned[start : end + 1])
        except (ValueError, TypeError):
            pass
    return value


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

    @field_validator("hypotheses", "recommendations", mode="before")
    @classmethod
    def _recover_leaked_list(cls, value: Any) -> Any:
        return _recover_stringified_list(value)
