from posthog.schema import AgentMode

from ee.hogai.core.plan_mode import PlanModeExecutable, PlanModeToolsExecutable
from ee.hogai.llm import MaxChatAnthropic
from ee.hogai.tool import MaxTool
from ee.hogai.utils.types.base import AssistantState, PartialAssistantState

SWITCH_TO_RESEARCH_MODE_PROMPT = """
Successfully switched to research mode. Planning is over, you can now proceed with the actual research.

You MUST continue executing the plan until it is complete. Do not respond with text only - proceed with tool calls until you have completed the tasks.
"""


class ResearchAgentExecutable(PlanModeExecutable):
    """
    Executable for the research agent's plan mode.
    NOTE: Mode transitions are handled in ResearchAgentToolsExecutable after the tool executes.
    """

    MAX_TOOL_CALLS = 1_000_000
    THINKING_CONFIG = {"type": "enabled", "budget_tokens": 4096}
    MAX_TOKENS = 16_384

    def _get_model(self, state: AssistantState, tools: list["MaxTool"]):
        base_model = MaxChatAnthropic(
            model="claude-opus-4-5-20251101",
            streaming=True,
            stream_usage=True,
            user=self._user,
            team=self._team,
            betas=["interleaved-thinking-2025-05-14", "context-1m-2025-08-07"],
            max_tokens=self.MAX_TOKENS,
            thinking=self.THINKING_CONFIG,
            conversation_start_dt=state.start_dt,
            billable=True,
        )

        return base_model.bind_tools(tools, parallel_tool_calls=True)


class ResearchAgentToolsExecutable(PlanModeToolsExecutable):
    """
    Executable for handling tool calls in the research agent.
    Handles transitions from PLAN to RESEARCH mode after switch_mode tool executes.
    """

    @property
    def transition_supermode(self) -> AgentMode:
        return AgentMode.RESEARCH

    @property
    def transition_prompt(self) -> str:
        return SWITCH_TO_RESEARCH_MODE_PROMPT

    def _should_transition(self, state: AssistantState, result: PartialAssistantState) -> bool:
        # Transition when switch_mode tool switches to RESEARCH mode while in PLAN supermode
        return state.supermode == AgentMode.PLAN and result.agent_mode == AgentMode.RESEARCH
