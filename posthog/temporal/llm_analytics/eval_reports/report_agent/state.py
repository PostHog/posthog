"""State definitions for the evaluation report agent."""

from typing import Annotated, TypedDict

from langgraph.graph.message import add_messages
from langgraph.managed import RemainingSteps

from posthog.temporal.llm_analytics.eval_reports.report_agent.schema import EvalReportContent


class EvalReportAgentState(TypedDict):
    """State for the evaluation report agent graph.

    The agent mutates `report` via `set_title`, `add_section`, and `add_citation`
    tool calls. After the agent finishes, the graph computes `report.metrics`
    mechanically and overwrites the placeholder — the agent's own output for
    metrics (if any) is discarded to guarantee grounded numbers.
    """

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
    report_prompt_guidance: str

    # Working state — the agent builds this up via tool calls
    report: EvalReportContent
