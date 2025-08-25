import time
import asyncio
from typing import Any, cast
from uuid import uuid4

import structlog
from langchain_core.runnables import RunnableConfig
from langgraph.config import get_stream_writer
from langgraph.types import StreamWriter

from posthog.schema import (
    AssistantToolCallMessage,
    MaxRecordingUniversalFilters,
    NotebookUpdateMessage,
    RecordingsQuery,
)

from posthog.models.notebook.notebook import Notebook
from posthog.sync import database_sync_to_async
from posthog.temporal.ai.session_summary.summarize_session import execute_summarize_session
from posthog.temporal.ai.session_summary.summarize_session_group import (
    SessionSummaryStreamUpdate,
    execute_summarize_session_group,
)

from ee.hogai.graph.base import AssistantNode
from ee.hogai.session_summaries.constants import GROUP_SUMMARIES_MIN_SESSIONS, SESSION_SUMMARIES_STREAMING_MODEL
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
from ee.hogai.utils.types import AssistantNodeName, AssistantState, PartialAssistantState


class SessionSummarizationNode(AssistantNode):
    logger = structlog.get_logger(__name__)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._intermediate_state = None

    def _get_stream_writer(self) -> StreamWriter | None:
        """Get the stream writer for custom events"""
        try:
            return get_stream_writer()
        except Exception as err:
            self.logger.warning(
                "Failed to get stream writer for session summarization",
                extra={"node": "SessionSummarizationNode", "error": str(err)},
            )
            # Fallback if stream writer is not available
            return None

    def _stream_progress(self, progress_message: str, writer: StreamWriter | None) -> None:
        """Push summarization progress as reasoning messages"""
        if not writer:
            self.logger.warning(
                "Stream writer is not available, cannot stream progress",
                extra={"node": "SessionSummarizationNode", "message": progress_message},
            )
            return
        message_chunk = prepare_reasoning_progress_message(progress_message)
        message = (message_chunk, {"langgraph_node": AssistantNodeName.SESSION_SUMMARIZATION})
        writer(("session_summarization_node", "messages", message))
        return

    def _stream_notebook_content(
        self, content: dict, state: AssistantState, writer: StreamWriter | None, partial: bool = True
    ) -> None:
        """Stream TipTap content directly to a notebook if notebook_id is present in state."""
        if not writer:
            self.logger.exception("Stream writer not available for notebook update")
            return
        # Check if we have a notebook_id in the state
        if not state.notebook_id:
            self.logger.exception("No notebook_id in state, skipping notebook update")
            return
        if partial:
            # Create a notebook update message; not providing id to count it as a partial message on FE
            notebook_message = NotebookUpdateMessage(notebook_id=state.notebook_id, content=content)
        else:
            # If not partial - means the final state of the notebook to show "Open the notebook" button in the UI
            notebook_message = NotebookUpdateMessage(notebook_id=state.notebook_id, content=content, id=str(uuid4()))
        # Stream the notebook update
        message = (notebook_message, {"langgraph_node": AssistantNodeName.SESSION_SUMMARIZATION})
        writer(("session_summarization_node", "messages", message))

    async def _generate_replay_filters(self, plain_text_query: str) -> MaxRecordingUniversalFilters | None:
        """Generates replay filters to get session ids by querying a compiled Universal filters graph."""
        from products.replay.backend.max_tools import SessionReplayFilterOptionsGraph

        graph = SessionReplayFilterOptionsGraph(self._team, self._user).compile_full_graph()
        # Call with your query
        result = await graph.ainvoke(
            {
                "change": plain_text_query,
                "current_filters": {},  # Empty state, as we need results from the query-to-filter
            }
        )
        if not result or not isinstance(result, dict) or not result.get("output"):
            self.logger.error(
                f"Invalid result from filter options graph: {result}",
                extra={
                    "team_id": getattr(self._team, "id", "unknown"),
                    "user_id": getattr(self._user, "id", "unknown"),
                    "result": result,
                },
            )
            return None
        # Extract the generated filters
        filters_data = result["output"]
        if not filters_data:
            return None
        max_filters = cast(MaxRecordingUniversalFilters, filters_data)
        return max_filters

    def _get_session_ids_with_filters(self, replay_filters: MaxRecordingUniversalFilters) -> list[str] | None:
        from posthog.session_recordings.queries.session_recording_list_from_query import SessionRecordingListFromQuery

        # Convert Max filters into recordings query format
        properties = []
        if replay_filters.filter_group and replay_filters.filter_group.values:
            for inner_group in replay_filters.filter_group.values:
                if hasattr(inner_group, "values"):
                    properties.extend(inner_group.values)
        recordings_query = RecordingsQuery(
            date_from=replay_filters.date_from,
            date_to=replay_filters.date_to,
            properties=properties,
            filter_test_accounts=replay_filters.filter_test_accounts,
            order=replay_filters.order,
            # Handle duration filters
            having_predicates=(
                [
                    {"key": "duration", "type": "recording", "operator": dur.operator, "value": dur.value}
                    for dur in (replay_filters.duration or [])
                ]
                if replay_filters.duration
                else None
            ),
        )
        # Execute the query to get session IDs
        query_runner = SessionRecordingListFromQuery(
            team=self._team, query=recordings_query, hogql_query_modifiers=None
        )
        results = query_runner.run()
        # Extract session IDs
        session_ids = [recording["session_id"] for recording in results.results]
        return session_ids if session_ids else None

    async def _summarize_sessions_individually(self, session_ids: list[str], writer: StreamWriter | None) -> str:
        """Summarize sessions individually with progress updates."""
        total = len(session_ids)
        completed = 0

        async def _summarize(session_id: str) -> str:
            nonlocal completed
            result = await execute_summarize_session(
                session_id=session_id,
                user_id=self._user.id,
                team=self._team,
                model_to_use=SESSION_SUMMARIES_STREAMING_MODEL,
            )
            completed += 1
            # Update the user on the progress
            self._stream_progress(progress_message=f"Watching sessions ({completed}/{total})", writer=writer)
            return result

        # Run all tasks concurrently
        tasks = [_summarize(sid) for sid in session_ids]
        summaries = await asyncio.gather(*tasks)
        # TODO: Add layer to convert JSON into more readable text for Max to returns to user
        self._stream_progress(progress_message=f"Generating a summary, almost there", writer=writer)
        return "\n".join(summaries)

    async def _summarize_sessions_as_group(
        self, session_ids: list[str], state: AssistantState, writer: StreamWriter | None, notebook: Notebook | None
    ) -> str:
        """Summarize sessions as a group (for larger sets)."""
        min_timestamp, max_timestamp = find_sessions_timestamps(session_ids=session_ids, team=self._team)

        # Initialize intermediate state with plan
        self._intermediate_state = SummaryNotebookIntermediateState(team_name=self._team.name)

        # Stream initial plan
        initial_state = self._intermediate_state.format_intermediate_state()
        self._stream_notebook_content(initial_state, state, writer)

        async for update_type, step, data in execute_summarize_session_group(
            session_ids=session_ids,
            user_id=self._user.id,
            team=self._team,
            min_timestamp=min_timestamp,
            max_timestamp=max_timestamp,
            extra_summary_context=None,
            local_reads_prod=False,
        ):
            # Max "reasoning" text update message
            if update_type == SessionSummaryStreamUpdate.UI_STATUS:
                if not isinstance(data, str):
                    raise TypeError(
                        f"Unexpected data type for stream update {SessionSummaryStreamUpdate.UI_STATUS}: {type(data)} "
                        f"(expected: str)"
                    )
                # Update intermediate state based on step enum (no content, as it's just a status message)
                self._intermediate_state.update_step_progress(content=None, step=step)
                # Status message - stream to user
                self._stream_progress(progress_message=data, writer=writer)
            # Notebook intermediate data update messages
            elif update_type == SessionSummaryStreamUpdate.NOTEBOOK_UPDATE:
                if not isinstance(data, dict):
                    raise TypeError(
                        f"Unexpected data type for stream update {SessionSummaryStreamUpdate.NOTEBOOK_UPDATE}: {type(data)} "
                        f"(expected: dict)"
                    )
                # Update intermediate state based on step enum
                self._intermediate_state.update_step_progress(content=data, step=step)
                # Stream the updated intermediate state
                formatted_state = self._intermediate_state.format_intermediate_state()
                self._stream_notebook_content(formatted_state, state, writer)
            # Final summary result
            elif update_type == SessionSummaryStreamUpdate.FINAL_RESULT:
                if not isinstance(data, EnrichedSessionGroupSummaryPatternsList):
                    raise ValueError(
                        f"Unexpected data type for stream update {SessionSummaryStreamUpdate.FINAL_RESULT}: {type(data)} "
                        f"(expected: EnrichedSessionGroupSummaryPatternsList)"
                    )
                # Replace the intermediate state with final report
                summary = data
                summary_content = generate_notebook_content_from_summary(
                    summary=summary, session_ids=session_ids, project_name=self._team.name, team_id=self._team.id
                )
                self._stream_notebook_content(summary_content, state, writer, partial=False)
                # Update the notebook through BE for cases where the chat was closed
                await update_notebook_from_summary_content(
                    notebook=notebook, summary_content=summary_content, session_ids=session_ids
                )
                # Return the summary to Max to generate inline summary of the full summary
                return summary.model_dump_json(exclude_none=True)
            else:
                raise ValueError(
                    f"Unexpected update type ({update_type}) in session group summarization (session_ids: {logging_session_ids(session_ids)})."
                )
        else:
            raise ValueError(
                f"No summary was generated from session group summarization (session_ids: {logging_session_ids(session_ids)})"
            )

    async def arun(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState | None:
        start_time = time.time()
        conversation_id = config.get("configurable", {}).get("thread_id", "unknown")
        writer = self._get_stream_writer()
        # If query was not provided for some reason
        if not state.session_summarization_query:
            self._log_failure(
                f"Session summarization query is not provided: {state.session_summarization_query}",
                conversation_id,
                start_time,
            )
            return self._create_error_response(self._base_error_instructions, state)
        try:
            # Generate filters to get session ids from DB
            replay_filters = await self._generate_replay_filters(state.session_summarization_query)
            if not replay_filters:
                self._log_failure(
                    f"No Replay filters were generated for session summarization: {state.session_summarization_query}",
                    conversation_id,
                    start_time,
                )
                return self._create_error_response(self._base_error_instructions, state)
            # Query the filters to get session ids
            session_ids = await database_sync_to_async(self._get_session_ids_with_filters, thread_sensitive=False)(
                replay_filters
            )
            if not session_ids:
                return PartialAssistantState(
                    messages=[
                        AssistantToolCallMessage(
                            content="No sessions were found.",
                            tool_call_id=state.root_tool_call_id or "unknown",
                            id=str(uuid4()),
                        ),
                    ],
                    session_summarization_query=None,
                    root_tool_call_id=None,
                )
            # Process sessions based on count
            base_message = f"Found sessions ({len(session_ids)})"
            if len(session_ids) <= GROUP_SUMMARIES_MIN_SESSIONS:
                # If small amount of sessions - there are no patterns to extract, so summarize them individually and return as is
                self._stream_progress(
                    progress_message=f"{base_message}. We will do a quick summary, as the scope is small",
                    writer=writer,
                )
                summaries_content = await self._summarize_sessions_individually(session_ids=session_ids, writer=writer)
            else:
                # Check if the notebook is provided, create a notebook to fill if not
                notebook = None
                if not state.notebook_id:
                    notebook = await create_empty_notebook_for_summary(user=self._user, team=self._team)
                    # Could be moved to a separate "create notebook" node (or reuse the one from deep research)
                    state.notebook_id = notebook.short_id
                # For large groups, process in detail, searching for patterns
                # TODO: Allow users to define the pattern themselves (or rather catch it from the query)
                self._stream_progress(
                    progress_message=f"{base_message}. We will analyze in detail, and store the report in a notebook",
                    writer=writer,
                )
                summaries_content = await self._summarize_sessions_as_group(
                    session_ids=session_ids, state=state, writer=writer, notebook=notebook
                )
            return PartialAssistantState(
                messages=[
                    AssistantToolCallMessage(
                        content=summaries_content,
                        tool_call_id=state.root_tool_call_id or "unknown",
                        id=str(uuid4()),
                    ),
                ],
                session_summarization_query=None,
                root_tool_call_id=None,
                # Ensure to pass the notebook id to the next node
                notebook_id=state.notebook_id,
            )
        except Exception as err:
            self._log_failure("Session summarization failed", conversation_id, start_time, err)
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
            session_summarization_query=None,
            root_tool_call_id=None,
            notebook_id=state.notebook_id,
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
        return "INSTRUCTIONS: Tell the user that you encountered an issue while summarizing the session and suggest they try again with a different question."
