from typing import Literal, cast

from langchain_core.messages import AIMessage as LangchainAIMessage, BaseMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableConfig
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from ee.hogai.router.prompts import (
    ROUTER_INSIGHT_DESCRIPTION_PROMPT,
    ROUTER_SYSTEM_PROMPT,
    ROUTER_USER_PROMPT,
)
from ee.hogai.utils import AssistantState, AssistantNode
from posthog.schema import HumanMessage, RouterMessage

RouteName = Literal["trends", "funnel"]


class RouterOutput(BaseModel):
    visualization_type: Literal["trends", "funnel"] = Field(..., description=ROUTER_INSIGHT_DESCRIPTION_PROMPT)


class RouterNode(AssistantNode):
    def run(self, state: AssistantState, config: RunnableConfig) -> AssistantState:
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", ROUTER_SYSTEM_PROMPT),
            ],
            template_format="mustache",
        ) + self._construct_messages(state)
        chain = prompt | self._model
        output: RouterOutput = chain.invoke({}, config)
        return {"messages": [RouterMessage(content=output.visualization_type)]}

    def router(self, state: AssistantState) -> RouteName:
        last_message = state["messages"][-1]
        if isinstance(last_message, RouterMessage):
            return cast(RouteName, last_message.content)
        raise ValueError("Invalid route.")

    @property
    def _model(self):
        return ChatOpenAI(model="gpt-4o-mini", temperature=0, disable_streaming=True).with_structured_output(
            RouterOutput
        )

    def _construct_messages(self, state: AssistantState):
        history: list[BaseMessage] = []
        for message in state["messages"]:
            if isinstance(message, HumanMessage):
                history += ChatPromptTemplate.from_messages(
                    [("user", ROUTER_USER_PROMPT.strip())], template_format="mustache"
                ).format_messages(question=message.content)
            elif isinstance(message, RouterMessage):
                history += [
                    # AIMessage with the tool call
                    LangchainAIMessage(content=message.content),
                ]
        return history
