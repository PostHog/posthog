import time
import asyncio
from typing import Any, Literal, cast
from uuid import uuid4

import structlog
import posthoganalytics
from langchain_core.agents import AgentAction
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableConfig

from posthog.schema import AssistantMessage, AssistantToolCallMessage, MaxRecordingUniversalFilters, RecordingsQuery

from posthog.session_recordings.playlist_counters import convert_filters_to_recordings_query
from posthog.sync import database_sync_to_async
from posthog.temporal.ai.session_summary.summarize_session import execute_summarize_session
from posthog.temporal.ai.session_summary.summarize_session_group import (
    SessionSummaryStreamUpdate,
    execute_summarize_session_group,
)

from ee.hogai.chat_agent.session_summaries.prompts import GENERATE_FILTER_QUERY_PROMPT
from ee.hogai.core.node import AssistantNode
from ee.hogai.llm import MaxChatOpenAI
from ee.hogai.session_summaries.constants import (
    GROUP_SUMMARIES_MIN_SESSIONS,
    MAX_SESSIONS_TO_SUMMARIZE,
    SESSION_SUMMARIES_SYNC_MODEL,
)
from ee.hogai.session_summaries.session.stringify import SingleSessionSummaryStringifier
from ee.hogai.session_summaries.session_group.patterns import EnrichedSessionGroupSummaryPatternsList
from ee.hogai.session_summaries.session_group.stringify import SessionGroupSummaryStringifier
from ee.hogai.session_summaries.session_group.summarize_session_group import find_sessions_timestamps
from ee.hogai.session_summaries.tracking import (
    capture_session_summary_generated,
    capture_session_summary_started,
    generate_tracking_id,
)
from ee.hogai.session_summaries.utils import logging_session_ids
from ee.hogai.utils.state import prepare_reasoning_progress_message
from ee.hogai.utils.types import AssistantState, PartialAssistantState
from ee.hogai.utils.types.base import AssistantNodeName
from ee.hogai.utils.types.composed import MaxNodeName


class SessionSummarizationNode(AssistantNode):
    logger = structlog.get_logger(__name__)

    @property
    def node_name(self) -> MaxNodeName:
        return AssistantNodeName.SESSION_SUMMARIZATION

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._session_search = _SessionSearch(self)
        self._session_summarizer = _SessionSummarizer(self)

    def _stream_progress(self, progress_message: str) -> None:
        """Push summarization progress as reasoning messages"""
        content = prepare_reasoning_progress_message(progress_message)
        if content:
            self.dispatcher.update(content)

    def _stream_filters(self, filters: MaxRecordingUniversalFilters) -> None:
        """Stream filters to the user"""
        self.dispatcher.message(
            AssistantToolCallMessage(
                content="",
                ui_payload={"search_session_recordings": filters.model_dump(exclude_none=True)},
                # Randomized tool call ID, as we don't want this to be THE result of the actual session summarization tool call
                # - it's OK because this is only dispatched ephemerally, so the tool message doesn't get added to the state
                tool_call_id=str(uuid4()),
            )
        )

    def _determine_video_validation_enabled(self) -> bool | Literal["full"]:
        """
        Check if the user has the video validation for session summaries feature flag enabled.
        """
        if posthoganalytics.feature_enabled(
            "max-session-summarization-video-as-base",
            str(self._user.distinct_id),
            groups={"organization": str(self._team.organization_id)},
            group_properties={"organization": {"id": str(self._team.organization_id)}},
            send_feature_flag_events=False,
        ):
            return "full"  # Use video as base of summarization
        return (
            posthoganalytics.feature_enabled(
                "max-session-summarization-video-validation",
                str(self._user.distinct_id),
                groups={"organization": str(self._team.organization_id)},
                group_properties={"organization": {"id": str(self._team.organization_id)}},
                send_feature_flag_events=False,
            )
            or False
        )

    async def arun(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState | None:
        start_time = time.time()
        conversation_id = config.get("configurable", {}).get("thread_id", "unknown")
        # Search for session ids with filters (current or generated)
        search_result = await self._session_search.search_sessions(state, conversation_id, start_time, config)
        # No sessions were found
        if not search_result:
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
        # The search failed or clarification is needed
        if isinstance(search_result, PartialAssistantState):
            return search_result
        # We have session IDs - start tracking
        session_ids = search_result
        summary_type: Literal["single", "group"] = (
            "single" if len(session_ids) <= GROUP_SUMMARIES_MIN_SESSIONS else "group"
        )
        video_validation_enabled = self._determine_video_validation_enabled()
        tracking_id = generate_tracking_id()
        capture_session_summary_started(
            user=self._user,
            team=self._team,
            tracking_id=tracking_id,
            summary_source="chat",
            summary_type=summary_type,
            is_streaming=False,
            session_ids=session_ids,
            video_validation_enabled=video_validation_enabled,
        )
        try:
            # Summarize sessions
            summaries_content, session_group_summary_id = await self._session_summarizer.summarize_sessions(
                session_ids=session_ids, state=state
            )
            # Build messages list
            messages: list = []
            # Add session group summary message for frontend "View summary" button (only for group summaries)
            if session_group_summary_id:
                messages.append(
                    AssistantMessage(
                        meta={
                            "form": {
                                "options": [
                                    {
                                        "value": "Open report",
                                        "href": f"/session-summaries/{session_group_summary_id}",
                                        "variant": "primary",
                                    }
                                ]
                            }
                        },
                        content=f"Report complete: {state.summary_title or 'Sessions summary'}",
                        id=str(uuid4()),
                    )
                )
            # Add content
            messages.append(
                AssistantToolCallMessage(
                    content=summaries_content,
                    tool_call_id=state.root_tool_call_id or "unknown",
                    id=str(uuid4()),
                ),
            )
            ready_state = PartialAssistantState(
                messages=messages, session_summarization_query=None, root_tool_call_id=None
            )
        except Exception as err:
            # The session summarization failed
            self._log_failure("Session summarization failed", conversation_id, start_time, err)
            capture_session_summary_generated(
                user=self._user,
                team=self._team,
                tracking_id=tracking_id,
                summary_source="chat",
                summary_type=summary_type,
                is_streaming=False,
                session_ids=session_ids,
                video_validation_enabled=video_validation_enabled,
                success=False,
                error_type=type(err).__name__,
                error_message=str(err),
            )
            return self._create_error_response(self._base_error_instructions, state)
        # The session successfully summarized
        capture_session_summary_generated(
            user=self._user,
            team=self._team,
            tracking_id=tracking_id,
            summary_source="chat",
            summary_type=summary_type,
            is_streaming=False,
            session_ids=session_ids,
            video_validation_enabled=video_validation_enabled,
            success=True,
        )
        return ready_state

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
            signals_type="session-summaries",
        )

    @property
    def _base_error_instructions(self) -> str:
        return "INSTRUCTIONS: Tell the user that you encountered an issue while summarizing the session and suggest they try again with a different question."


class _SessionSearch:
    """Handles the search to get session ids with filters (current or generated)"""

    def __init__(self, node: SessionSummarizationNode):
        self._node = node

    async def _generate_replay_filters(
        self, state: AssistantState, config: RunnableConfig, filter_query: str, conversation_id: str, start_time: float
    ) -> MaxRecordingUniversalFilters | str | None:
        """
        Generates replay filters to get session ids by directly using SearchSessionRecordingsTool.

        Returns:
            - filters: MaxRecordingUniversalFilters if successful
            - question: str if clarification is needed
            - None if there's an error
        """
        from products.replay.backend.max_tools import SearchSessionRecordingsTool  # Avoid circular import

        # Create the tool instance with minimal context (no current_filters for fresh generation)
        tool = await SearchSessionRecordingsTool.create_tool_class(
            team=self._node._team,
            user=self._node._user,
            node_path=self._node.node_path,
            state=state,
            config=config,
            context_manager=self._node.context_manager,
        )
        try:
            # Call the tool's graph directly to use the same implementation as in the tool (avoid duplication)
            result = await tool._invoke_graph(change=filter_query)
            if not result.get("output"):
                self._node._log_failure(
                    f"SearchSessionRecordingsTool returned no output for session summarization (query: {filter_query})",
                    conversation_id,
                    start_time,
                )
                return None
            output = result["output"]
            # Return filters if generated successfully
            if isinstance(output, MaxRecordingUniversalFilters):
                return output
            # Return clarification question if needed
            if not result.get("intermediate_steps") or not len(result["intermediate_steps"][-1]):
                self._node._log_failure(
                    f"SearchSessionRecordingsTool returned no intermediate steps for session summarization (query: {filter_query}): {result}",
                    conversation_id,
                    start_time,
                )
                return None
            last_step = result["intermediate_steps"][-1][0]
            if (
                not isinstance(last_step, AgentAction)
                or last_step.tool != "ask_user_for_help"
                or not isinstance(last_step.tool_input, str)
            ):
                self._node._log_failure(
                    f"SearchSessionRecordingsTool last step was neither filters nor ask_user_for_help "
                    f"for session summarization (query: {filter_query}): {result}",
                    conversation_id,
                    start_time,
                )
                return None
            return last_step.tool_input
        except Exception as e:
            self._node.logger.exception(
                f"Unexpected error generating replay filters for session summarization: {e}",
                extra={
                    "team_id": getattr(self._node._team, "id", "unknown"),
                    "user_id": getattr(self._node._user, "id", "unknown"),
                    "query": filter_query,
                },
                signals_type="session-summaries",
            )
            return None

    def _get_session_ids_with_filters(self, replay_filters: RecordingsQuery) -> list[str] | None:
        """Get session ids from DB with filters"""
        from posthog.session_recordings.queries.session_recording_list_from_query import SessionRecordingListFromQuery

        # Execute the query to get session IDs
        try:
            query_runner = SessionRecordingListFromQuery(
                team=self._node._team, query=replay_filters, hogql_query_modifiers=None
            )
            results = query_runner.run()
        except Exception as e:
            self._node.logger.exception(
                f"Error getting session ids for session summarization with filters query "
                f"({replay_filters.model_dump_json(exclude_none=True)}): {e}",
                signals_type="session-summaries",
            )
            return None
        # Extract session IDs
        session_ids = [recording["session_id"] for recording in results.results]
        return session_ids if session_ids else None

    def _validate_specific_session_ids(self, session_ids: list[str]) -> list[str] | None:
        """Validate that specific session IDs exist in the database."""
        from posthog.session_recordings.queries.session_replay_events import SessionReplayEvents

        replay_events = SessionReplayEvents()
        sessions_found, _, _ = replay_events.sessions_found_with_timestamps(
            session_ids=session_ids,
            team=self._node._team,
        )
        if not sessions_found:
            return None
        # Preserve the original order, filtering out invalid sessions
        return [sid for sid in session_ids if sid in sessions_found]

    async def _generate_filter_query(self, plain_text_query: str, config: RunnableConfig) -> str:
        """Generate a filter query for the user's summarization query to keep the search context clear"""
        messages = [
            ("human", GENERATE_FILTER_QUERY_PROMPT.format(input_query=plain_text_query)),
        ]
        prompt = ChatPromptTemplate.from_messages(messages)
        model = MaxChatOpenAI(
            model="gpt-4.1", temperature=0.3, disable_streaming=True, user=self._node._user, team=self._node._team
        )
        chain = prompt | model | StrOutputParser()
        filter_query = chain.invoke({}, config=config)
        # Validate the generated filter query is not empty or just whitespace
        if not filter_query or not filter_query.strip():
            msg = f"Filter query generated for session summarization is empty or just whitespace (initial query: {plain_text_query})"
            self._node.logger.error(msg, signals_type="session-summaries")
            raise ValueError(msg)
        return filter_query

    async def search_sessions(
        self, state: AssistantState, conversation_id: str, start_time: float, config: RunnableConfig
    ) -> list[str] | PartialAssistantState | None:
        # If query was not provided for some reason
        if state.session_summarization_query is None:
            self._node._log_failure(
                f"Session summarization query is not provided when summarizing sessions: {state.session_summarization_query}",
                conversation_id,
                start_time,
            )
            return self._node._create_error_response(self._node._base_error_instructions, state)
        # If the decision on the current filters is not made
        if state.should_use_current_filters is None:
            self._node._log_failure(
                f"Use current filters decision is not made when summarizing sessions: {state.should_use_current_filters}",
                conversation_id,
                start_time,
            )
            return self._node._create_error_response(self._node._base_error_instructions, state)
        # If the current filters were marked as relevant, but not present in the context
        search_session_recordings_context = self._node.context_manager.get_contextual_tools().get(
            "search_session_recordings", {}
        )
        current_filters = search_session_recordings_context.get("current_filters")
        try:
            # Check what to use - filters or specific session IDs, as they are mutually exclusive
            if state.specific_session_ids_to_summarize and state.should_use_current_filters:
                self._node._log_failure(
                    f"specific_session_ids_to_summarize and should_use_current_filters cannot be set at the same time",
                    conversation_id,
                    start_time,
                )
                return self._node._create_error_response(self._node._base_error_instructions, state)
            # Use specific session IDs, if provided
            if state.specific_session_ids_to_summarize:
                # Validate that sessions exist before using them
                valid_session_ids = await database_sync_to_async(
                    self._validate_specific_session_ids, thread_sensitive=False
                )(state.specific_session_ids_to_summarize)
                if not valid_session_ids:
                    return None
                return valid_session_ids
            # Use current filters, if provided
            if state.should_use_current_filters:
                if not current_filters:
                    self._node._log_failure(
                        f"Use current filters decision was set to True, but current filters were not provided when summarizing sessions: {state.should_use_current_filters}",
                        conversation_id,
                        start_time,
                    )
                    return self._node._create_error_response(self._node._base_error_instructions, state)
                current_filters = cast(dict[str, Any], current_filters)
                replay_filters = convert_filters_to_recordings_query(current_filters)
            # If not - generate filters to get session ids from DB
            else:
                filter_query = await self._generate_filter_query(state.session_summarization_query, config)
                filter_generation_result = await self._generate_replay_filters(
                    state=state,
                    config=config,
                    filter_query=filter_query,
                    conversation_id=conversation_id,
                    start_time=start_time,
                )
                if filter_generation_result is None:
                    return self._node._create_error_response(
                        "INSTRUCTIONS: Tell the user that you encountered an issue while generating session filters to match the user's query. "
                        'Suggest to use more specific conditions (like ids) or go to "Session replay" page and use its filters when summarizing.',
                        state,
                    )
                # Check if we got a clarification question instead of filters
                if isinstance(filter_generation_result, str):
                    # Return the clarification question to the user
                    return PartialAssistantState(
                        messages=[
                            AssistantToolCallMessage(
                                content=filter_generation_result,
                                tool_call_id=state.root_tool_call_id or "unknown",
                                id=str(uuid4()),
                            ),
                        ],
                        session_summarization_query=None,
                        root_tool_call_id=None,
                    )
                # Use filters when generated successfully
                replay_filters = convert_filters_to_recordings_query(
                    filter_generation_result.model_dump(exclude_none=True)
                )
                self._node._stream_filters(filter_generation_result)
            # Query the filters to get session ids
            if (
                not replay_filters.limit
                or replay_filters.limit <= 0
                or replay_filters.limit > MAX_SESSIONS_TO_SUMMARIZE
            ):
                # If no limit provided (none or negative) or too large - use the default limit
                replay_filters.limit = MAX_SESSIONS_TO_SUMMARIZE
            session_ids = await database_sync_to_async(self._get_session_ids_with_filters, thread_sensitive=False)(
                replay_filters
            )
            return session_ids
        except Exception as e:
            self._node._log_failure(
                f"Unexpected error when searching sessions for session summarization: {e}",
                conversation_id,
                start_time,
            )
            return self._node._create_error_response(self._node._base_error_instructions, state)


class _SessionSummarizer:
    """Handles the summarization of session recordings"""

    def __init__(self, node: SessionSummarizationNode):
        self._node = node

    async def _summarize_sessions_individually(self, session_ids: list[str]) -> str:
        """Summarize sessions individually with progress updates."""
        total = len(session_ids)
        completed = 0
        video_validation_enabled = self._node._determine_video_validation_enabled()

        async def _summarize(session_id: str) -> dict[str, Any]:
            nonlocal completed
            result = await execute_summarize_session(
                session_id=session_id,
                user=self._node._user,
                team=self._node._team,
                model_to_use=SESSION_SUMMARIES_SYNC_MODEL,
                video_validation_enabled=video_validation_enabled,
            )
            completed += 1
            # Update the user on the progress
            self._node._stream_progress(progress_message=f"Watching sessions ({completed}/{total})")
            return result

        # Run all tasks concurrently
        tasks = [_summarize(sid) for sid in session_ids]
        summaries = await asyncio.gather(*tasks)
        self._node._stream_progress(progress_message=f"Generating a summary, almost there")
        # Stringify, as chat doesn't need full JSON to be context-aware, while providing it could overload the context
        stringified_summaries = []
        for summary in summaries:
            stringifier = SingleSessionSummaryStringifier(summary)
            stringified_summaries.append(stringifier.stringify_session())
        # Combine all stringified summaries into a single string
        summaries_str = "\n\n".join(stringified_summaries)
        return summaries_str

    async def _summarize_sessions_as_group(
        self, session_ids: list[str], state: AssistantState, summary_title: str | None
    ) -> tuple[str, str]:
        """Summarize sessions as a group (for larger sets). Returns tuple of (summary_str, session_group_summary_id)."""
        min_timestamp, max_timestamp = await database_sync_to_async(find_sessions_timestamps, thread_sensitive=False)(
            session_ids=session_ids, team=self._node._team
        )
        # Check if the summaries should be validated with videos
        video_validation_enabled = self._node._determine_video_validation_enabled()

        async for update_type, data in execute_summarize_session_group(
            session_ids=session_ids,
            user=self._node._user,
            team=self._node._team,
            min_timestamp=min_timestamp,
            max_timestamp=max_timestamp,
            summary_title=summary_title,
            extra_summary_context=None,
            video_validation_enabled=video_validation_enabled,
        ):
            # Max "reasoning" text update message
            if update_type == SessionSummaryStreamUpdate.UI_STATUS:
                if not isinstance(data, str):
                    msg = (
                        f"Unexpected data type for stream update {SessionSummaryStreamUpdate.UI_STATUS}: {type(data)} "
                        f"(expected: str)"
                    )
                    self._node.logger.error(msg, signals_type="session-summaries")
                    raise TypeError(msg)
                # Status message - stream to user
                self._node._stream_progress(progress_message=data)
            # Final summary result
            elif update_type == SessionSummaryStreamUpdate.FINAL_RESULT:
                if not isinstance(data, tuple) or len(data) != 2:
                    msg = (
                        f"Unexpected data type for stream update {SessionSummaryStreamUpdate.FINAL_RESULT}: {type(data)} "
                        f"(expected: tuple[EnrichedSessionGroupSummaryPatternsList, str])"
                    )
                    self._node.logger.error(msg, signals_type="session-summaries")
                    raise ValueError(msg)
                summary, session_group_summary_id = data
                if not isinstance(summary, EnrichedSessionGroupSummaryPatternsList):
                    msg = (  # type: ignore[unreachable]
                        f"Unexpected data type for patterns in stream update {SessionSummaryStreamUpdate.FINAL_RESULT}: {type(summary)} "
                        f"(expected: EnrichedSessionGroupSummaryPatternsList)"
                    )
                    self._node.logger.error(msg, signals_type="session-summaries")
                    raise ValueError(msg)
                # Stringify the summary to "weight" less and apply example limits per pattern, so it won't overload the context
                stringifier = SessionGroupSummaryStringifier(summary.model_dump(exclude_none=False))
                summary_str = stringifier.stringify_patterns()
                return summary_str, session_group_summary_id
            else:
                msg = f"Unexpected update type ({update_type}) in session group summarization (session_ids: {logging_session_ids(session_ids)})."  # type: ignore[unreachable]
                self._node.logger.error(msg, signals_type="session-summaries")
                raise ValueError(msg)
        else:
            msg = f"No summary was generated from session group summarization (session_ids: {logging_session_ids(session_ids)})"
            self._node.logger.error(msg, signals_type="session-summaries")
            raise ValueError(msg)

    async def summarize_sessions(
        self,
        session_ids: list[str],
        state: AssistantState,
    ) -> tuple[str, str | None]:
        """
        Summarize sessions. Returns tuple of (summary_str, session_group_summary_id).
        session_group_summary_id is None for individual summaries (<= GROUP_SUMMARIES_MIN_SESSIONS).
        """
        # Process sessions based on count
        base_message = f"Found sessions ({len(session_ids)})"
        if len(session_ids) <= GROUP_SUMMARIES_MIN_SESSIONS:
            # If small amount of sessions - there are no patterns to extract, so summarize them individually and return as is
            self._node._stream_progress(
                progress_message=f"{base_message}. We will do a quick summary, as the scope is small",
            )
            summaries_content = await self._summarize_sessions_individually(session_ids=session_ids)
            return summaries_content, None
        # For large groups, process in detail, searching for patterns
        self._node._stream_progress(
            progress_message=f"{base_message}. We will analyze in detail, and store the report",
        )
        summaries_content, session_group_summary_id = await self._summarize_sessions_as_group(
            session_ids=session_ids, state=state, summary_title=state.summary_title
        )
        return summaries_content, session_group_summary_id
