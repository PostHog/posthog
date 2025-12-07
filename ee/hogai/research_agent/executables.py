from typing import Literal

from langchain_core.runnables import RunnableConfig

from posthog.schema import AgentMode, AssistantMessage, AssistantTool, AssistantToolCallMessage, HumanMessage

from ee.hogai.core.agent_modes.executables import AgentExecutable, AgentToolsExecutable
from ee.hogai.llm import MaxChatAnthropic
from ee.hogai.tool import MaxTool
from ee.hogai.utils.helpers import find_last_message_of_type
from ee.hogai.utils.types.base import AssistantState, PartialAssistantState

SWITCH_TO_RESEARCH_MODE_PROMPT = """
Successfully switched to research mode. Planning is over, you can now proceed with the actual research.
"""


class ResearchAgentExecutable(AgentExecutable):
    MAX_TOOL_CALLS = 1_000_000
    THINKING_CONFIG = {"type": "enabled", "budget_tokens": 4096}
    MAX_TOKENS = 16_384

    async def arun(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState:
        new_state = state.model_copy()
        if not new_state.research_mode or isinstance(new_state.messages[-1], HumanMessage):
            new_state.agent_mode = AgentMode.PRODUCT_ANALYTICS
            new_state.research_mode = AgentMode.PLAN
        return await super().arun(new_state, config)

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


class ResearchAgentToolsExecutable(AgentToolsExecutable):
    async def arun(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState:
        result = await super().arun(state, config)
        if result.agent_mode == AgentMode.RESEARCH:
            new_result = result.model_copy()
            new_result.agent_mode = AgentMode.PRODUCT_ANALYTICS
            new_result.research_mode = AgentMode.RESEARCH
            last_message = new_result.messages[-1].model_copy()
            if not isinstance(last_message, AssistantToolCallMessage):
                raise ValueError("Switch mode tool result must be an AssistantToolCallMessage")
            last_message.content = SWITCH_TO_RESEARCH_MODE_PROMPT
            new_result.messages[-1] = last_message
            return new_result
        return result

    def router(self, state: AssistantState) -> Literal["root", "end"]:
        last_message = state.messages[-1]
        if isinstance(last_message, AssistantToolCallMessage) and state.research_mode == AgentMode.RESEARCH:
            last_assistant_message = find_last_message_of_type(state.messages, AssistantMessage)
            if last_assistant_message and (tool_calls := last_assistant_message.tool_calls):
                create_notebook_tool_call = next(tc for tc in tool_calls if tc.name == AssistantTool.CREATE_NOTEBOOK)
                if create_notebook_tool_call and create_notebook_tool_call.args.get("content"):
                    # Agent has created a final non-draft notebook, we end the research
                    return "end"
        return "root"
