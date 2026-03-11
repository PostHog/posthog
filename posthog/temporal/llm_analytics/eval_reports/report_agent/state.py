"""State definitions for the evaluation report agent."""

from typing import Annotated, TypedDict

from langgraph.graph.message import add_messages
from langgraph.managed import RemainingSteps

from posthog.temporal.llm_analytics.eval_reports.report_agent.schema import EvalReportMetadata, ReportSection


class EvalReportAgentState(TypedDict):
    """State for the evaluation report agent graph."""

    # LangGraph message history (required by create_react_agent)
    messages: Annotated[list, add_messages]
    remaining_steps: RemainingSteps

    # Input
    team_id: int
    evaluation_id: str
    evaluation_name: str
    evaluation_description: str
    evaluation_prompt: str
    evaluation_type: str
    period_start: str
    period_end: str
    previous_period_start: str

    # Working state
    report: dict[str, ReportSection | None]
    computed_metadata: EvalReportMetadata | None
