import json
import time
from typing import Any
from uuid import uuid4

from django.utils import timezone

import structlog
from langchain_core.runnables import RunnableConfig

from posthog.schema import AssistantToolCallMessage, NotebookUpdateMessage

from products.notebooks.backend.util import (
    TipTapNode,
    create_heading_with_text,
    create_paragraph_with_content,
    create_text_content,
)

from ee.hogai.graph.base import AssistantNode
from ee.hogai.session_summaries.session_group.summary_notebooks import (
    create_empty_notebook_for_summary,
    update_notebook_from_summary_content,
)
from ee.hogai.traces_summaries.search_summaries_embeddings import EmbeddingSearcher
from ee.hogai.utils.types import AssistantState, PartialAssistantState
from ee.hogai.utils.types.base import AssistantNodeName
from ee.hogai.utils.types.composed import MaxNodeName


class LLMTracesSummarizationNode(AssistantNode):
    logger = structlog.get_logger(__name__)
    REASONING_MESSAGE = "Summarizing LLM traces"

    @property
    def node_name(self) -> MaxNodeName:
        return AssistantNodeName.LLM_TRACES_SUMMARIZATION

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    async def _stream_notebook_content(self, content: dict, state: AssistantState, partial: bool = True) -> None:
        """Stream TipTap content directly to a notebook if notebook_id is present in state."""
        # Check if we have a notebook_id in the state
        if not state.notebook_short_id:
            self.logger.exception("No notebook_short_id in state, skipping notebook update")
            return
        if partial:
            # Create a notebook update message; not providing id to count it as a partial message on FE
            notebook_message = NotebookUpdateMessage(notebook_id=state.notebook_short_id, content=content)
        else:
            # If not partial - means the final state of the notebook to show "Open the notebook" button in the UI
            notebook_message = NotebookUpdateMessage(
                notebook_id=state.notebook_short_id, content=content, id=str(uuid4())
            )
        # Stream the notebook update
        await self._write_message(notebook_message)

    async def arun(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState | None:
        start_time = time.time()
        conversation_id = config.get("configurable", {}).get("thread_id", "unknown")
        llm_traces_summarization_query = state.llm_traces_summarization_query
        notebook = await create_empty_notebook_for_summary(
            user=self._user,
            team=self._team,
            summary_title=_create_notebook_title(query=llm_traces_summarization_query),
        )
        state.notebook_short_id = notebook.short_id
        await self._stream_notebook_content(
            content=_prepare_initial_notebook_state(query=llm_traces_summarization_query), state=state
        )
        try:
            # Search for similar traces
            similar_documents = EmbeddingSearcher.prepare_input_data(
                question=llm_traces_summarization_query,
                top=5,
            )
            if not similar_documents:
                return self._create_error_response("No similar traces found", state)
            notebook_content = _prepare_basic_llm_summary_notebook_content(
                summaries=similar_documents, query=llm_traces_summarization_query
            )
            await self._stream_notebook_content(content=notebook_content, state=state)
            await update_notebook_from_summary_content(
                notebook=notebook, summary_content=notebook_content, session_ids=[]
            )
            # Return traces for Max to process
            # TODO: Return more structured data
            return PartialAssistantState(
                messages=[
                    AssistantToolCallMessage(
                        content=f"Here are 5 latest traces for the requested query (specify 'latest' explicitly in your response):\n\n{json.dumps(similar_documents)}",
                        tool_call_id=state.root_tool_call_id or "unknown",
                        id=str(uuid4()),
                    ),
                ],
                llm_traces_summarization_query=None,
                root_tool_call_id=None,
            )
        except Exception as err:
            self._log_failure("LLM traces summarization failed", conversation_id, start_time, err)
            return self._create_error_response(self._base_error_instructions, state)

    def _create_error_response(self, message: str, state: AssistantState) -> PartialAssistantState:
        return PartialAssistantState(
            messages=[
                AssistantToolCallMessage(
                    content=message,
                    tool_call_id=state.root_tool_call_id or "unknown",
                    id=str(uuid4()),
                ),
            ],
            llm_traces_summarization_query=None,
            root_tool_call_id=None,
        )

    def _log_failure(self, message: str, conversation_id: str, start_time: float, error: Any = None):
        self.logger.error(
            message,
            extra={
                "team_id": getattr(self._team, "id", "unknown"),
                "conversation_id": conversation_id,
                "execution_time_ms": round(time.time() - start_time, 2) * 1000,
                "error": str(error) if error else None,
            },
            exc_info=error if error else None,
        )

    @property
    def _base_error_instructions(self) -> str:
        return "INSTRUCTIONS: Tell the user that you encountered an issue while summarizing the LLM traces and suggest they try again with a different question."


def _create_notebook_title(query: str) -> str:
    title = f'LLM traces summaries report (last 5) - "{query}"'
    timestamp = timezone.now().strftime("%Y-%m-%d")
    title += f" ({timestamp})"
    return title


def _prepare_basic_llm_summary_notebook_content(summaries: list[dict[str, str]], query: str) -> TipTapNode:
    content = []
    # Title
    content.append(create_heading_with_text(_create_notebook_title(query=query), 1))
    # Add summaries
    content.append({"type": "horizontalRule"})
    for summary in summaries:
        content.append(
            create_paragraph_with_content(
                [
                    create_text_content("Trace ID: ", is_bold=True),
                    create_text_content(f"https://us.posthog.com/project/2/llm-analytics/traces/{summary["trace_id"]}"),
                    # create_text_content(summary["trace_id"]),
                ]
            )
        )
        content.append(
            create_paragraph_with_content(
                [
                    create_text_content("Trace summary: ", is_bold=True),
                    create_text_content(summary["trace_summary"]),
                ]
            )
        )
        content.append({"type": "horizontalRule"})
    return {
        "type": "doc",
        "content": content,
    }


def _prepare_initial_notebook_state(query: str):
    content = []
    # Title
    content.append(create_heading_with_text(_create_notebook_title(query=query), 1))
    # Initial content
    content.append(create_paragraph_with_content([create_text_content("📖 Reading through traces intensively...")]))
    return {"type": "doc", "content": content}
