import asyncio
from typing import Any, Literal, Self
from uuid import uuid4

import structlog
import posthoganalytics
from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, Field

from posthog.schema import AssistantMessage, AssistantToolCallMessage, MaxRecordingUniversalFilters, RecordingsQuery

from posthog.models import Team, User
from posthog.sync import database_sync_to_async
from posthog.temporal.ai.session_summary.summarize_session import execute_summarize_session
from posthog.temporal.ai.session_summary.summarize_session_group import (
    SessionSummaryStreamUpdate,
    execute_summarize_session_group,
)

from ee.hogai.context.context import AssistantContextManager
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
from ee.hogai.utils.prompt import format_prompt_string
from ee.hogai.utils.state import prepare_reasoning_progress_message
from ee.hogai.utils.types.base import AssistantState, NodePath

logger = structlog.get_logger(__name__)


SUMMARIZE_SESSIONS_TOOL_PROMPT = """
Use this tool to convert a natural language request into session replay filters. You will generate a MaxRecordingUniversalFilters object to find relevant recordings for summarization.

**Guidelines:**
- Be minimalist - only include filters essential to answer the user's question
- Use sensible defaults unless explicitly requested otherwise
- Adjust filters rather than accepting subpar results (note: no results is NOT a data issue)

# Property Types and Discovery

A session recording contains events and entities. When filtering, you must understand which property type to use:

**ENTITY PROPERTIES** (person, session, group):
- **Person properties**: User attributes (email, name, country, custom fields). Use tools to discover available person properties.
- **Session properties**: Session-level data (device type, browser, OS, screen size, start timestamp). Use tools to discover available session properties.
- **Group properties**: Organization/account attributes (plan tier, company name). Use tools to discover group properties for specific group types. The defined group types are: {{#groups}} {{.}}s,{{/groups}}.

**EVENT PROPERTIES**:
- Properties of specific events that occurred during the recording (e.g., URL visited, button clicked). Use tools to discover properties for specific event names.

**RECORDING PROPERTIES**:
- Recording-level metrics (console_error_count, click_count, activity_score). These are built-in and don't require discovery.

**CRITICAL**: Use property discovery tools before creating filters. If you can't find an exact property match, try the next best match. Do not call the same tool twice for the same entity/event.

# Property Value Matching

When using discovered property values:
- **Related but not synonyms**: Use the user's original value. Example: User asks for browser "Chrome", tool returns ["Firefox", "Safari"] -> use "Chrome" (related concept)
- **Synonyms or variants**: Use the discovered value. Example: User asks for city "New York", tool returns ["New York City", "NYC"] -> use "New York City" (synonym)

# Filter Structure

## filter_group (REQUIRED)
Two-level nested structure with AND/OR logic.

**Empty filter** (all recordings):
```json
{"type":"AND","values":[{"type":"AND","values":[]}]}
```

## duration (REQUIRED)
Array of duration constraints. Default to `[]` unless user asks about recording length.

Duration types: "duration", "active_seconds", "inactive_seconds"

Example (longer than 5 minutes):
```json
{"duration":[{"key":"duration","type":"recording","operator":"gt","value":300}]}
```

## Date Range
- **date_from**: "-7d" (relative), "2025-01-15" (absolute). Default: "-3d"
- **date_to**: null (current time, default) or "2025-01-20" (absolute)

## Ordering
- **order**: "start_time" (default), "duration", "console_error_count", "activity_score", etc.
- **order_direction**: "DESC" (default), "ASC"

## Test Accounts
- **filter_test_accounts**: true (recommended, exclude test accounts), false/null (include all)

# Operators by Data Type

**String**: "exact", "is_not", "icontains", "not_icontains", "regex", "not_regex", "is_set", "is_not_set"
**Numeric**: "exact", "is_not", "gt", "gte", "lt", "lte", "is_set", "is_not_set"
**DateTime**: "is_date_exact", "is_not", "is_date_before", "is_date_after", "is_set", "is_not_set"
**Boolean**: "exact", "is_not", "is_set", "is_not_set"

Note: "exact" and "is_not" accept arrays of multiple values.

**Operator Selection Tips:**
- Use "icontains" for URLs (handles parameters/query strings)
- Use "exact" for enumerated values (device type, browser, country codes)
- Use "gt"/"lt" for counts and metrics

# Logical Grouping

**AND**: All criteria must match (narrower results). Example: "mobile users from US" -> mobile AND US
**OR**: Any criteria can match (broader results). Example: "users from US or UK" -> US OR UK

**Simple AND** (most common):
```json
{"type":"AND","values":[{"type":"AND","values":[{"key":"$device_type","type":"session","operator":"exact","value":["Mobile"]},{"key":"$geoip_country_code","type":"person","operator":"exact","value":["US"]}]}]}
```

**Simple OR**:
```json
{"type":"OR","values":[{"type":"AND","values":[{"key":"$geoip_country_code","type":"person","operator":"exact","value":["US"]}]},{"type":"AND","values":[{"key":"$geoip_country_code","type":"person","operator":"exact","value":["UK"]}]}]}
```

**Complex (A OR B) AND (C OR D)**:
```json
{"type":"AND","values":[{"type":"OR","values":[{"key":"$device_type","type":"session","operator":"exact","value":["Mobile"]},{"key":"$device_type","type":"session","operator":"exact","value":["Tablet"]}]},{"type":"OR","values":[{"key":"$geoip_country_code","type":"person","operator":"exact","value":["US"]},{"key":"$geoip_country_code","type":"person","operator":"exact","value":["UK"]}]}]}
```

**Complex (A AND B) OR (C AND D)**:
```json
{"type":"OR","values":[{"type":"AND","values":[{"key":"$device_type","type":"session","operator":"exact","value":["Mobile"]},{"key":"$geoip_country_code","type":"person","operator":"exact","value":["US"]}]},{"type":"AND","values":[{"key":"$device_type","type":"session","operator":"exact","value":["Desktop"]},{"key":"$geoip_country_code","type":"person","operator":"exact","value":["UK"]}]}]}
```

# Common Properties

**Session**: `$device_type` (Mobile/Desktop/Tablet), `$browser`, `$os`, `$screen_width`, `$screen_height`
**Person**: `$geoip_country_code` (US/UK/FR), `$geoip_city_name`, custom fields
**Event**: `$current_url`, `$event_type` ($rageclick/$pageview), `$pathname`
**Recording**: `console_error_count`, `click_count`, `keypress_count`, `mouse_activity_count`, `activity_score`

# Special Patterns

**Frustrated users (rageclicks)**:
```json
{"filter_group":{"type":"AND","values":[{"type":"AND","values":[{"key":"$event_type","type":"event","operator":"exact","value":["$rageclick"]}]}]}}
```

**Users with errors**:
```json
{"filter_group":{"type":"AND","values":[{"type":"AND","values":[{"key":"console_error_count","type":"recording","operator":"gt","value":[0]}]}]},"order":"console_error_count","order_direction":"DESC"}
```

**Clear all filters**:
```json
{"date_from":"-3d","date_to":null,"duration":[],"filter_group":{"type":"AND","values":[{"type":"AND","values":[]}]},"filter_test_accounts":true,"order":"start_time","order_direction":"DESC"}
```

# Complete Examples

**Mobile users from US (last 3 days)**:
```json
{"date_from":"-3d","date_to":null,"duration":[],"filter_group":{"type":"AND","values":[{"type":"AND","values":[{"key":"$device_type","type":"session","operator":"exact","value":["Mobile"]},{"key":"$geoip_country_code","type":"person","operator":"exact","value":["US"]}]}]},"filter_test_accounts":true}
```

**US or UK users (last week)**:
```json
{"date_from":"-7d","date_to":null,"duration":[],"filter_group":{"type":"OR","values":[{"type":"AND","values":[{"key":"$geoip_country_code","type":"person","operator":"exact","value":["US"]}]},{"type":"AND","values":[{"key":"$geoip_country_code","type":"person","operator":"exact","value":["UK"]}]}]},"filter_test_accounts":true}
```

**Long mobile sessions from paid customers on pricing page**:
```json
{"date_from":"-7d","date_to":null,"duration":[{"key":"duration","type":"recording","operator":"gt","value":300}],"filter_group":{"type":"AND","values":[{"type":"AND","values":[{"key":"plan_type","type":"person","operator":"exact","value":["paid"]},{"key":"$device_type","type":"session","operator":"exact","value":["Mobile"]},{"key":"$current_url","type":"event","operator":"icontains","value":["/pricing"]}]}]},"order":"duration","order_direction":"DESC","filter_test_accounts":true}
```

**Error tracking (yesterday)**:
```json
{"date_from":"-1d","date_to":null,"duration":[],"filter_group":{"type":"AND","values":[{"type":"AND","values":[{"key":"console_error_count","type":"recording","operator":"gt","value":[0]}]}]},"order":"console_error_count","order_direction":"DESC","filter_test_accounts":true}
```

**(Mobile OR Tablet) AND (US OR UK)**:
```json
{"date_from":"-3d","date_to":null,"duration":[],"filter_group":{"type":"AND","values":[{"type":"OR","values":[{"key":"$device_type","type":"session","operator":"exact","value":["Mobile"]},{"key":"$device_type","type":"session","operator":"exact","value":["Tablet"]}]},{"type":"OR","values":[{"key":"$geoip_country_code","type":"person","operator":"exact","value":["US"]},{"key":"$geoip_country_code","type":"person","operator":"exact","value":["UK"]}]}]},"filter_test_accounts":true}
```

# Filter Completion Strategy

Always aim to complete filters as much as possible:
- If you found most properties but are missing some, return what you have (user can refine later)
- If you've found very few properties, use property discovery tools or ask for clarification
- Don't get stuck on perfect matches - use reasonable approximations when appropriate

# Critical Reminders

1. **Property discovery**: Use tools to find properties before creating filters
2. **Don't repeat tool calls**: If a property isn't found, try the next best option
3. **Minimalism**: Only include essential filters
4. **Defaults**: date_from="-3d", duration=[], filter_test_accounts=true
5. **Duration placement**: Duration filters go in `duration` array, NOT filter_group
6. **Value types**: Arrays for "exact"/"is_not", single values for comparisons
7. **Output format**: Valid JSON object only, no markdown or explanatory text
""".strip()


class SummarizeSessionsToolArgs(BaseModel):
    search_query: MaxRecordingUniversalFilters = Field(
        description="Converted user's query into a JSON object that will be used to search for relevant session recordings to summarize."
    )
    summary_title: str = Field(
        description="""
        - The name of the summary that is expected to be generated from the user's `search_query`.
        - The name should cover in 3-7 words what sessions would be to be summarized in the summary
        - This won't be used for any search of filtering, only to properly label the generated summary.
        - Examples:
            - filters: "{"key":"$os","value":["Mac OS X"],"operator":"exact","type":"event"}" -> name: "MacOS users"
            - filters: "{"date_from": "-7d", "filter_test_accounts": True}" -> name: "All sessions (last 7 days)"
            - and similar
        * If there's not enough context to generated the summary name - keep it an empty string ("")
        """.strip()
    )
    session_summarization_limit: int = Field(
        description="""
        - The maximum number of sessions to summarize
        - This will be used to apply to DB query to limit the results.
        - Extract the limit from the user's query if present. Set to -1 if not present.
        - IMPORTANT: Extract the limit only if the user's query explicitly mentions a number of sessions to summarize.
        - Examples:
          * 'summarize all sessions from yesterday' -> limit: -1
          * 'summarize last 100 sessions' -> limit: 100
          * 'summarize these sessions' -> limit: -1
          * 'summarize first 10 of these sessions' -> limit: 10
          * 'summarize the sessions of the users with at least 10 events' -> limit: -1
          * 'summarize the sessions of the last 30 days' -> limit: -1
          * 'summarize last 500 sessions of the MacOS users from US' -> limit: 500
          * and similar
        """.strip()
    )


class SummarizeSessionsTool(MaxTool):
    name: Literal["summarize_sessions"] = "summarize_sessions"
    args_schema: type[BaseModel] = SummarizeSessionsToolArgs

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

    @classmethod
    async def create_tool_class(
        cls,
        *,
        team: Team,
        user: User,
        node_path: tuple[NodePath, ...] | None = None,
        state: AssistantState | None = None,
        config: RunnableConfig | None = None,
        context_manager: AssistantContextManager | None = None,
    ) -> Self:
        context_manager = context_manager or AssistantContextManager(team, user, config)
        prompt = format_prompt_string(
            SUMMARIZE_SESSIONS_TOOL_PROMPT,
            groups=await context_manager.get_group_names(),
        )
        return cls(team=team, user=user, state=state, node_path=node_path, config=config, description=prompt)

    async def _arun_impl(
        self, search_query: MaxRecordingUniversalFilters, summary_title: str, session_summarization_limit: int
    ) -> tuple[str, ToolMessagesArtifact | None]:
        # Stream filters to the user at the start
        self._stream_filters(search_query)

        # Convert filters to recordings query
        recordings_query = self._convert_max_filters_to_recordings_query(search_query)

        # Determine query limit
        query_limit = session_summarization_limit
        if not query_limit or query_limit <= 0 or query_limit > MAX_SESSIONS_TO_SUMMARIZE:
            # If no limit provided (none or negative) or too large - use the default limit
            query_limit = MAX_SESSIONS_TO_SUMMARIZE

        # Get session IDs
        session_ids = await database_sync_to_async(self._get_session_ids_with_filters, thread_sensitive=False)(
            recordings_query, query_limit
        )

        # No sessions found
        if not session_ids:
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

    def _convert_max_filters_to_recordings_query(self, replay_filters: MaxRecordingUniversalFilters) -> RecordingsQuery:
        """Convert Max-generated filters into recordings query format"""
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
            # Handle duration filters - preserve the original key (e.g., "active_seconds" or "duration")
            having_predicates=(
                [
                    {"key": dur.key, "type": "recording", "operator": dur.operator, "value": dur.value}
                    for dur in (replay_filters.duration or [])
                ]
                if replay_filters.duration
                else None
            ),
        )
        return recordings_query

    def _get_session_ids_with_filters(self, replay_filters: RecordingsQuery, limit: int) -> list[str] | None:
        """Get session ids from DB with filters"""
        from posthog.session_recordings.queries.session_recording_list_from_query import SessionRecordingListFromQuery

        # Execute the query to get session IDs
        replay_filters.limit = limit
        try:
            query_runner = SessionRecordingListFromQuery(
                team=self._team, query=replay_filters, hogql_query_modifiers=None, limit=limit
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
                user_id=self._user.id,
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

        min_timestamp, max_timestamp = find_sessions_timestamps(session_ids=session_ids, team=self._team)
        # Check if the summaries should be validated with videos
        video_validation_enabled = self._has_video_validation_feature_flag()

        async for update_type, data in execute_summarize_session_group(
            session_ids=session_ids,
            user_id=self._user.id,
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
        self,
        session_ids: list[str],
        summary_title: str | None,
    ) -> tuple[str, str | None]:
        """
        Summarize sessions. Returns tuple of (summary_str, session_group_summary_id).
        session_group_summary_id is None for individual summaries, as report is not generated.
        """
        # Process sessions based on count
        base_message = f"Found sessions ({len(session_ids)})"
        if len(session_ids) <= GROUP_SUMMARIES_MIN_SESSIONS:
            # If small amount of sessions - there are no patterns to extract, so summarize them individually and return as is
            self._stream_progress(
                progress_message=f"{base_message}. We will do a quick summary, as the scope is small",
            )
            summaries_content = await self._summarize_sessions_individually(session_ids=session_ids)
            return summaries_content, None
        # For large groups, process in detail, searching for patterns
        self._stream_progress(
            progress_message=f"{base_message}. We will analyze in detail, and store the report",
        )
        summaries_content, session_group_summary_id = await self._summarize_sessions_as_group(
            session_ids=session_ids,
            summary_title=summary_title,
        )
        return summaries_content, session_group_summary_id
