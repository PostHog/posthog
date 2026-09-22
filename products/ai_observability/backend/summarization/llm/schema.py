"""
Pydantic schema for structured LLM summarization outputs.
"""

import re
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

_LINE_REF_RE = re.compile(r"L(\d+)", re.IGNORECASE)


def _keep_one_line_ref(value: str) -> str:
    """Reduce a line reference to the first `L45` in it, or to an empty string.

    The summary UI links each item to one source line, but models answer with ranges
    (`L28-L31`) and lists although the prompt asks for one reference. OpenAI strict structured
    outputs do not enforce a `pattern`, so the contract holds here, not in the schema the model
    sees.
    """
    match = _LINE_REF_RE.search(value)
    return f"L{match.group(1)}" if match else ""


LineRef = Annotated[str, AfterValidator(_keep_one_line_ref)]


class SummaryBullet(BaseModel):
    """A single bullet point in the summary."""

    model_config = ConfigDict(extra="forbid")

    text: str = Field(description="The bullet point text")
    line_refs: LineRef = Field(
        description="Single line reference like 'L45' pointing to the most relevant line for this bullet"
    )


class InterestingNote(BaseModel):
    """A single interesting note."""

    model_config = ConfigDict(extra="forbid")

    text: str = Field(description="The note text")
    line_refs: LineRef = Field(
        description="Single line reference like 'L45' pointing to the most relevant line, or empty string if no specific line"
    )


class SummarizationResponse(BaseModel):
    """Structured response from LLM summarization."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(
        description="A concise, descriptive title (no longer than 10 words) summarizing the main purpose or outcome of this trace/event"
    )
    flow_diagram: str = Field(
        description="ASCII/text-based flow diagram showing the main steps in an easy, human-readable way. Use arrows (↓, →), branches (├─→, └─→), and symbols (✓, ✗)."
    )
    summary_bullets: list[SummaryBullet] = Field(description="3-10 summary bullet points with line references")
    interesting_notes: list[InterestingNote] = Field(
        description="Interesting notes (detailed mode). Use empty array for minimal mode."
    )
