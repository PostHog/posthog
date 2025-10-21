from typing import Literal, cast

from langchain_core.messages import AIMessage as LangchainAIMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableConfig

from posthog.schema import HumanMessage

from ee.hogai.graph.deep_research.base.nodes import DeepResearchNode
from ee.hogai.graph.deep_research.onboarding.prompts import DEEP_RESEARCH_ONBOARDING_PROMPT
from ee.hogai.graph.deep_research.types import DeepResearchNodeName, DeepResearchState, PartialDeepResearchState
from ee.hogai.utils.helpers import normalize_ai_message
from ee.hogai.utils.types.composed import MaxNodeName


class DeepResearchOnboardingNode(DeepResearchNode):
    @property
    def node_name(self) -> MaxNodeName:
        return DeepResearchNodeName.NOTEBOOK_PLANNING

    def should_run_onboarding_at_start(self, state: DeepResearchState) -> Literal["onboarding", "planning", "continue"]:
        if not state.messages:
            return "onboarding"

        human_messages = [m for m in state.messages if isinstance(m, HumanMessage)]
        if len(human_messages) < 2:
            # This assumes that we keep the onboarding flow with the assistant asking a clarification question
            # So there will be 2 human messages during the onboarding flow
            return "onboarding"

        # If we have current_run_notebooks, we're continuing an existing run
        if state.current_run_notebooks:
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
        messages = normalize_ai_message(cast(LangchainAIMessage, response))
        response_id = response.response_metadata["id"]

        return PartialDeepResearchState(
            messages=messages,
            previous_response_id=response_id,
            current_run_notebooks=[],  # Reset current run notebooks on new run
        )
