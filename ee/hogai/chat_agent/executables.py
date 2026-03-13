import asyncio

from langchain_core.runnables import RunnableConfig

from posthog.schema import AgentMode

from ee.hogai.chat_agent.toolkit import DEFAULT_TOOLS
from ee.hogai.core.agent_modes.executables import AgentExecutable, AgentToolsExecutable
from ee.hogai.core.plan_mode import PlanModeExecutable, PlanModeToolsExecutable
from ee.hogai.tools.switch_mode import _get_default_tools_prompt, _get_modes_prompt
from ee.hogai.utils.prompt import format_prompt_string
from ee.hogai.utils.types.base import CLEAR_SUPERMODE, AssistantState, PartialAssistantState

SWITCH_TO_EXECUTION_MODE_PROMPT = """
Planning complete. Switched to execution mode, which defaults to product analytics mode.

Available tools and modes:
## Common tools
{{{default_tools}}}

## Specialized modes
{{{available_modes}}}

You MUST continue executing the plan until it is complete. Do not respond with text only - proceed with tool calls until you have completed the tasks.
"""

SWITCH_TO_PLAN_MODE_PROMPT = """
You have successfully switched to plan mode to help structure your task.
"""


class ChatAgentExecutable(AgentExecutable):
    """
    Executable for the chat agent's non-plan mode (regular execution mode).
    """

    pass


class ChatAgentToolsExecutable(AgentToolsExecutable):
    """
    Executable for handling tool calls in the chat agent's non-plan mode.
    Handles transitions TO plan mode after switch_mode tool successfully executes.
    """

    async def arun(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState:
        result = await super().arun(state, config)

        # Check if we just switched to plan mode (result.agent_mode == PLAN after tool execution)
        # Only transition if we're not already in plan mode
        if state.supermode is None and result.agent_mode == AgentMode.PLAN:
            from posthog.schema import AssistantToolCallMessage

            # Set supermode to PLAN and default mode to SQL
            result = result.model_copy(
                update={
                    "agent_mode": AgentMode.SQL,  # Default mode inside plan mode
                    "supermode": AgentMode.PLAN,
                }
            )

            # Replace the tool call message content with the transition prompt
            last_message = result.messages[-1] if result.messages else None
            if isinstance(last_message, AssistantToolCallMessage):
                updated_message = last_message.model_copy(update={"content": SWITCH_TO_PLAN_MODE_PROMPT})
                result = result.model_copy(update={"messages": [*result.messages[:-1], updated_message]})

        return result


class ChatAgentPlanExecutable(PlanModeExecutable):
    """
    Executable for the chat agent's plan mode.
    Inherits from PlanModeExecutable which sets supermode=PLAN on first turn or new human message.
    """

    @property
    def transition_supermode(self) -> str:
        # Chat agent exits plan mode entirely (supermode becomes None via CLEAR_SUPERMODE)
        return CLEAR_SUPERMODE


class ChatAgentPlanToolsExecutable(PlanModeToolsExecutable):
    """
    Executable for handling tool calls in the chat agent's plan mode.
    Handles transitions to execution mode after switch_mode tool successfully executes.
    """

    @property
    def transition_supermode(self) -> str:
        # Chat agent exits plan mode entirely (supermode becomes None via CLEAR_SUPERMODE)
        return CLEAR_SUPERMODE

    async def get_transition_prompt(self) -> str:
        from ee.hogai.chat_agent.mode_manager import get_execution_mode_registry  # circular import

        execution_registry = get_execution_mode_registry(self._team, self._user)

        default_tools, available_modes = await asyncio.gather(
            _get_default_tools_prompt(
                team=self._team,
                user=self._user,
                default_tool_classes=DEFAULT_TOOLS,
            ),
            _get_modes_prompt(
                team=self._team,
                user=self._user,
                context_manager=self.context_manager,
                mode_registry=execution_registry,
            ),
        )

        return format_prompt_string(
            SWITCH_TO_EXECUTION_MODE_PROMPT,
            default_tools=default_tools,
            available_modes=available_modes,
        )

    def _should_transition(self, state: AssistantState, result: PartialAssistantState) -> bool:
        # Transition when switching from plan mode to execution mode
        # The tool has already validated and set result.agent_mode = EXECUTION
        return state.supermode == AgentMode.PLAN and result.agent_mode == AgentMode.EXECUTION
