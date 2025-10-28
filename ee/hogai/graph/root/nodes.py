from typing import Optional, cast

from langchain_core.runnables import RunnableConfig
from langgraph.types import Send

from posthog.schema import AgentMode, AssistantMessage, ReasoningMessage

from ee.hogai.graph.agent.factory import AgentDefinition
from ee.hogai.graph.base import AssistantNode
from ee.hogai.tool import CONTEXTUAL_TOOL_NAME_TO_TOOL
from ee.hogai.utils.types import (
    AssistantNodeName,
    AssistantState,
    BaseState,
    BaseStateWithMessages,
    PartialAssistantState,
)
from ee.hogai.utils.types.composed import MaxNodeName

product_analytics_agent = AgentDefinition(AgentMode.PRODUCT_ANALYTICS, "Product Analytics Agent")

MODE_REGISTRY = {}


class RootNode(AssistantNode):
    async def arun(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState:
        pass

    async def get_reasoning_message(
        self, input: BaseState, default_message: Optional[str] = None
    ) -> ReasoningMessage | None:
        input = cast(AssistantState, input)
        if self.context_manager.has_awaitable_context(input):
            return ReasoningMessage(content="Calculating context")
        return None

    def router(self, state: AssistantState):
        last_message = state.messages[-1]
        if not isinstance(last_message, AssistantMessage) or not last_message.tool_calls:
            return AssistantNodeName.END
        return [
            Send(AssistantNodeName.ROOT_TOOLS, state.model_copy(update={"root_tool_call_id": tool_call.id}))
            for tool_call in last_message.tool_calls
        ]

    @property
    def node_name(self) -> MaxNodeName:
        return AssistantNodeName.ROOT


class RootNodeTools(AssistantNode):
    @property
    def node_name(self) -> MaxNodeName:
        return AssistantNodeName.ROOT_TOOLS

    async def get_reasoning_message(
        self, input: BaseState, default_message: Optional[str] = None
    ) -> ReasoningMessage | None:
        if not isinstance(input, BaseStateWithMessages):
            return None
        if not input.messages:
            return None

        assert isinstance(input.messages[-1], AssistantMessage)
        tool_calls = input.messages[-1].tool_calls or []
        if len(tool_calls) == 0:
            return None
        tool_call = tool_calls[0]
        content = None
        if tool_call.name == "create_and_query_insight":
            content = "Coming up with an insight"
        else:
            # This tool should be in CONTEXTUAL_TOOL_NAME_TO_TOOL, but it might not be in the rare case
            # when the tool has been removed from the backend since the user's frontend was loaded
            try:
                ToolClass = CONTEXTUAL_TOOL_NAME_TO_TOOL[tool_call.name]  # type: ignore
                tool = await ToolClass.create_tool_class(team=self._team, user=self._user)
                content = tool.thinking_message
            except KeyError:
                content = f"Running tool {tool_call.name}"

        return ReasoningMessage(content=content) if content else None

    async def arun(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState | None:
        pass
