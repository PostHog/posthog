from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableConfig

from posthog.schema import DeepResearchNotebook, DeepResearchType, HumanMessage

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

        notebook = await self._astream_notebook(chain, config, DeepResearchNodeName.NOTEBOOK_PLANNING)
        notebook_update_message = self._generate_notebook_update_message(notebook)

        notebook_title = self.notebook.title if self.notebook else "Planning Notebook"
        notebook_info = DeepResearchNotebook(
            notebook_type=DeepResearchType.PLANNING,
            notebook_id=notebook.short_id,
            title=notebook_title,
        )

        # Determine if this is a new research run
        # A new run is when current_run_notebooks is None or empty
        is_new_run = not state.current_run_notebooks
        current_run_notebooks = [notebook_info] if is_new_run else [*state.current_run_notebooks, notebook_info]

        # Update the notebook message with type and all conversation notebooks
        all_conversation_notebooks = [*state.conversation_notebooks, notebook_info]
        notebook_update_message.notebook_type = "deep_research"
        notebook_update_message.conversation_notebooks = all_conversation_notebooks
        notebook_update_message.current_run_notebook_ids = [nb.notebook_id for nb in current_run_notebooks]

        return PartialDeepResearchState(
            messages=[notebook_update_message],
            previous_response_id=None,  # we reset the previous response id because we're starting a new conversation after the onboarding
            conversation_notebooks=[notebook_info],  # Add to persistent list
            current_run_notebooks=current_run_notebooks,  # Track current run notebooks
        )
