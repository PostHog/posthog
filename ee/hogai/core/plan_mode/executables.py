"""
Shared executables for plan mode used by both chat agent and research agent.
"""

from abc import abstractmethod

from langchain_core.runnables import RunnableConfig

from posthog.schema import AgentMode, AssistantMessage, AssistantToolCall, AssistantToolCallMessage, HumanMessage

from ee.hogai.core.agent_modes.executables import AgentExecutable, AgentToolsExecutable
from ee.hogai.utils.types.base import AssistantState, PartialAssistantState


class PlanModeExecutable(AgentExecutable):
    """
    Base executable for plan mode agents.
    Sets supermode=PLAN when entering plan mode on first turn or new human message.
    """

    async def arun(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState:
        should_set_plan_mode = not state.supermode or (state.messages and isinstance(state.messages[-1], HumanMessage))

        if should_set_plan_mode:
            new_state = state.model_copy(update={"agent_mode": AgentMode.SQL, "supermode": AgentMode.PLAN})
        else:
            new_state = state

        result = await super().arun(new_state, config)

        # NOTE: Mode transitions (e.g., switch_mode("execution")) are handled in
        # PlanModeToolsExecutable.arun() AFTER the tool validates and executes.
        # This ensures the tool validates against the correct mode_registry.

        # Ensure supermode and agent_mode are persisted to the checkpoint on first turn
        if should_set_plan_mode:
            result = result.model_copy(update={"supermode": AgentMode.PLAN, "agent_mode": AgentMode.SQL})

        return result


class PlanModeToolsExecutable(AgentToolsExecutable):
    @property
    @abstractmethod
    def transition_prompt(self) -> str:
        """The prompt to display to the user when transitioning to the next mode."""
        ...

    @property
    @abstractmethod
    def transition_supermode(self) -> AgentMode | str | None:
        """The supermode value after transition completes.

        This should match the transition_supermode from the corresponding PlanModeExecutable.
        Used to detect when a transition happened in the previous root node.
        """
        ...

    def _get_current_tool_call(self, state: AssistantState) -> AssistantToolCall | None:
        """Get the current tool call being processed."""
        if not state.root_tool_call_id:
            return None

        for msg in reversed(state.messages):
            if isinstance(msg, AssistantMessage) and msg.tool_calls:
                for tc in msg.tool_calls:
                    if tc.id == state.root_tool_call_id:
                        return tc
        return None

    def _is_switch_mode_tool_call(self, state: AssistantState) -> bool:
        """Check if the current tool call is switch_mode."""
        tool_call = self._get_current_tool_call(state)
        return tool_call is not None and tool_call.name == "switch_mode"

    def _should_transition(self, state: AssistantState, result: PartialAssistantState) -> bool:
        """Check if we should transition based on the tool result.

        Override this in subclasses to define transition conditions.
        Default: transition when switch_mode tool is called and result.agent_mode
        matches the expected transition target.
        """
        return False  # Subclasses should override

    async def arun(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState:
        result = await super().arun(state, config)

        # Check if we should transition AFTER the tool successfully executed
        if self._is_switch_mode_tool_call(state) and self._should_transition(state, result):
            # Apply the supermode transition
            result = result.model_copy(
                update={
                    "agent_mode": AgentMode.PRODUCT_ANALYTICS,
                    "supermode": self.transition_supermode,
                }
            )

            # Replace the tool call message content with the transition prompt
            last_message = result.messages[-1] if result.messages else None
            if isinstance(last_message, AssistantToolCallMessage):
                updated_message = last_message.model_copy(update={"content": self.transition_prompt})
                result = result.model_copy(update={"messages": [*result.messages[:-1], updated_message]})

        return result
