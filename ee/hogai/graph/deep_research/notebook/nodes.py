from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableConfig

from posthog.schema import HumanMessage

from ee.hogai.graph.deep_research.base.nodes import DeepResearchNode
from ee.hogai.graph.deep_research.notebook.prompts import DEEP_RESEARCH_NOTEBOOK_PLANNING_PROMPT
from ee.hogai.graph.deep_research.types import DeepResearchNodeName, DeepResearchState, PartialDeepResearchState


class DeepResearchNotebookPlanningNode(DeepResearchNode):
    async def arun(self, state: DeepResearchState, config: RunnableConfig) -> PartialDeepResearchState:
        # We use instructions with the OpenAI Responses API
        instructions = DEEP_RESEARCH_NOTEBOOK_PLANNING_PROMPT.format(
            core_memory=await self._aget_core_memory(),
        )

        last_message = state.messages[-1]
        if not isinstance(last_message, HumanMessage):
            raise ValueError("Last message is not a human message.")

        prompt = ChatPromptTemplate.from_messages(
            [
                ("human", last_message.content),
            ]
        )

        chain = prompt | self._get_model(instructions, state.previous_response_id)

        notebook_update_message = await self._astream_notebook(chain, config, DeepResearchNodeName.NOTEBOOK_PLANNING)

        return PartialDeepResearchState(
            messages=[notebook_update_message],
            previous_response_id=None,  # we reset the previous response id because we're starting a new conversation after the onboarding
            notebook_short_id=notebook_update_message.notebook_id,
        )
