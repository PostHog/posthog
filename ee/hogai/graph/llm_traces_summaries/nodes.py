import json
import time
from typing import Any
from uuid import uuid4

from django.utils import timezone

import structlog
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableConfig

from posthog.schema import AssistantToolCallMessage, DateRange, EmbeddingDistance, NotebookUpdateMessage

from posthog.sync import database_sync_to_async

from products.notebooks.backend.util import (
    TipTapNode,
    create_heading_with_text,
    create_paragraph_with_content,
    create_text_content,
)

from ee.hogai.graph.base import AssistantNode
from ee.hogai.graph.llm_traces_summaries.prompts import (
    ACCESS_SIMILAR_TRACES_RESULTS_PROMPT,
    EXTRACT_TOPICS_FROM_QUERY_PROMPT,
)
from ee.hogai.llm import MaxChatOpenAI
from ee.hogai.llm_traces_summaries.summarize_traces import LLMTracesSummarizer
from ee.hogai.session_summaries.session_group.summary_notebooks import (
    create_empty_notebook_for_summary,
    update_notebook_from_summary_content,
)
from ee.hogai.utils.types import AssistantState, PartialAssistantState
from ee.hogai.utils.types.base import AssistantNodeName
from ee.hogai.utils.types.composed import MaxNodeName
from ee.models.llm_traces_summaries import LLMTraceSummary

# Analyzing the last week by default, later could be guessed from the query
DEFAULT_LLM_TRACES_SUMMARIZATION_TOOL_DATE_RANGE = DateRange(date_from="-7d")
# Issue search is the main search, for now, later could be guessed from the query
DEFAULT_LLM_TRACES_SUMMARIZATION_TOOL_SUMMARY_TYPE = LLMTraceSummary.LLMTraceSummaryType.ISSUES_SEARCH
# Search for the top 10 similar traces by default, later could be guessed from the query
DEFAULT_LLM_TRACES_SUMMARIZATION_TOOL_TOP_SIMILAR_TRACES_COUNT = 10


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
        if not llm_traces_summarization_query:
            return self._create_error_response("No query provided", state)
        notebook = await create_empty_notebook_for_summary(
            user=self._user,
            team=self._team,
            summary_title=_create_notebook_title(
                query=llm_traces_summarization_query, top=DEFAULT_LLM_TRACES_SUMMARIZATION_TOOL_TOP_SIMILAR_TRACES_COUNT
            ),
        )
        state.notebook_short_id = notebook.short_id
        try:
            # Extract topics to search for in LLM traces
            extracted_topics_str = await self._extract_topics_from_query(
                plain_text_query=llm_traces_summarization_query, config=config
            )
            # Search for LLM traces with similar topics
            traces_summarizer = LLMTracesSummarizer(team=self._team)
            similar_traces = await database_sync_to_async(traces_summarizer.find_top_similar_traces_for_query)(
                query=extracted_topics_str,
                request_id=str(conversation_id),
                top=DEFAULT_LLM_TRACES_SUMMARIZATION_TOOL_TOP_SIMILAR_TRACES_COUNT,
                date_range=DEFAULT_LLM_TRACES_SUMMARIZATION_TOOL_DATE_RANGE,
                summary_type=DEFAULT_LLM_TRACES_SUMMARIZATION_TOOL_SUMMARY_TYPE,
            )
            # Format found traces into readable/printable documents, while remove excessive context
            similar_documents = self._format_similar_traces_into_documents(similar_traces=similar_traces)
            if not similar_documents:
                return self._create_error_response("No similar traces found", state)
            notebook_content = _prepare_basic_llm_summary_notebook_content(
                summaries=similar_documents,
                query=llm_traces_summarization_query,
                team_id=self._team.id,
                top=DEFAULT_LLM_TRACES_SUMMARIZATION_TOOL_TOP_SIMILAR_TRACES_COUNT,
            )
            await self._stream_notebook_content(content=notebook_content, state=state)
            await update_notebook_from_summary_content(
                notebook=notebook, summary_content=notebook_content, session_ids=[]
            )
            # Return traces for Max to process
            return PartialAssistantState(
                messages=[
                    AssistantToolCallMessage(
                        content=ACCESS_SIMILAR_TRACES_RESULTS_PROMPT.format(found_traces=json.dumps(similar_documents)),
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

    async def _extract_topics_from_query(self, plain_text_query: str, config: RunnableConfig) -> str:
        """Extract topics from the user's LLM traces summarization query"""
        messages = [
            ("human", EXTRACT_TOPICS_FROM_QUERY_PROMPT.format(input_query=plain_text_query)),
        ]
        prompt = ChatPromptTemplate.from_messages(messages)
        model = MaxChatOpenAI(model="gpt-4.1", temperature=0, disable_streaming=True, user=self._user, team=self._team)
        chain = prompt | model | StrOutputParser()
        extracted_topics = chain.invoke({}, config=config)
        # Validate the generated filter query is not empty or just whitespace
        if not extracted_topics or not extracted_topics.strip():
            raise ValueError(
                f"Topics extracted from LLM traces summarization query are empty or just whitespace (initial query: {plain_text_query})"
            )
        return extracted_topics

    def _format_similar_traces_into_documents(
        self, similar_traces: dict[str, tuple[EmbeddingDistance, LLMTraceSummary]]
    ) -> list[dict[str, str | float]]:
        documents = []
        for trace_id, (distance, summary) in similar_traces.items():
            # Types to keep mypy happy
            document: dict[str, str | float] = {
                "trace_id": str(trace_id),
                "trace_summary": str(summary.summary),
                # Providing cosine similarity score info to the LLM, so it can better assess the relevance of the trace
                "cosine_similarity": float(1 - distance.distance),
            }
            documents.append(document)
        return documents

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


def _create_notebook_title(query: str, top: int) -> str:
    title = f'LLM traces summaries report (top {top}) - "{query}"'
    timestamp = timezone.now().strftime("%Y-%m-%d")
    title += f" ({timestamp})"
    return title


def _prepare_basic_llm_summary_notebook_content(
    summaries: list[dict[str, str | float]], query: str, team_id: int, top: int
) -> TipTapNode:
    content = []
    # Title
    content.append(create_heading_with_text(_create_notebook_title(query=query, top=top), 1))
    # Add summaries
    content.append({"type": "horizontalRule"})
    for summary in summaries:
        content.append(
            create_paragraph_with_content(
                [
                    create_text_content("Trace ID: ", is_bold=True),
                    # TODO: Use local/prod linkts
                    create_text_content(
                        f"https://us.posthog.com/project/{team_id}/llm-analytics/traces/{summary["trace_id"]}"
                    ),
                ]
            )
        )
        content.append(
            create_paragraph_with_content(
                [
                    create_text_content("Trace summary: ", is_bold=True),
                    create_text_content(str(summary["trace_summary"])),
                ]
            )
        )
        content.append({"type": "horizontalRule"})
    return {
        "type": "doc",
        "content": content,
    }
