import asyncio
import time
from typing import cast, Literal, Any
from uuid import uuid4
from langgraph.types import StreamWriter
import structlog
from langchain_core.runnables import RunnableConfig

from ee.hogai.graph.base import AssistantNode
from ee.hogai.session_summaries.constants import SESSION_SUMMARIES_STREAMING_MODEL, GROUP_SUMMARIES_MIN_SESSIONS
from ee.hogai.session_summaries.session_group.patterns import EnrichedSessionGroupSummaryPatternsList
from ee.hogai.session_summaries.session_group.summarize_session_group import find_sessions_timestamps
from ee.hogai.session_summaries.session_group.summary_notebooks import create_summary_notebook
from ee.hogai.utils.types import AssistantState, PartialAssistantState, AssistantNodeName
from posthog.schema import MaxRecordingUniversalFilters, RecordingsQuery, AssistantToolCallMessage
from posthog.sync import database_sync_to_async
from posthog.temporal.ai.session_summary.summarize_session import execute_summarize_session
from posthog.temporal.ai.session_summary.summarize_session_group import execute_summarize_session_group
from langgraph.config import get_stream_writer
from langchain_core.messages import AIMessageChunk


class SessionSummarizationNode(AssistantNode):
    logger = structlog.get_logger(__name__)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

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
        message_chunk = AIMessageChunk(
            content="",
            additional_kwargs={"reasoning": {"summary": [{"text": f"**{progress_message}**"}]}},
        )
        message = (message_chunk, {"langgraph_node": AssistantNodeName.SESSION_SUMMARIZATION})
        writer(("session_summarization_node", "messages", message))
        return

    async def _generate_replay_filters(self, plain_text_query: str) -> MaxRecordingUniversalFilters | None:
        """Generates replay filters to get session ids by querying a compiled Universal filters graph."""
        from ee.hogai.graph.filter_options.prompts import PRODUCT_DESCRIPTION_PROMPT
        from products.replay.backend.prompts import SESSION_REPLAY_RESPONSE_FORMATS_PROMPT
        from products.replay.backend.prompts import SESSION_REPLAY_EXAMPLES_PROMPT
        from products.replay.backend.prompts import MULTIPLE_FILTERS_PROMPT
        from ee.hogai.graph.filter_options.graph import FilterOptionsGraph

        # Create the graph with injected prompts
        injected_prompts = {
            "product_description_prompt": PRODUCT_DESCRIPTION_PROMPT,
            "response_formats_prompt": SESSION_REPLAY_RESPONSE_FORMATS_PROMPT,
            "examples_prompt": SESSION_REPLAY_EXAMPLES_PROMPT,
            "multiple_filters_prompt": MULTIPLE_FILTERS_PROMPT,
        }
        graph = FilterOptionsGraph(self._team, self._user, injected_prompts=injected_prompts).compile_full_graph()
        # Call with your query
        result = await graph.ainvoke(
            {
                "change": plain_text_query,
                "current_filters": {},  # Empty state, as we need results from the query-to-filter
            }
        )
        if (
            not result
            or not isinstance(result, dict)
            or not result.get("generated_filter_options")
            or not result["generated_filter_options"].get("data")
        ):
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
        filters_data = result["generated_filter_options"]["data"]
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

    async def _summarize_sessions_as_group(self, session_ids: list[str], writer: StreamWriter | None) -> str:
        """Summarize sessions as a group (for larger sets)."""
        min_timestamp, max_timestamp = find_sessions_timestamps(session_ids=session_ids, team=self._team)
        summary = None
        async for update in execute_summarize_session_group(
            session_ids=session_ids,
            user_id=self._user.pk,
            team=self._team,
            min_timestamp=min_timestamp,
            max_timestamp=max_timestamp,
            extra_summary_context=None,
            local_reads_prod=False,
        ):
            if isinstance(update, str):
                # Status message - stream to user
                self._stream_progress(progress_message=update, writer=writer)
            elif isinstance(update, EnrichedSessionGroupSummaryPatternsList):
                # Final summary
                summary = update
            else:
                raise ValueError(
                    f"Unexpected update type ({type(update)}) in session group summarization (session_ids: {session_ids})."
                )
        if summary:
            await database_sync_to_async(create_summary_notebook)(
                session_ids=session_ids, user=self._user, team=self._team, summary=summary
            )
            return summary.model_dump_json(exclude_none=True)
        else:
            raise ValueError(f"No summary was generated from session group summarization (session_ids: {session_ids})")

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
            return self._create_error_response(self._base_error_instructions, state.root_tool_call_id)
        try:
            # Generate filters to get session ids from DB
            replay_filters = await self._generate_replay_filters(state.session_summarization_query)
            if not replay_filters:
                self._log_failure(
                    f"No Replay filters were generated for session summarization: {state.session_summarization_query}",
                    conversation_id,
                    start_time,
                )
                return self._create_error_response(self._base_error_instructions, state.root_tool_call_id)
            # Query the filters to get session ids
            session_ids = await database_sync_to_async(self._get_session_ids_with_filters)(replay_filters)
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
                # For large groups, process in detail, searching for patterns
                # TODO: Allow users to define the pattern themselves
                self._stream_progress(
                    progress_message=f"{base_message}. We will analyze in detail, and store the report in a notebook",
                    writer=writer,
                )
                summaries_content = await self._summarize_sessions_as_group(session_ids=session_ids, writer=writer)
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
            )
        except Exception as err:
            self._log_failure("Session summarization failed", conversation_id, start_time, err)
            return self._create_error_response(self._base_error_instructions, state.root_tool_call_id)

    def _create_error_response(self, message: str, root_tool_call_id: str | None) -> PartialAssistantState:
        return PartialAssistantState(
            messages=[
                AssistantToolCallMessage(
                    content=message,
                    tool_call_id=root_tool_call_id or "unknown",
                    id=str(uuid4()),
                ),
            ],
            session_summarization_query=None,
            root_tool_call_id=None,
        )

    def _log_failure(self, message: str, conversation_id: str, start_time: float, error: Any = None):
        self.logger.exception(
            message,
            extra={
                "team_id": getattr(self._team, "id", "unknown"),
                "conversation_id": conversation_id,
                "execution_time_ms": round(time.time() - start_time * 1000, 2),
                "error": str(error) if error else None,
            },
        )

    @property
    def _base_error_instructions(self) -> str:
        return "INSTRUCTIONS: Tell the user that you encountered an issue while summarizing the session and suggest they try again with a different question."

    def router(self, _: AssistantState) -> Literal["end", "root"]:
        return "root"
