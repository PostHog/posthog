import json
import time
import asyncio
from typing import Any, cast
from uuid import uuid4

import structlog
from langchain_core.agents import AgentAction
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableConfig

from ee.hogai.traces_summaries.search_summaries_embeddings import EmbeddingSearcher
from posthog.schema import (
    AssistantToolCallMessage,
    MaxRecordingUniversalFilters,
    NotebookUpdateMessage,
    RecordingsQuery,
)

from posthog.models.team.team import check_is_feature_available_for_team
from posthog.session_recordings.models.session_recording_playlist import SessionRecordingPlaylist
from posthog.sync import database_sync_to_async
from posthog.temporal.ai.session_summary.summarize_session import execute_summarize_session
from posthog.temporal.ai.session_summary.summarize_session_group import (
    SessionSummaryStreamUpdate,
    execute_summarize_session_group,
)

from products.notebooks.backend.models import Notebook

from ee.hogai.graph.base import AssistantNode
from ee.hogai.graph.session_summaries.prompts import GENERATE_FILTER_QUERY_PROMPT
from ee.hogai.llm import MaxChatOpenAI
from ee.hogai.session_summaries.constants import (
    GROUP_SUMMARIES_MIN_SESSIONS,
    MAX_SESSIONS_TO_SUMMARIZE,
    SESSION_SUMMARIES_STREAMING_MODEL,
)
from ee.hogai.session_summaries.session_group.patterns import EnrichedSessionGroupSummaryPatternsList
from ee.hogai.session_summaries.session_group.summarize_session_group import find_sessions_timestamps
from ee.hogai.session_summaries.session_group.summary_notebooks import (
    SummaryNotebookIntermediateState,
    create_empty_notebook_for_summary,
    generate_notebook_content_from_summary,
    update_notebook_from_summary_content,
)
from ee.hogai.session_summaries.utils import logging_session_ids
from ee.hogai.utils.state import prepare_reasoning_progress_message
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
