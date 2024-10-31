from typing import Literal

from langchain_core.messages import AIMessage as LangchainAIMessage
from langchain_core.messages import BaseMessage, ToolCall
from langchain_core.messages import ToolMessage as LangchainToolMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableConfig
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from ee.hogai.router.prompts import (
    router_system_prompt,
    router_user_prompt,
)
from ee.hogai.utils import AssistantNode, AssistantState
from posthog.schema import HumanMessage, RouterMessage

RouteName = Literal["trends", "funnel"]


class RouterOutput(BaseModel):
    reasoning_steps: str = Field(..., description="The reasoning steps to arrive at the insight type.")
    insight_type: Literal["trends", "funnel"] = Field(..., description="The type of insight to generate.")


class RouterNode(AssistantNode):
    def run(self, state: AssistantState, config: RunnableConfig):
        model = self._model.with_structured_output(RouterOutput)
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", router_system_prompt),
            ],
            template_format="mustache",
        ) + self._reconstruct_conversation(state)
        chain = prompt | model
        output: RouterOutput = chain.invoke({}, config)

        return output

    def router(self, state: AssistantState) -> RouteName:
        last_message = state["messages"][-1]
        if isinstance(last_message, RouterMessage):
            tool_call = self._get_tool_call(last_message)
            msg: LangchainToolMessage = self._tools[tool_call["name"]].invoke(tool_call)
            return msg.content
        raise ValueError("Invalid route.")

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
