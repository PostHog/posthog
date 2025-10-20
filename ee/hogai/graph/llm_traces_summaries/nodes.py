import json
import time
from typing import Any
from uuid import uuid4

from django.utils import timezone

import structlog
from langchain_core.runnables import RunnableConfig

from posthog.schema import AssistantToolCallMessage

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

    async def arun(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState | None:
        start_time = time.time()
        conversation_id = config.get("configurable", {}).get("thread_id", "unknown")
        llm_traces_summarization_query = state.llm_traces_summarization_query
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
            notebook = await create_empty_notebook_for_summary(
                user=self._user,
                team=self._team,
                summary_title=_create_notebook_title(query=llm_traces_summarization_query),
            )
            await update_notebook_from_summary_content(
                notebook=notebook, summary_content=notebook_content, session_ids=[]
            )
            # Return traces for Max to process
            # TODO: Return more structured data
            return PartialAssistantState(
                messages=[
                    AssistantToolCallMessage(
                        content=json.dumps(similar_documents),
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
    title = f'LLM traces summaries report - "{query}"'
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
                    create_text_content(summary["trace_id"]),
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


# async def create_notebook_from_summary_content(
#     user: User, team: Team, summary_content: TipTapNode, query: str
# ) -> Notebook:
#     """Create a notebook with session summary patterns."""
#     notebook = await Notebook.objects.acreate(
#         team=team,
#         title=_create_notebook_title(query=query),
#         content=summary_content,
#         created_by=user,
#         last_modified_by=user,
#     )
#     return notebook
