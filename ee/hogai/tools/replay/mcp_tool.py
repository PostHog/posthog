from typing import Any

import structlog
from pydantic import BaseModel, Field

from posthog.sync import database_sync_to_async
from posthog.temporal.ai.session_summary.summarize_session import execute_summarize_session

from ee.hogai.mcp_tool import MCPTool, mcp_tool_registry
from ee.hogai.session_summaries.constants import SESSION_SUMMARIES_SYNC_MODEL
from ee.hogai.session_summaries.session.stringify import SingleSessionSummaryStringifier
from ee.hogai.tool_errors import MaxToolFatalError, MaxToolRetryableError

logger = structlog.get_logger(__name__)


class SummarizeSessionMCPToolArgs(BaseModel):
    session_id: str = Field(description="The session recording ID to summarize.")


@mcp_tool_registry.register(scopes=["session_recording:read"])
class SummarizeSessionMCPTool(MCPTool[SummarizeSessionMCPToolArgs]):
    """
    MCP tool to summarize a single session recording.

    Returns an LLM-generated summary of what the user did during the session,
    including key actions, segments, issues encountered, and session outcome.
    Uses a cached summary if available, otherwise generates a new one.
    """

    name = "summarize_session"
    args_schema = SummarizeSessionMCPToolArgs

    async def execute(self, args: SummarizeSessionMCPToolArgs) -> str:
        session_id = args.session_id.strip()
        if not session_id:
            raise MaxToolRetryableError("session_id must not be empty.")

        session_exists = await self._check_session_exists(session_id)
        if not session_exists:
            raise MaxToolRetryableError(
                f"No session recording found for session_id '{session_id}'. Verify the ID is correct."
            )

        try:
            summary = await execute_summarize_session(
                session_id=session_id,
                user=self._user,
                team=self._team,
                model_to_use=SESSION_SUMMARIES_SYNC_MODEL,
            )
        except Exception as e:
            logger.exception(
                f"Session summarization failed for session_id {session_id}",
                session_id=session_id,
                team_id=self._team.id,
                signals_type="session-summaries",
            )
            raise MaxToolFatalError(f"Failed to summarize session: {e}") from e

        return self._stringify_summary(summary)

    async def _check_session_exists(self, session_id: str) -> bool:
        @database_sync_to_async(thread_sensitive=False)
        def _check():
            from posthog.session_recordings.queries.session_replay_events import SessionReplayEvents

            return SessionReplayEvents().exists(session_id=session_id, team=self._team)

        return await _check()

    @staticmethod
    def _stringify_summary(summary: dict[str, Any]) -> str:
        stringifier = SingleSessionSummaryStringifier(summary)
        return stringifier.stringify_session()
