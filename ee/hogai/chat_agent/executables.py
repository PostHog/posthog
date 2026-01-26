from posthog.schema import AgentMode

from ee.hogai.core.plan_mode import PlanModeExecutable, PlanModeToolsExecutable
from ee.hogai.utils.types.base import CLEAR_SUPERMODE, AssistantState, PartialAssistantState

SWITCH_TO_EXECUTION_MODE_PROMPT = """
Planning complete. Executing the plan now.

You MUST continue executing the plan until it is complete. Do not respond with text only - proceed with tool calls until you have completed the tasks.
"""


class ChatAgentPlanExecutable(PlanModeExecutable):
    """
    Executable for the chat agent's plan mode.
    Inherits from PlanModeExecutable which sets supermode=PLAN on first turn or new human message.
    """

    pass


class ChatAgentPlanToolsExecutable(PlanModeToolsExecutable):
    """
    Executable for handling tool calls in the chat agent's plan mode.
    Transitions to execution mode and clears supermode using CLEAR_SUPERMODE sentinel.
    """

    @property
    def transition_supermode(self) -> str:
        # Chat agent exits plan mode entirely (supermode becomes None via CLEAR_SUPERMODE)
        return CLEAR_SUPERMODE

    @property
    def transition_prompt(self) -> str:
        return SWITCH_TO_EXECUTION_MODE_PROMPT

    def _should_transition(self, state: AssistantState, result: PartialAssistantState) -> bool:
        # Transition when switching from plan mode to execution mode
        return state.supermode == AgentMode.PLAN and result.agent_mode == AgentMode.EXECUTION
