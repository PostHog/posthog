from datetime import datetime
from textwrap import dedent
from typing import Literal

import structlog
from pydantic import BaseModel, Field

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.session_recordings.queries.session_replay_events import SessionReplayEvents
from posthog.sync import database_sync_to_async

from ee.hogai.tool import MaxTool, ToolMessagesArtifact

logger = structlog.get_logger(__name__)


class GetSessionRecordingToolArgs(BaseModel):
    session_id: str = Field(
        description=dedent(
            """
            The session ID (also known as `$session_id`) of the recording to look up.

            Sources for this value:
            - The current recording the user is viewing (provided in tool context as `current_session_id`).
            - A session ID the user pasted into the conversation.
            - A session ID surfaced by a previous tool call such as `filter_session_recordings`.

            Do not invent session IDs. If you do not have one, ask the user or call
            `filter_session_recordings` first.
            """
        ).strip()
    )


class GetSessionRecordingTool(MaxTool):
    name: Literal["get_session_recording"] = "get_session_recording"
    description: str = dedent(
        """
        Look up metadata for a single session recording by its session ID.

        Use this when the user asks for details about a specific recording — for example
        "what is the distinct_id for this recording?", "when did this session start?",
        "how long was this session?", or "who was this user?".

        The tool returns the recording's distinct_id, start and end timestamps, duration,
        click/keypress/console-error counts, first URL, and snapshot source. It does NOT
        return the recording's events or a summary — use `summarize_sessions` for that.
        """
    ).strip()
    args_schema: type[BaseModel] = GetSessionRecordingToolArgs
    context_prompt_template: str = "Current session ID being viewed: {{{current_session_id}}}."

    def get_required_resource_access(self):
        return [("session_recording", "viewer")]

    async def _arun_impl(self, session_id: str) -> tuple[str, ToolMessagesArtifact | None]:
        session_id = (session_id or "").strip()
        if not session_id:
            return "⚠️ No session ID was provided.", None

        try:
            metadata = await database_sync_to_async(self._get_metadata, thread_sensitive=False)(session_id)
        except Exception as e:
            logger.exception(
                f"get_session_recording failed for session {session_id}: {e}",
                signals_type="get-session-recording",
            )
            return f"⚠️ Failed to fetch metadata for session {session_id}: {e}", None

        if metadata is None:
            return (
                f"No recording was found for session_id `{session_id}`. "
                "It may have expired, been deleted, or never been ingested.",
                None,
            )

        return self._format_metadata(session_id, metadata), None

    def _get_metadata(self, session_id: str) -> dict | None:
        with tags_context(
            product=Product.MAX_AI,
            feature=Feature.POSTHOG_AI,
            team_id=self._team.pk,
            org_id=self._team.organization_id,
        ):
            metadata = SessionReplayEvents().get_metadata(session_id=session_id, team=self._team)
        if metadata is None:
            return None
        return dict(metadata)

    @staticmethod
    def _format_timestamp(value: datetime | str | None) -> str | None:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value.strftime("%Y-%m-%d %H:%M:%S UTC")
        return str(value)

    @staticmethod
    def _format_duration(duration: int | float | None) -> str | None:
        if duration is None:
            return None
        total_seconds = int(duration)
        if total_seconds < 0:
            return None
        minutes, seconds = divmod(total_seconds, 60)
        hours, minutes = divmod(minutes, 60)
        if hours > 0:
            return f"{hours}h {minutes}m {seconds}s"
        if minutes > 0:
            return f"{minutes}m {seconds}s"
        return f"{seconds}s"

    @classmethod
    def _format_metadata(cls, session_id: str, metadata: dict) -> str:
        lines = [f"Session `{session_id}`:"]

        distinct_id = metadata.get("distinct_id")
        lines.append(f"- distinct_id: {distinct_id}" if distinct_id else "- distinct_id: (unknown)")

        start = cls._format_timestamp(metadata.get("start_time"))
        if start:
            lines.append(f"- start_time: {start}")
        end = cls._format_timestamp(metadata.get("end_time"))
        if end:
            lines.append(f"- end_time: {end}")
        duration = cls._format_duration(metadata.get("duration"))
        if duration:
            lines.append(f"- duration: {duration}")

        active_seconds = metadata.get("active_seconds")
        if active_seconds is not None:
            lines.append(f"- active_seconds: {int(active_seconds)}")

        click_count = metadata.get("click_count")
        keypress_count = metadata.get("keypress_count")
        console_error_count = metadata.get("console_error_count")
        if click_count is not None:
            lines.append(f"- click_count: {click_count}")
        if keypress_count is not None:
            lines.append(f"- keypress_count: {keypress_count}")
        if console_error_count is not None:
            lines.append(f"- console_error_count: {console_error_count}")

        first_url = metadata.get("first_url")
        if first_url:
            lines.append(f"- first_url: {first_url}")

        snapshot_source = metadata.get("snapshot_source")
        if snapshot_source:
            lines.append(f"- snapshot_source: {snapshot_source}")

        recording_ttl = metadata.get("recording_ttl")
        if recording_ttl is not None:
            lines.append(f"- recording_ttl_days: {recording_ttl}")

        return "\n".join(lines)
