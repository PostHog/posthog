import asyncio
from textwrap import dedent
from typing import Any, Literal
from uuid import uuid4

import structlog
import posthoganalytics
from pydantic import BaseModel, Field

from posthog.schema import AssistantMessage, AssistantToolCallMessage, MaxRecordingUniversalFilters, RecordingsQuery

from posthog.session_recordings.playlist_counters import convert_filters_to_recordings_query
from posthog.sync import database_sync_to_async
from posthog.temporal.ai.session_summary.summarize_session import execute_summarize_session
from posthog.temporal.ai.session_summary.summarize_session_group import (
    SessionSummaryStreamUpdate,
    execute_summarize_session_group,
)
from posthog.utils import pluralize

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
from ee.hogai.tool import MaxTool, ToolMessagesArtifact
from ee.hogai.utils.state import prepare_reasoning_progress_message

logger = structlog.get_logger(__name__)


class SummarizeSessionsToolArgs(BaseModel):
    recordings_filters_or_explicit_session_ids: MaxRecordingUniversalFilters | list[str] = Field(
        description=dedent(
            """
        - User's question converted into a JSON object that will be used to search for relevant session recordings to summarize, based on filter_session_recordings use.
        - If the user provided explicit sessions IDs, or requested ones from context to be use, pass this as a list of those UUIDs.
          Important: If the user refers to a query created by search_session_recordings in the context, use those filters as a filters object instead of the list of UUIDs, as there could be hundreds of UUIDs to pass.
        """
        ).strip()
    )
    summary_title: str = Field(
        description=dedent(
            """
        - The name of the summary that is expected to be generated from the user's `search_query`.
        - The name should cover in 3-7 words what sessions would be to be summarized in the summary
        - This won't be used for any search of filtering, only to properly label the generated summary.
        - Examples:
            - filters: "{"key":"$os","value":["Mac OS X"],"operator":"exact","type":"event"}" -> name: "MacOS users"
            - filters: "{"date_from": "-7d", "filter_test_accounts": True}" -> name: "All sessions (last 7 days)"
            - and similar
        * If there's not enough context to generated the summary name - keep it an empty string ("")
        """
        ).strip()
    )


class SummarizeSessionsTool(MaxTool):
    name: Literal["summarize_sessions"] = "summarize_sessions"
    description: str = dedent(
        """
        Use this tool to summarize session recordings by analyzing the events within those sessions (and the visual recordings) to find patterns and issues.

        If explicit session IDs to summarize were not specified by the user, you should first use the filter_session_recordings tool to filter for relevant recordings.
        Do not use this tool if the preceding filter_session_recordings call returned no results.

        To use session summarization, get the filters right rather than accepting subpar ones (no results is likely a filtering issue rather than a data issue)
        """
    ).strip()
    args_schema: type[BaseModel] = SummarizeSessionsToolArgs

    def get_required_resource_access(self):
        return [("session_recording", "viewer")]

    async def _arun_impl(
        self,
        recordings_filters_or_explicit_session_ids: MaxRecordingUniversalFilters | list[str],
        summary_title: str,
    ) -> tuple[str, ToolMessagesArtifact | None]:
        # If filters - convert filters to recordings query and get session IDs
        if isinstance(recordings_filters_or_explicit_session_ids, MaxRecordingUniversalFilters):
            recordings_query = convert_filters_to_recordings_query(
                recordings_filters_or_explicit_session_ids.model_dump(exclude_none=True)
            )
            # Determine query limit
            if (
                not recordings_query.limit
                or recordings_query.limit <= 0
                or recordings_query.limit > MAX_SESSIONS_TO_SUMMARIZE
            ):
                # If no limit provided (none or negative) or too large - use the default limit
                recordings_query.limit = MAX_SESSIONS_TO_SUMMARIZE
            # Get session IDs
            llm_provided_session_ids = await database_sync_to_async(
                self._get_session_ids_with_filters, thread_sensitive=False
            )(recordings_query)
            llm_provided_session_ids_source: Literal["filters", "explicit"] = "filters"
        # If explicit session IDs - use them directly
        elif isinstance(recordings_filters_or_explicit_session_ids, list):
            llm_provided_session_ids = recordings_filters_or_explicit_session_ids
            llm_provided_session_ids_source = "explicit"
        # If unexpected type - raise an error
        else:
            msg = (  # type: ignore[unreachable]
                f"Unexpected type of recordings_filters_or_explicit_session_ids: "
                f"{type(recordings_filters_or_explicit_session_ids)}: {recordings_filters_or_explicit_session_ids}"
            )
            logger.error(msg, signals_type="session-summaries")
            raise ValueError(msg)
        # If LLM provided no session ids - nothing to summarize
        if not llm_provided_session_ids:
            return "No sessions were found matching the specified criteria.", None
        # Confirm that the sessions provided by the LLM (through filters or explicitly) are true sessions with events (to avoid DB query failures)
        session_ids = await database_sync_to_async(self._validate_specific_session_ids, thread_sensitive=False)(
            llm_provided_session_ids
        )
        # LLM provided session ids, but no actual sessions with events were found
        if not session_ids:
            llm_provided_input = (
                recordings_filters_or_explicit_session_ids
                if isinstance(recordings_filters_or_explicit_session_ids, list)
                else recordings_filters_or_explicit_session_ids.model_dump_json(exclude_none=True)
            )
            logger.warning(
                (
                    f"No sessions with events were found for the LLM-provided session IDs ({llm_provided_session_ids}) "
                    f"for the source ({llm_provided_session_ids_source}): {llm_provided_input}"
                ),
                signals_type="session-summaries",
            )
            return "No sessions were found matching the specified criteria.", None
        # We have session IDs - start tracking
        summary_type: Literal["single", "group"] = (
            "single" if len(session_ids) <= GROUP_SUMMARIES_MIN_SESSIONS else "group"
        )
        video_validation_enabled = self._has_video_validation_feature_flag()
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
            # Summarize the sessions
            summaries_content, session_group_summary_id = await self._summarize_sessions(
                session_ids=session_ids,
                summary_title=summary_title,
                session_ids_source=llm_provided_session_ids_source,
            )
            # Build messages artifact for group summaries (with "Open report" button)
            content, artifact = None, None
            if session_group_summary_id:
                messages = [
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
                        content=f"Report complete: {summary_title or 'Sessions summary'}",
                        id=str(uuid4()),
                    ),
                    AssistantToolCallMessage(
                        content=summaries_content,
                        tool_call_id=self._state.root_tool_call_id or "unknown",
                        id=str(uuid4()),
                    ),
                ]
                # Providing string to avoid feeding the context twice, as AssistantToolCallMessage is required for proper rendering of the report button
                content, artifact = "Sessions summarized successfully", ToolMessagesArtifact(messages=messages)
            else:
                content, artifact = summaries_content, None
        except Exception as err:
            # The session summarization failed
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
            raise
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
        return content, artifact

    def _has_video_validation_feature_flag(self) -> bool | None:
        """
        Check if the user has the video validation for session summaries feature flag enabled.
        """
        return posthoganalytics.feature_enabled(
            "max-session-summarization-video-validation",
            str(self._user.distinct_id),
            groups={"organization": str(self._team.organization_id)},
            group_properties={"organization": {"id": str(self._team.organization_id)}},
            send_feature_flag_events=False,
        )

    def _stream_progress(self, progress_message: str) -> None:
        """Push summarization progress as reasoning messages"""
        content = prepare_reasoning_progress_message(progress_message)
        if content:
            self.dispatcher.update(content)

    def _get_session_ids_with_filters(self, replay_filters: RecordingsQuery) -> list[str] | None:
        """Get session ids from DB with filters"""
        from posthog.session_recordings.queries.session_recording_list_from_query import SessionRecordingListFromQuery

        # Execute the query to get session IDs
        try:
            query_runner = SessionRecordingListFromQuery(
                team=self._team, query=replay_filters, hogql_query_modifiers=None
            )
            results = query_runner.run()
        except Exception as e:
            logger.exception(
                f"Error getting session ids for session summarization with filters query "
                f"({replay_filters.model_dump_json(exclude_none=True)}): {e}",
                signals_type="session-summaries",
            )
            return None
        # Extract session IDs
        session_ids = [recording["session_id"] for recording in results.results]
        return session_ids if session_ids else None

    async def _summarize_sessions_individually(self, session_ids: list[str]) -> str:
        """Summarize sessions individually with progress updates."""
        total = len(session_ids)
        completed = 0
        video_validation_enabled = self._has_video_validation_feature_flag()

        async def _summarize(session_id: str) -> dict[str, Any]:
            nonlocal completed
            result = await execute_summarize_session(
                session_id=session_id,
                user=self._user,
                team=self._team,
                model_to_use=SESSION_SUMMARIES_SYNC_MODEL,
                video_validation_enabled=video_validation_enabled,
            )
            completed += 1
            # Update the user on the progress
            self._stream_progress(progress_message=f"Watching sessions ({completed}/{total})")
            return result

        # Run all tasks concurrently
        tasks = [_summarize(sid) for sid in session_ids]
        summaries = await asyncio.gather(*tasks)
        self._stream_progress(progress_message=f"Generating a summary, almost there")
        # Stringify, as chat doesn't need full JSON to be context-aware, while providing it could overload the context
        stringified_summaries = []
        for summary in summaries:
            stringifier = SingleSessionSummaryStringifier(summary)
            stringified_summaries.append(stringifier.stringify_session())
        # Combine all stringified summaries into a single string
        summaries_str = "\n\n".join(stringified_summaries)
        return summaries_str

    async def _summarize_sessions_as_group(
        self,
        session_ids: list[str],
        summary_title: str | None,
    ) -> tuple[str, str]:
        """Summarize sessions as a group (for larger sets). Returns tuple of (summary_str, session_group_summary_id)."""
        from ee.hogai.session_summaries.utils import logging_session_ids

        min_timestamp, max_timestamp = await database_sync_to_async(find_sessions_timestamps, thread_sensitive=False)(
            session_ids=session_ids, team=self._team
        )
        # Check if the summaries should be validated with videos
        video_validation_enabled = self._has_video_validation_feature_flag()
        async for update_type, data in execute_summarize_session_group(
            session_ids=session_ids,
            user=self._user,
            team=self._team,
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
                    logger.error(msg, signals_type="session-summaries")
                    raise TypeError(msg)
                # Status message - stream to user
                self._stream_progress(progress_message=data)
            # Final summary result
            elif update_type == SessionSummaryStreamUpdate.FINAL_RESULT:
                if not isinstance(data, tuple) or len(data) != 2:
                    msg = (
                        f"Unexpected data type for stream update {SessionSummaryStreamUpdate.FINAL_RESULT}: {type(data)} "
                        f"(expected: tuple[EnrichedSessionGroupSummaryPatternsList, str])"
                    )
                    logger.error(msg, signals_type="session-summaries")
                    raise ValueError(msg)
                summary, session_group_summary_id = data
                if not isinstance(summary, EnrichedSessionGroupSummaryPatternsList):
                    msg = (  # type: ignore[unreachable]
                        f"Unexpected data type for patterns in stream update {SessionSummaryStreamUpdate.FINAL_RESULT}: {type(summary)} "
                        f"(expected: EnrichedSessionGroupSummaryPatternsList)"
                    )
                    logger.error(msg, signals_type="session-summaries")
                    raise ValueError(msg)
                # Stringify the summary to "weight" less and apply example limits per pattern, so it won't overload the context
                stringifier = SessionGroupSummaryStringifier(summary.model_dump(exclude_none=False))
                summary_str = stringifier.stringify_patterns()
                return summary_str, session_group_summary_id
            else:
                msg = f"Unexpected update type ({update_type}) in session group summarization (session_ids: {logging_session_ids(session_ids)})."  # type: ignore[unreachable]
                logger.error(msg, signals_type="session-summaries")
                raise ValueError(msg)
        else:
            msg = f"No summary was generated from session group summarization (session_ids: {logging_session_ids(session_ids)})"
            logger.error(msg, signals_type="session-summaries")
            raise ValueError(msg)

    async def _summarize_sessions(
        self, session_ids: list[str], summary_title: str | None, *, session_ids_source: Literal["filters", "explicit"]
    ) -> tuple[str, str | None]:
        """
        Summarize sessions. Returns tuple of (summary_str, session_group_summary_id).
        session_group_summary_id is None for individual summaries, as report is not generated.
        """
        # Process sessions based on count
        base_message = f"Found {pluralize(len(session_ids), 'session')} based on {'filters' if session_ids_source == 'filters' else 'explicit session IDs'}."
        if len(session_ids) <= GROUP_SUMMARIES_MIN_SESSIONS:
            # If small amount of sessions - there are no patterns to extract, so summarize them individually and return as is
            self._stream_progress(
                progress_message=f"{base_message} We will do a quick summary, as the scope is small",
            )
            summaries_content = await self._summarize_sessions_individually(session_ids=session_ids)
            return summaries_content, None
        # For large groups, process in detail, searching for patterns
        self._stream_progress(
            progress_message=f"{base_message} We will analyze in detail, and store the report",
        )
        summaries_content, session_group_summary_id = await self._summarize_sessions_as_group(
            session_ids=session_ids,
            summary_title=summary_title,
        )
        return summaries_content, session_group_summary_id

    def _validate_specific_session_ids(self, session_ids: list[str]) -> list[str] | None:
        """Validate that specific session IDs exist in the database."""
        from posthog.session_recordings.queries.session_replay_events import SessionReplayEvents

        replay_events = SessionReplayEvents()
        sessions_found, _, _ = replay_events.sessions_found_with_timestamps(
            session_ids=session_ids,
            team=self._team,
        )
        if not sessions_found:
            return None
        # Preserve the original order, filtering out invalid sessions
        return [sid for sid in session_ids if sid in sessions_found]
