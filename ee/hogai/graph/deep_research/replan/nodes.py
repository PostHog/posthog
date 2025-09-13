import logging
from typing import Literal, cast
from uuid import uuid4

from langchain_core.messages import AIMessage as LangchainAIMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableConfig

from posthog.schema import AssistantMessage, AssistantToolCall, HumanMessage

from ee.hogai.graph.deep_research.base.nodes import DeepResearchNode
from ee.hogai.graph.deep_research.replan.prompts import DEEP_RESEARCH_REPLANNER_PROMPT
from ee.hogai.graph.deep_research.types import DeepResearchState, PartialDeepResearchState
from ee.hogai.utils.helpers import extract_content_from_ai_message
from ee.hogai.utils.types import WithCommentary

logger = logging.getLogger(__name__)


class restart_research(WithCommentary):
    """
    Restart the research based on the user's feedback.
    """


class DeepResearchReplannerNode(DeepResearchNode):
    async def arun(self, state: DeepResearchState, config: RunnableConfig) -> PartialDeepResearchState:
        # We use instructions with the OpenAI Responses API
        instructions = DEEP_RESEARCH_REPLANNER_PROMPT.format(
            core_memory=await self._aget_core_memory(),
        )

        last_message = state.messages[-1]
        if not isinstance(last_message, HumanMessage):
            raise ValueError("Last message is not a human message.")

        prompt = ChatPromptTemplate.from_messages([("human", last_message.content)])
        model = self._get_model(instructions, state.previous_response_id).bind_tools(
            [restart_research],
        )

        chain = prompt | model
        response = await chain.ainvoke(
            {},
            config,
        )
        response = cast(LangchainAIMessage, response)

        content = extract_content_from_ai_message(response)
        response_id = response.response_metadata["id"]

        tool_calls = response.tool_calls
        if len(tool_calls) > 1:
            raise ValueError("Expected exactly one tool call.")
        if len(tool_calls) == 0:
            return PartialDeepResearchState(
                messages=[AssistantMessage(content=content, id=str(uuid4()))],
                previous_response_id=response_id,
            )
        commentary = tool_calls[0]["args"].get("commentary")
        _messages = [AssistantMessage(content=commentary, id=str(uuid4()))] if commentary else []

        return PartialDeepResearchState(
            messages=[
                *_messages,
                AssistantMessage(
                    content=content,
                    tool_calls=[
                        AssistantToolCall(id=cast(str, tool_call["id"]), name=tool_call["name"], args=tool_call["args"])
                        for tool_call in response.tool_calls
                    ],
                    id=str(uuid4()),
                ),
            ],
            planning_notebook_short_id=None,
            final_report_notebook_short_id=None,
            previous_response_id=response_id,
            intermediate_results=[],
            tasks=None,
            task_results=[],
            todos=None,
        )

    def router(self, state: DeepResearchState) -> Literal["end", "restart"]:
        last_message = state.messages[-1]
        if not isinstance(last_message, AssistantMessage):
            raise ValueError("Last message is not an assistant message.")
        tool_calls = last_message.tool_calls
        if not tool_calls:
            return "end"
        if len(tool_calls) > 1:
            raise ValueError("Expected exactly one tool call.")
        if tool_calls[0].name == "replan":
            return "restart"
        else:
            raise ValueError("Unexpected tool call.")
