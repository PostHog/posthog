from textwrap import dedent
from typing import Any, Literal

import structlog
from pydantic import BaseModel, Field

from posthog.schema import MaxRecordingUniversalFilters, RecordingsQuery

from posthog.sync import database_sync_to_async

from products.replay.backend.prompts import (
    DATE_FIELDS_PROMPT,
    FILTER_FIELDS_TAXONOMY_PROMPT,
    PRODUCT_DESCRIPTION_PROMPT,
    SESSION_REPLAY_EXAMPLES_PROMPT,
)

from ee.hogai.tool import MaxTool, ToolMessagesArtifact
from ee.hogai.tools.replay.summarize_sessions import SummarizeSessionsTool

logger = structlog.get_logger(__name__)


class FilterSessionRecordingsToolArgs(BaseModel):
    recordings_filters: MaxRecordingUniversalFilters = Field(
        description=dedent(f"""
        User's question converted into a recordings query.

        **CRITICAL: You MUST use the read_taxonomy tool to discover and clarify ALL properties and events before creating filters.**

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

        **Session**: `$device_type` (Mobile/Desktop/Tablet), `$browser`, `$os`, `$screen_width`, `$screen_height`
        **Person**: `$geoip_country_code` (US/UK/FR), `$geoip_city_name`, custom fields
        **Event**: `$current_url`, `$event_type` ($rageclick/$pageview), `$pathname`
        **Recording**: `console_error_count`, `click_count`, `keypress_count`, `mouse_activity_count`, `activity_score`

        # Filter Completion Strategy

        Always aim to complete filters as much as possible:
        - **FIRST**: Use read_taxonomy to discover ALL relevant properties and events
        - If you found most properties but are missing some, return what you have (user can refine later)
        - If you've found very few properties, use read_taxonomy again or ask for clarification
        - Don't get stuck on perfect matches - use reasonable approximations when appropriate
        - **Remember**: Property discovery with read_taxonomy is MANDATORY before filter creation

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
        Filters session recordings by creating a recordings query, and then running it to list the recordings. The list is AUTOMATICALLY shown to the user as a widget.
        - When to use the tool:
        * When the user asks to update session recordings filters
            - "update" synonyms: "change", "modify", "adjust", and similar
            - "session recordings" synonyms: "sessions", "recordings", "replays", "user sessions", and similar
        * When the user asks to search for session recordings
            - "search for" synonyms: "find", "look up", and similar
        * When the user asks to summarize session recordings

        When on the replay page, the tool will update the filters in the page.
        """).strip()

    async def _arun_impl(
        self, recordings_filters: MaxRecordingUniversalFilters
    ) -> tuple[str, ToolMessagesArtifact | None]:
        # Convert filters to recordings query and execute
        recordings_query = SummarizeSessionsTool._convert_max_filters_to_recordings_query(recordings_filters)

        try:
            query_results = await database_sync_to_async(self._get_recordings_with_filters, thread_sensitive=False)(
                recordings_query
            )
        except:
            query_results = None

        if query_results is None:
            content = "⚠️ Updated session recordings filters, but encountered an issue fetching results."
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

    def _get_recordings_with_filters(self, recordings_query: RecordingsQuery, limit: int = 50) -> Any:
        """Get recordings from DB with filters"""
        from posthog.session_recordings.queries.session_recording_list_from_query import SessionRecordingListFromQuery

        recordings_query.limit = limit
        try:
            query_runner = SessionRecordingListFromQuery(
                team=self._team, query=recordings_query, hogql_query_modifiers=None, limit=limit
            )
            results = query_runner.run()
        except Exception as e:
            logger.exception(
                f"Error getting recordings with filters query ({recordings_query.model_dump_json(exclude_none=True)}): {e}"
            )
            return None
        return results

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
