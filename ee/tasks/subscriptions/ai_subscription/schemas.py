from typing import Literal

from pydantic import BaseModel, Field


class QueryPlanStep(BaseModel):
    """One step in a query plan — a single HogQL query to run.

    MVP supports only HogQL; typed Trends/Funnels/Retention queries are a follow-up.
    """

    description: str = Field(..., description="One-sentence rationale for running this query.")
    query_type: Literal["hogql"] = Field("hogql", description="MVP: always 'hogql'.")
    hogql: str = Field(..., description="A HogQL SELECT statement scoped to the team's events.")
    time_window_days: int = Field(7, ge=1, le=365)


class QueryPlan(BaseModel):
    """A short, bounded plan of queries that answer the user's prompt."""

    overall_intent: str = Field(..., description="Plain-English summary of what the report will tell the user.")
    # Cap at 3 (was 5). Each step adds up to ~4 min wall-clock under worst-case
    # retries, and 3 well-chosen queries cover almost any report. Bumping back up
    # is a one-line change if real prompts turn out to need more headroom.
    steps: list[QueryPlanStep] = Field(..., min_length=1, max_length=3)


class EnrichedPromptSpec(BaseModel):
    """Everything the synthesis step needs to write the final markdown report."""

    cleaned_prompt: str
    context_blob: str
    plan: QueryPlan


class HogQLFix(BaseModel):
    """LLM response when asked to rewrite a HogQL query that failed to parse/execute."""

    fixed_hogql: str = Field(
        ...,
        description="A single, flat HogQL SELECT statement that addresses the original step intent.",
    )
