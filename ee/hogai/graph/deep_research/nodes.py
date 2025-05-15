from langchain_anthropic import ChatAnthropic
from ee.hogai.graph.base import AssistantNode
from ee.hogai.graph.deep_research.prompts import DEEP_RESEARCH_PLANNER_PROMPT
from ee.hogai.utils.types import AssistantState, PartialAssistantState
from langchain_core.runnables import RunnableConfig
from langchain_core.prompts import ChatPromptTemplate
from typing import Literal, cast
from uuid import uuid4

from langchain_core.messages import (
    AIMessage as LangchainAIMessage,
    BaseMessage,
    HumanMessage as LangchainHumanMessage,
    ToolMessage as LangchainToolMessage,
)
from pydantic import BaseModel, Field

from posthog.schema import (
    AssistantMessage,
    AssistantToolCall,
    AssistantToolCallMessage,
    FailureMessage,
    HumanMessage,
)


class PlanStep(BaseModel):
    type: Literal["product_analytics", "session_replay"]
    reasoning: str


class Plan(BaseModel):
    steps: list[PlanStep]


class plan_research(BaseModel):
    """
    Plan the best way to answer the user's question, using the tools available to you.
    """

    plan: Plan = Field(description="A step-by-step plan for answering the user's question")


class ask_user(BaseModel):
    """
    Ask the user for more information to help you plan the best way to answer the user's question.
    """

    question: str = Field(description="The question you are asking the user for more information about")


class DeepResearchPlannerNode(AssistantNode):
    def run(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState:
        history = self._construct_messages(state)

        prompt = (
            ChatPromptTemplate.from_messages(
                [
                    ("system", DEEP_RESEARCH_PLANNER_PROMPT),
                ],
                template_format="mustache",
            )
            + history
        )

        chain = prompt | self._get_model(state, config)

        message = chain.invoke(
            {
                "core_memory": self.core_memory_text,
            },
            config,
        )
        message = cast(LangchainAIMessage, message)

        return PartialAssistantState(
            messages=[
                AssistantMessage(
                    content=str(message.content),
                    tool_calls=[
                        AssistantToolCall(id=tool_call["id"], name=tool_call["name"], args=tool_call["args"])
                        for tool_call in message.tool_calls
                    ],
                    id=str(uuid4()),
                ),
            ],
        )

    def _get_model(self, state: AssistantState, config: RunnableConfig):
        # Research suggests temperature is not _massively_ correlated with creativity, hence even in this very
        # conversational context we're using a temperature of 0, for near determinism (https://arxiv.org/html/2405.00492v1)
        base_model = ChatAnthropic(model="claude-3-5-sonnet-latest", temperature=0.0, streaming=True, stream_usage=True)

        available_tools: list[type[BaseModel]] = [plan_research, ask_user]
        return base_model.bind_tools(available_tools, parallel_tool_calls=False)

    def _construct_messages(self, state: AssistantState) -> list[BaseMessage]:
        # `assistant` messages must be contiguous with the respective `tool` messages.
        tool_result_messages = {
            message.tool_call_id: message for message in state.messages if isinstance(message, AssistantToolCallMessage)
        }

        history: list[BaseMessage] = []
        for message in state.messages:
            if isinstance(message, HumanMessage):
                history.append(LangchainHumanMessage(content=message.content, id=message.id))
            elif isinstance(message, AssistantMessage):
                # Filter out tool calls without a tool response, so the completion doesn't fail.
                tool_calls = [
                    tool for tool in (message.model_dump()["tool_calls"] or []) if tool["id"] in tool_result_messages
                ]

                history.append(LangchainAIMessage(content=message.content, tool_calls=tool_calls, id=message.id))

                # Append associated tool call messages.
                for tool_call in tool_calls:
                    tool_call_id = tool_call["id"]
                    result_message = tool_result_messages[tool_call_id]
                    history.append(
                        LangchainToolMessage(
                            content=result_message.content, tool_call_id=tool_call_id, id=result_message.id
                        )
                    )
            elif isinstance(message, FailureMessage):
                history.append(
                    LangchainAIMessage(content=message.content or "An unknown failure occurred.", id=message.id)
                )

        return history


class DeepResearchPlannerToolsNode(AssistantNode):
    def run(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState:
        last_message = state.messages[-1]
        if not isinstance(last_message, AssistantMessage) or not last_message.tool_calls:
            raise ValueError("No tool calls found.")

        tools_calls = last_message.tool_calls
        if len(tools_calls) != 1:
            raise ValueError("Expected exactly one tool call.")

        tool_call = tools_calls[0]
        if tool_call.name == "plan_research":
            return PartialAssistantState(
                messages=[
                    AssistantToolCallMessage(
                        content=str(tool_call.args["plan"]),
                        id=str(uuid4()),
                        tool_call_id=tool_call.id,
                    )
                ],
                deep_research_plan=str(tool_call.args["plan"]),
            )
        elif tool_call.name == "ask_user":
            return PartialAssistantState(
                messages=[
                    AssistantToolCallMessage(
                        content="done",
                        id=str(uuid4()),
                        tool_call_id=tool_call.id,
                    ),
                    AssistantMessage(
                        content=tool_call.args["question"],
                        id=str(uuid4()),
                    ),
                ]
            )
        else:
            raise ValueError(f"Unknown tool called: {tool_call.name}")

    def router(self, state: AssistantState) -> Literal["continue", "end"]:
        last_message = state.messages[-1]
        if isinstance(last_message, AssistantMessage):
            return "end"
        elif isinstance(last_message, AssistantToolCallMessage):
            return "continue"
        else:
            raise ValueError(f"Unknown message type: {type(last_message)}")
