"""
Pydantic schema for structured evaluation summary outputs.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from ..constants import EVALUATION_SUMMARY_CHUNK_SIZE, EVALUATION_SUMMARY_MAX_RUNS


class EvaluationPattern(BaseModel):
    """A pattern identified across evaluation results."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(description="Short title for the pattern (3-5 words)")
    description: str = Field(description="Detailed description of the pattern")
    frequency: str = Field(description="How common this pattern is: 'common', 'occasional', or 'rare'")
    example_reasoning: str = Field(
        description="An example reasoning from the evaluated runs that demonstrates this pattern"
    )
    example_generation_ids: list[str] = Field(description="List of 1-5 generation IDs that exemplify this pattern")


class EvaluationSummaryStatistics(BaseModel):
    """Statistics about the analyzed evaluation runs."""

    model_config = ConfigDict(extra="forbid")

    total_analyzed: int = Field(description="Total number of evaluation runs analyzed")
    pass_count: int = Field(description="Number of passing evaluations")
    fail_count: int = Field(description="Number of failing evaluations")
    na_count: int = Field(description="Number of N/A (not applicable) evaluations")


class EvaluationSummaryResponse(BaseModel):
    """Structured response from AI-powered evaluation summarization."""

    model_config = ConfigDict(extra="forbid")

    overall_assessment: str
    pass_patterns: list[EvaluationPattern]
    fail_patterns: list[EvaluationPattern]
    na_patterns: list[EvaluationPattern]
    recommendations: list[str]
    statistics: EvaluationSummaryStatistics


class EvaluationPatternCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    result: Literal["pass", "fail", "na"] = Field(description="Result category for this candidate theme")
    title: str = Field(max_length=60, description="Short title for the candidate theme (3-5 words)")
    occurrence_count: int = Field(
        ge=1,
        le=EVALUATION_SUMMARY_MAX_RUNS,
        description="Exact number of evaluation runs represented by this theme",
    )
    example_reasoning: str = Field(
        max_length=240,
        description="Concise reasoning from one run that demonstrates this candidate theme",
    )
    example_generation_ids: list[Annotated[str, Field(max_length=64)]] = Field(
        min_length=1,
        max_length=3,
        description="List of 1-3 generation IDs that exemplify this theme",
    )


class EvaluationSummaryMapResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    patterns: list[EvaluationPatternCandidate] = Field(
        max_length=EVALUATION_SUMMARY_CHUNK_SIZE,
        description="Candidate themes representing evaluation runs",
    )
