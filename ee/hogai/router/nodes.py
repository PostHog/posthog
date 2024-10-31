from functools import cached_property
from typing import Literal

from langchain_core.messages import AIMessage as LangchainAIMessage
from langchain_core.messages import BaseMessage, ToolCall
from langchain_core.messages import ToolMessage as LangchainToolMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import Tool
from langchain_openai import ChatOpenAI

from ee.hogai.router.prompts import (
    router_funnel_description_prompt,
    router_system_prompt,
    router_trends_description_prompt,
    router_user_prompt,
)
from ee.hogai.utils import AssistantNode, AssistantState
from posthog.schema import AssistantToolCall, HumanMessage, RouterMessage

RouteName = Literal["trends", "funnel"]


class RouterNode(AssistantNode):
    def run(self, state: AssistantState, config: RunnableConfig):
        model = self._model.bind_tools(self._tools.values(), tool_choice="required", parallel_tool_calls=False)
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", router_system_prompt),
            ],
            template_format="mustache",
        ) + self._reconstruct_conversation(state)
        chain = prompt | model
        message: LangchainAIMessage = chain.invoke({}, config)
        tool_call = message.tool_calls[0]
        return {
            "messages": [
                RouterMessage(
                    tool_call=AssistantToolCall.model_validate(
                        {
                            "name": tool_call["name"],
                            "args": tool_call["args"],
                            "id": tool_call["id"],
                        }
                    )
                )
            ]
        }

    def router(self, state: AssistantState) -> RouteName:
        last_message = state["messages"][-1]
        if isinstance(last_message, RouterMessage):
            tool_call = self._get_tool_call(last_message)
            msg: LangchainToolMessage = self._tools[tool_call["name"]].invoke(tool_call)
            return msg.content
        raise ValueError("Invalid route.")

    @cached_property
    def _tools(self) -> dict[str, Tool]:
        def generate_trends_insight() -> RouteName:
            return "trends"

        def generate_funnel_insight() -> RouteName:
            return "funnel"

        return {
            "generate_trends_insight": Tool(
                name="generate_trends_insight",
                description=router_trends_description_prompt,
                func=generate_trends_insight,
            ),
            "generate_funnel_insight": Tool(
                name="generate_funnel_insight",
                description=router_funnel_description_prompt,
                func=generate_funnel_insight,
            ),
        }

    def _get_tool_call(self, message: RouterMessage) -> ToolCall:
        return {
            "name": message.tool_call.name,
            "args": message.tool_call.args,
            "id": message.tool_call.id,
        }

    @property
    def _model(self):
        return ChatOpenAI(model="gpt-4o-mini", temperature=0, streaming=True)

    def _reconstruct_conversation(self, state: AssistantState):
        history: list[BaseMessage] = []
        for message in state["messages"]:
            if isinstance(message, HumanMessage):
                history += ChatPromptTemplate.from_messages([("user", router_user_prompt)]).format_messages(
                    question=message.content
                )
            elif isinstance(message, RouterMessage):
                tool_call = self._get_tool_call(message)
                history += [
                    # AIMessage with the tool call
                    LangchainAIMessage(content="", tool_calls=[tool_call]),
                    # ToolMessage with the tool call result
                    self._tools[tool_call["name"]].invoke(tool_call),
                ]
        return history
