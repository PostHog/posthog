from typing import Literal, cast

from langchain_core.messages import AIMessage as LangchainAIMessage, BaseMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableConfig
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from ee.hogai.router.prompts import (
    router_insight_description_prompt,
    router_system_prompt,
    router_user_prompt,
)
from ee.hogai.utils import AssistantNode, AssistantState
from posthog.schema import HumanMessage, RouterMessage

RouteName = Literal["trends", "funnel"]


class RouterOutput(BaseModel):
    visualization_type: Literal["trends", "funnel"] = Field(..., description=router_insight_description_prompt)


class RouterNode(AssistantNode):
    def run(self, state: AssistantState, config: RunnableConfig) -> AssistantState:
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", router_system_prompt),
            ],
            template_format="mustache",
        ) + self._reconstruct_conversation(state)
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

    def _reconstruct_conversation(self, state: AssistantState):
        history: list[BaseMessage] = []
        for message in state["messages"]:
            if isinstance(message, HumanMessage):
                history += ChatPromptTemplate.from_messages(
                    [("user", router_user_prompt.strip())], template_format="mustache"
                ).format_messages(question=message.content)
            elif isinstance(message, RouterMessage):
                history += [
                    # AIMessage with the tool call
                    LangchainAIMessage(content=message.content),
                ]
        return history
