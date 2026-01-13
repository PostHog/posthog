from textwrap import dedent
from typing import Any, Literal

import structlog
from posthoganalytics import capture_exception
from pydantic import BaseModel, Field

from posthog.schema import MaxRecordingUniversalFilters, RecordingsQuery

from posthog.session_recordings.playlist_counters import convert_filters_to_recordings_query
from posthog.session_recordings.queries.session_recording_list_from_query import SessionRecordingListFromQuery
from posthog.session_recordings.queries.utils import SessionRecordingQueryResult
from posthog.sync import database_sync_to_async

from products.replay.backend.prompts import (
    DATE_FIELDS_PROMPT,
    FILTER_EXAMPLES_PROMPT,
    FILTER_FIELDS_TAXONOMY_PROMPT,
    PRODUCT_DESCRIPTION_PROMPT,
    SESSION_REPLAY_EXAMPLES_PROMPT,
)

from ee.hogai.tool import MaxTool, ToolMessagesArtifact

logger = structlog.get_logger(__name__)


class FilterSessionRecordingsToolArgs(BaseModel):
    recordings_filters: MaxRecordingUniversalFilters = Field(
        description=dedent(f"""
        User's question converted into a recordings query.

        {PRODUCT_DESCRIPTION_PROMPT}

        {SESSION_REPLAY_EXAMPLES_PROMPT}

        {FILTER_FIELDS_TAXONOMY_PROMPT}

        {DATE_FIELDS_PROMPT}

        # Property Types and Discovery

        A session recording contains events and entities. When filtering, you must understand which property type to use:

        **ENTITY PROPERTIES** (person, session, group):
        - **Person properties**: User attributes (email, name, country, custom fields). **MUST use read_taxonomy to discover available person properties.**
        - **Session properties**: Session-level data (device type, browser, OS, screen size, start timestamp). **MUST use read_taxonomy to discover available session properties.**
        - **Group properties**: Organization/account attributes (plan tier, company name). **MUST use read_taxonomy to discover group properties for specific group types.** The defined group types are: {{{{#groups}}}} {{{{.}}}}s,{{{{/groups}}}}.

        **EVENT PROPERTIES**:
        - Properties of specific events that occurred during the recording (e.g., URL visited, button clicked). **MUST use read_taxonomy to discover properties for specific event names.**

        **RECORDING PROPERTIES**:
        - Recording-level metrics (console_error_count, click_count, activity_score). These are built-in and don't require discovery.

        **CRITICAL**: ALWAYS use read_taxonomy to discover properties before creating filters. Never assume property names or values exist without verification. If you can't find an exact property match, try the next best match. Do not call the same tool twice for the same entity/event.

        # Property Value Matching

        When using discovered property values:
        - **Related but not synonyms**: Use the user's original value. Example: User asks for browser "Chrome", tool returns ["Firefox", "Safari"] -> use "Chrome" (related concept)
        - **Synonyms or variants**: Use the discovered value. Example: User asks for city "New York", tool returns ["New York City", "NYC"] -> use "New York City" (synonym)

        # Common Properties

        **Event**: `$device_type` (Mobile/Desktop/Tablet), `$browser`, `$os`, `$screen_width`, `$screen_height`, `$current_url`, `$pathname`
        **Session**: `$session_duration`, `$channel_type`, `$entry_current_url`, `$entry_pathname`, `$is_bounce`, `$pageview_count`
        **Person**: `$geoip_country_code` (US/UK/FR), `$geoip_city_name`, custom fields
        **Recording**: `console_error_count`, `click_count`, `keypress_count`, `mouse_activity_count`, `activity_score`

        # Filter Completion Strategy

        Always aim to complete filters as much as possible:
        - **FIRST**: Use read_taxonomy to discover ALL relevant properties and events
        - If you found most properties but are missing some, return what you have (user can refine later)
        - If you've found very few properties, use read_taxonomy again or ask for clarification
        - Don't get stuck on perfect matches - use reasonable approximations when appropriate
        - **Remember**: Property discovery with read_taxonomy is MANDATORY before filter creation

        # Filter Structure

        ## filter_group (REQUIRED)
        Two-level nested structure with AND/OR logic.
        **Empty filter** (all recordings):
        ```json
        {{"type":"AND","values":[{{"type":"AND","values":[]}}]}}
        ```

        ## duration (REQUIRED)
        Array of duration constraints. Default to `[]` unless user asks about recording length.
        Duration types: "duration", "active_seconds", "inactive_seconds"
        Example (longer than 5 minutes):
        ```json
        {{"duration":[{{"key":"duration","type":"recording","operator":"gt","value":300}}]}}
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


        {FILTER_EXAMPLES_PROMPT}

        # Critical Reminders

        1. **Property discovery**: ALWAYS use read_taxonomy to discover ALL properties and events before creating filters - never assume they exist
        2. **Don't repeat tool calls**: If a property isn't found, try the next best option
        3. **Minimalism**: Only include essential filters
        4. **Defaults**: date_from="-3d", duration=[], filter_test_accounts=true
        5. **Duration placement**: Duration filters go in `duration` array, NOT filter_group
        6. **Value types**: Arrays for "exact"/"is_not", single values for comparisons
        7. **Output format**: Valid JSON object only, no markdown or explanatory text
        8. **Silence**: Do not output when performing taxonomy exploration, just use the tools
        """).strip()
    )


class FilterSessionRecordingsTool(MaxTool):
    name: Literal["filter_session_recordings"] = "filter_session_recordings"
    args_schema: type[BaseModel] = FilterSessionRecordingsToolArgs
    description: str = dedent("""
        Use this tool to retrieve a list of filtered session recordings by creating a recordings query. The list is shown to the user as a widget.
        # When to use the tool:
        - The user asks to update session recordings filters
          - "update" synonyms: "change", "modify", "adjust", and similar
          - "session recordings" synonyms: "sessions", "recordings", "replays", "user sessions", and similar
        - The user asks to search for session recordings
          - "search for" synonyms: "find", "look up", and similar
        - The user asks to summarize session recordings

        When on the replay page, the tool will update the filters in the page.
        """).strip()
    context_prompt_template: str = "Current recordings filters are: {{{current_filters}}}.\nCurrent session ID being viewed: {{{current_session_id}}}."

    def get_required_resource_access(self):
        return [("session_recording", "viewer")]

    async def _arun_impl(
        self, recordings_filters: MaxRecordingUniversalFilters
    ) -> tuple[str, ToolMessagesArtifact | None]:
        # Convert filters to recordings query and execute
        recordings_query = convert_filters_to_recordings_query(recordings_filters.model_dump(exclude_none=True))

        try:
            query_results = await database_sync_to_async(self._get_recordings_with_filters, thread_sensitive=False)(
                recordings_query
            )
        except Exception as e:
            capture_exception(e)
            content = f"⚠️ Updated session recordings filters, but encountered an issue fetching results: {e}"
        else:
            total_count = len(query_results.results)
            if total_count == 0:
                content = "✅ Filtered session recordings. No recordings found matching these criteria."
            elif total_count == 1:
                content = "✅ Filtered session recordings. Found 1 recording matching these criteria:\n\n"
                content += self._format_recording_metadata(query_results.results[0])
            else:
                content = f"✅ Filtered session recordings. Found {total_count} recordings matching these criteria:\n\n"
                # Include metadata for up to first 5 recordings
                for i, recording in enumerate(query_results.results[:5]):
                    content += f"{i+1}. {self._format_recording_metadata(recording)}\n"
                if total_count > 5:
                    content += f"\n...and {total_count - 5} more recordings"
        return content, None

    def _get_recordings_with_filters(self, recordings_query: RecordingsQuery) -> SessionRecordingQueryResult:
        """Get recordings from DB with filters"""
        query_runner = SessionRecordingListFromQuery(
            team=self._team, query=recordings_query, hogql_query_modifiers=None
        )
        return query_runner.run()

    def _format_recording_metadata(self, recording: dict[str, Any]) -> str:
        """Format recording metadata for display."""
        from datetime import datetime

        parts = []

        # Person/distinct_id
        distinct_id = recording.get("distinct_id", "Unknown")
        parts.append(f"User: {distinct_id}")

        # Start time
        start_time = recording.get("start_time")
        if start_time:
            try:
                # start_time can be either a datetime object (from ClickHouse) or a string
                if isinstance(start_time, datetime):
                    dt = start_time
                else:
                    dt = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
                parts.append(f"Started: {dt.strftime('%Y-%m-%d %H:%M:%S UTC')}")
            except (ValueError, AttributeError):
                parts.append(f"Started: {start_time}")

        # Duration
        duration = recording.get("duration")
        if duration is not None:
            minutes, seconds = divmod(int(duration), 60)
            hours, minutes = divmod(minutes, 60)
            if hours > 0:
                parts.append(f"Duration: {hours}h {minutes}m {seconds}s")
            elif minutes > 0:
                parts.append(f"Duration: {minutes}m {seconds}s")
            else:
                parts.append(f"Duration: {seconds}s")

        # Activity metrics
        click_count = recording.get("click_count")
        keypress_count = recording.get("keypress_count")
        if click_count is not None or keypress_count is not None:
            activity_parts = []
            if click_count is not None:
                activity_parts.append(f"{click_count} clicks")
            if keypress_count is not None:
                activity_parts.append(f"{keypress_count} keypresses")
            parts.append(f"Activity: {', '.join(activity_parts)}")

        # Console errors
        console_error_count = recording.get("console_error_count")
        if console_error_count is not None and console_error_count > 0:
            parts.append(f"Console errors: {console_error_count}")

        # Active/inactive seconds
        active_seconds = recording.get("active_seconds")
        inactive_seconds = recording.get("inactive_seconds")
        if active_seconds is not None:
            parts.append(f"Active: {int(active_seconds)}s")
        if inactive_seconds is not None:
            parts.append(f"Inactive: {int(inactive_seconds)}s")

        # First URL
        first_url = recording.get("first_url")
        if first_url:
            parts.append(f"First URL: {first_url}")

        # Ongoing status
        ongoing = recording.get("ongoing")
        if ongoing:
            parts.append("Status: Ongoing")

        return " | ".join(parts)
