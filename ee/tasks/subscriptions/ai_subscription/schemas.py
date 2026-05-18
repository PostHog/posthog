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
    steps: list[QueryPlanStep] = Field(..., min_length=1, max_length=5)


class EnrichedPromptSpec(BaseModel):
    """Everything the synthesis step needs to write the final markdown report."""

    cleaned_prompt: str
    context_blob: str
    plan: QueryPlan
