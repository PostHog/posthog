from typing import Literal, cast
from uuid import uuid4

from langchain_core.messages import AIMessage as LangchainAIMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableConfig

from posthog.schema import AssistantMessage, HumanMessage

from ee.hogai.graph.deep_research.base.nodes import DeepResearchNode
from ee.hogai.graph.deep_research.onboarding.prompts import DEEP_RESEARCH_ONBOARDING_PROMPT
from ee.hogai.graph.deep_research.types import DeepResearchState, PartialDeepResearchState
from ee.hogai.utils.helpers import extract_content_from_ai_message


class DeepResearchOnboardingNode(DeepResearchNode):
    def should_run_onboarding_at_start(self, state: DeepResearchState) -> Literal["onboarding", "planning", "continue"]:
        if not state.messages:
            return "onboarding"

        human_messages = [m for m in state.messages if isinstance(m, HumanMessage)]
        if len(human_messages) < 2:
            # This assumes that we keep the onboarding flow with the assistant asking a clarification question
            # So there will be 2 human messages during the onboarding flow
            return "onboarding"

        if state.notebook_short_id:
            return "continue"
        return "planning"

    async def arun(self, state: DeepResearchState, config: RunnableConfig) -> PartialDeepResearchState:
        # We use instructions with the OpenAI Responses API
        instructions = DEEP_RESEARCH_ONBOARDING_PROMPT.format(
            core_memory=await self._aget_core_memory(),
        )

        if len(state.messages) == 0:
            raise ValueError("No messages found in the state.")

        last_message = state.messages[-1]
        if not isinstance(last_message, HumanMessage):
            raise ValueError("Last message is not a human message.")

        # Initial message or follow-up to the planner's questions
        prompt = ChatPromptTemplate.from_messages(
            [
                ("human", last_message.content),
            ]
        )

        chain = prompt | self._get_model(instructions, state.previous_response_id)

        response = await chain.ainvoke(
            {},
            config,
        )
        response = cast(LangchainAIMessage, response)
        response_id = response.response_metadata["id"]

        content = extract_content_from_ai_message(response)

        return PartialDeepResearchState(
            messages=[AssistantMessage(content=content, id=str(uuid4()))],
            previous_response_id=response_id,
        )
