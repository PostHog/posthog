from uuid import uuid4

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableConfig
from posthoganalytics import capture_exception

from posthog.schema import (
    DeepResearchNotebook,
    DeepResearchType,
    HumanMessage,
    NotebookUpdateMessage,
    ProsemirrorJSONContent,
)

from posthog.models.notebook.notebook import Notebook
from posthog.sync import database_sync_to_async

from ee.hogai.graph.deep_research.base.nodes import DeepResearchNode
from ee.hogai.graph.deep_research.notebook.prompts import DEEP_RESEARCH_NOTEBOOK_PLANNING_PROMPT
from ee.hogai.graph.deep_research.types import DeepResearchNodeName, DeepResearchState, PartialDeepResearchState
from ee.hogai.utils.types.composed import MaxNodeName


class DeepResearchNotebookPlanningNode(DeepResearchNode):
    @property
    def node_name(self) -> MaxNodeName:
        return DeepResearchNodeName.NOTEBOOK_PLANNING

    async def arun(self, state: DeepResearchState, config: RunnableConfig) -> PartialDeepResearchState:
        # Load template
        template_markdown = await self._retrieve_template_markdown(state)
        # We use instructions with the OpenAI Responses API
        instructions = DEEP_RESEARCH_NOTEBOOK_PLANNING_PROMPT.format(
            core_memory=await self._aget_core_memory(),
        )

        # Get last message if available, otherwise use empty string for template-only mode
        if not state.messages:
            raise IndexError("No messages in state")

        last_message = state.messages[-1]
        if not isinstance(last_message, HumanMessage):
            raise ValueError("Last message is not a human message.")

        human_content = last_message.content if last_message else ""
        # If a template was provided, emit a synthetic "loaded notebook" message once
        pre_messages: list = []
        if template_markdown and not state.has_emitted_template_loaded:
            serializer = self._get_notebook_serializer()
            json_content = serializer.from_markdown_to_json(template_markdown)
            loaded_message = NotebookUpdateMessage(
                id=str(uuid4()),
                notebook_id=str(state.template_notebook_short_id or ""),
                content=ProsemirrorJSONContent.model_validate(json_content.model_dump(exclude_none=True)),
                notebook_type="deep_research",
                event="loaded",
            )
            await self._write_message(loaded_message)
            pre_messages.append(loaded_message)

        # If template exists, use it (with or without additional human content)
        # If no template, use human content (which should exist in this case)
        if template_markdown:
            human_message = f"{template_markdown}\n\n{human_content}" if human_content else template_markdown
        else:
            human_message = human_content

        prompt = ChatPromptTemplate.from_messages(
            [
                ("human", human_message),
            ]
        )

        chain = prompt | self._get_model(instructions, state.previous_response_id)

        notebook = await self._astream_notebook(chain, config)
        notebook_update_message = self._generate_notebook_update_message(notebook)

        notebook_title = self.notebook.title if self.notebook and self.notebook.title else "Planning Notebook"
        notebook_info = DeepResearchNotebook(
            notebook_type=DeepResearchType.PLANNING,
            notebook_id=notebook.short_id,
            title=notebook_title,
        )

        current_run_notebooks = [notebook_info]
        all_conversation_notebooks = [*state.conversation_notebooks, notebook_info]
        notebook_update_message.notebook_type = "deep_research"
        notebook_update_message.conversation_notebooks = all_conversation_notebooks
        notebook_update_message.current_run_notebooks = current_run_notebooks

        return PartialDeepResearchState(
            messages=[*pre_messages, notebook_update_message],
            previous_response_id=None,  # we reset the previous response id because we're starting a new conversation after the onboarding
            conversation_notebooks=[notebook_info],
            current_run_notebooks=current_run_notebooks,
            has_emitted_template_loaded=True if pre_messages else state.has_emitted_template_loaded,
        )

    @database_sync_to_async
    def get_notebook(self, state: DeepResearchState) -> Notebook:
        return Notebook.objects.filter(
            team=self._team, short_id=str(state.template_notebook_short_id), deleted=False
        ).first()

    async def _retrieve_template_markdown(self, state: DeepResearchState) -> str | None:
        if not (
            state.template_notebook_short_id and not state.template_markdown and not state.has_emitted_template_loaded
        ):
            return state.template_markdown

        try:
            notebook = await self.get_notebook(state)

            if not notebook:
                return state.template_markdown

            text_content = getattr(notebook, "text_content", None)
            if text_content:
                return text_content

            content = getattr(notebook, "content", None)
            if content:
                try:
                    nb_json = ProsemirrorJSONContent.model_validate(notebook.content)
                    from ee.hogai.notebook.notebook_serializer import NotebookSerializer

                    return NotebookSerializer().from_json_to_markdown(nb_json)
                except Exception:
                    return state.template_markdown

            return state.template_markdown
        except Exception as e:
            capture_exception(e)
            return state.template_markdown
