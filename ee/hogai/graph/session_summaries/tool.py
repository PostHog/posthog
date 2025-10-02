import structlog
from pydantic import BaseModel, Field

from posthog.schema import AssistantTool, AssistantToolCallMessage

from ee.hogai.graph.session_summaries.nodes import SessionSummarizationNode
from ee.hogai.tool import MaxTool
from ee.hogai.utils.types.base import AssistantState, ToolResult

logger = structlog.get_logger(__name__)


class SessionSummarizationArgs(BaseModel):
    session_summarization_query: str = Field(
        description="""
        - The user's complete query for session recordings summarization.
        - This will be used to find relevant session recordings.
        - Always pass the user's complete, unmodified query.
        - Examples:
          * 'summarize all session recordings from yesterday'
          * 'analyze mobile user session recordings from last week, even if 1 second'
          * 'watch last 300 session recordings of MacOS users from US'
          * and similar
        """
    )
    should_use_current_filters: bool = Field(
        description="""
        - Whether to use current filters from user's UI to find relevant session recordings.
        - IMPORTANT: Should be always `false` if the current filters or `search_session_recordings` tool are not present in the conversation history.
        - Examples:
          * Set to `true` if one of the conditions is met:
            - the user wants to summarize "current/selected/opened/my/all/these" session recordings
            - the user wants to use "current/these" filters
            - the user's query specifies filters identical to the current filters
            - if the user's query doesn't specify any filters/conditions
            - the user refers to what they're "looking at" or "viewing"
          * Set to `false` if one of the conditions is met:
            - no current filters or `search_session_recordings` tool are present in the conversation
            - the user specifies date/time period different from the current filters
            - the user specifies conditions (user, device, id, URL, etc.) not present in the current filters
        """,
    )
    summary_title: str = Field(
        description="""
        - The name of the summary that is expected to be generated from the user's `session_summarization_query` and/or `current_filters` (if present).
        - The name should cover in 3-7 words what sessions would be to be summarized in the summary
        - This won't be used for any search of filtering, only to properly label the generated summary.
        - Examples:
          * If `should_use_current_filters` is `false`, then the `summary_title` should be generated based on the `session_summarization_query`:
            - query: "I want to watch all the sessions of user `user@example.com` in the last 30 days no matter how long" -> name: "Sessions of the user user@example.com (last 30 days)"
            - query: "summarize my last 100 session recordings" -> name: "Last 100 sessions"
            - and similar
          * If `should_use_current_filters` is `true`, then the `summary_title` should be generated based on the current filters in the context (if present):
            - filters: "{"key":"$os","value":["Mac OS X"],"operator":"exact","type":"event"}" -> name: "MacOS users"
            - filters: "{"date_from": "-7d", "filter_test_accounts": True}" -> name: "All sessions (last 7 days)"
            - and similar
          * If there's not enough context to generated the summary name - keep it an empty string ("")
        """
    )


class SessionSummarizationTool(MaxTool):
    name = AssistantTool.SESSION_SUMMARIZATION.value
    description = """
    - Summarize session recordings to find patterns and issues by summarizing sessions' events.
    - When to use the tool:
      * When the user asks to summarize session recordings
        - "summarize" synonyms: "watch", "analyze", "review", and similar
        - "session recordings" synonyms: "sessions", "recordings", "replays", "user sessions", and similar
    - When NOT to use the tool:
      * When the user asks to find, search for, or look up session recordings, but doesn't ask to summarize them
      * When users asks to update, change, or adjust session recordings filters
    """
    args_schema = SessionSummarizationArgs

    async def _arun_impl(
        self, session_summarization_query: str, should_use_current_filters: bool, summary_title: str
    ) -> ToolResult:
        state = AssistantState(
            root_tool_call_id=self._tool_call_id,
            session_summarization_query=session_summarization_query,
            should_use_current_filters=should_use_current_filters,
            summary_title=summary_title,
        )

        node = SessionSummarizationNode(team=self._team, user=self._user)
        result = await node.arun(state, self._config)
        if not result or not result.messages:
            logger.warning("Task failed: no messages received from node executor", tool_call_id=self._tool_call_id)
            return await self._failed_execution()
        last_message = result.messages[-1]
        if not isinstance(last_message, AssistantToolCallMessage):
            logger.warning("Task failed: last message is not AssistantToolCallMessage", tool_call_id=self._tool_call_id)
            return await self._failed_execution()

        return await self._successful_execution(last_message.content, [])
