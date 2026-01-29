"""
Shared executables for plan mode used by both chat agent and research agent.
"""

from abc import abstractmethod

from langchain_core.runnables import RunnableConfig

from posthog.schema import AgentMode, AssistantToolCallMessage, HumanMessage

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
            new_state = state.model_copy(
                update={"agent_mode": AgentMode.PRODUCT_ANALYTICS, "supermode": AgentMode.PLAN}
            )
        else:
            new_state = state

        result = await super().arun(new_state, config)

        # Ensure supermode and agent_mode are persisted to the checkpoint
        if should_set_plan_mode:
            result = result.model_copy(update={"supermode": AgentMode.PLAN, "agent_mode": AgentMode.PRODUCT_ANALYTICS})

        return result


class PlanModeToolsExecutable(AgentToolsExecutable):
    """
    Base executable for handling tool calls in plan mode.
    Subclasses must implement the mode transition logic.
    """

    @property
    @abstractmethod
    def transition_supermode(self) -> AgentMode | str | None:
        """The supermode to transition to after plan mode completes.

        Returns one of three values to express distinct intents:
        - AgentMode: Set supermode to this mode (e.g., AgentMode.RESEARCH)
        - CLEAR_SUPERMODE: Explicitly clear supermode to None (exit plan mode entirely)
        - None: Leave supermode unchanged (keep current value)

        Note: CLEAR_SUPERMODE is a string sentinel because None already means "no change"
        in the reducer pattern in LangGraph, so we need a distinct value to express "set to None".
        """
        ...

    @property
    @abstractmethod
    def transition_prompt(self) -> str:
        """The prompt to show when transitioning to the next mode."""
        ...

    @abstractmethod
    def _should_transition(self, state: AssistantState, result: PartialAssistantState) -> bool:
        """Check if we should transition to the next mode based on the tool result."""
        ...

    async def arun(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState:
        result = await super().arun(state, config)

        if self._should_transition(state, result):
            new_result = result.model_copy()
            new_result.agent_mode = AgentMode.PRODUCT_ANALYTICS
            new_result.supermode = self.transition_supermode
            last_message = new_result.messages[-1].model_copy()
            if not isinstance(last_message, AssistantToolCallMessage):
                raise ValueError("Switch mode tool result must be an AssistantToolCallMessage")
            last_message.content = self.transition_prompt
            new_result.messages[-1] = last_message
            return new_result

        return result
