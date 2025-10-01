from typing import Optional
from uuid import uuid4

from langchain_core.messages import AIMessageChunk
from langchain_core.runnables import Runnable, RunnableConfig

from posthog.schema import NotebookUpdateMessage, ProsemirrorJSONContent

from posthog.models.notebook.notebook import Notebook

from ee.hogai.graph.base import BaseAssistantNode
from ee.hogai.graph.deep_research.types import DeepResearchState, PartialDeepResearchState
from ee.hogai.llm import MaxChatOpenAI
from ee.hogai.notebook.notebook_serializer import NotebookContext, NotebookSerializer
from ee.hogai.utils.helpers import extract_content_from_ai_message
from ee.hogai.utils.state import merge_message_chunk


class DeepResearchNode(BaseAssistantNode[DeepResearchState, PartialDeepResearchState]):
    REASONING_MODEL = "o3"
    REASONING_EFFORT = "medium"

    notebook: Notebook | None = None
    _notebook_serializer: NotebookSerializer | None = None

    def _get_model(self, instructions: str, previous_response_id: Optional[str] = None):
        return MaxChatOpenAI(
            model=self.REASONING_MODEL,
            streaming=True,
            use_responses_api=True,
            max_retries=3,
            user=self._user,
            team=self._team,
            model_kwargs={
                "instructions": instructions,
                "previous_response_id": previous_response_id,
            },
            reasoning={
                "effort": self.REASONING_EFFORT,
                "summary": "auto",
            },
        )

    async def _create_notebook(self) -> Notebook:
        notebook = await Notebook.objects.acreate(
            team=self._team,
            created_by=self._user,
            content={},
        )
        return notebook

    async def _astream_notebook(
        self,
        chain: Runnable,
        config: RunnableConfig,
        stream_parameters: Optional[dict] = None,
        context: Optional[NotebookContext] = None,
    ) -> Notebook:
        if self.notebook is None:
            self.notebook = await self._create_notebook()

        notebook_update_message = None
        chunk = AIMessageChunk(content="")

        async for new_chunk in chain.astream(
            stream_parameters or {},
            config,
        ):
            if not new_chunk.content:
                continue

            chunk = merge_message_chunk(chunk, new_chunk)
            notebook_update_message = await self._llm_chunk_to_notebook_update_message(chunk, context)
            await self._write_message(notebook_update_message)

        if not notebook_update_message:
            raise ValueError("No notebook update message found.")

        # Mark completion and emit a final update.
        notebook_update_message.id = str(uuid4())
        # writer(self._message_to_langgraph_update(notebook_update_message, node_name))
        await self._write_message(notebook_update_message)

        return self.notebook

    def _get_notebook_serializer(self, context: Optional[NotebookContext] = None) -> NotebookSerializer:
        """Get or create a reusable notebook serializer to avoid repeated query conversions during streaming."""
        if self._notebook_serializer is None or (context and self._notebook_serializer.context != context):
            self._notebook_serializer = NotebookSerializer(context=context)
        return self._notebook_serializer

    async def _llm_chunk_to_notebook_update_message(
        self, response: AIMessageChunk, context: Optional[NotebookContext] = None
    ) -> NotebookUpdateMessage:
        if not self.notebook:
            self.notebook = await self._create_notebook()

        content = extract_content_from_ai_message(response)

        serializer = self._get_notebook_serializer(context=context)
        title = None
        json_content = serializer.from_markdown_to_json(content)
        if json_content.content:
            try:
                next_heading = next(node for node in json_content.content if node.type == "heading")
                if next_heading:
                    title = next_heading.content[0].text if next_heading.content else None
            except StopIteration:
                title = None

        self.notebook.title = title or "Deep Research Plan"
        self.notebook.content = json_content.model_dump(exclude_none=True)
        await self.notebook.asave()
        return NotebookUpdateMessage(  # doesn't have an id because it's a partial update
            notebook_id=str(self.notebook.short_id),
            content=ProsemirrorJSONContent.model_validate(self.notebook.content),
        )

    def _generate_notebook_update_message(self, notebook: Notebook) -> NotebookUpdateMessage:
        return NotebookUpdateMessage(notebook_id=notebook.short_id, content=notebook.content)
