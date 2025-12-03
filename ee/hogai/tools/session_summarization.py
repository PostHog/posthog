from typing import Literal

from langchain_core.runnables import RunnableLambda
from pydantic import BaseModel, Field

from ee.hogai.chat_agent.session_summaries.nodes import SessionSummarizationNode
from ee.hogai.tool import MaxTool, ToolMessagesArtifact
from ee.hogai.tool_errors import MaxToolFatalError
from ee.hogai.utils.types.base import AssistantState, PartialAssistantState

SESSION_SUMMARIZATION_TOOL_PROMPT = """
Use this tool to summarize session recordings by analysing the events within those sessions to find patterns and issues.
It will return a textual summary of the captured session recordings.

# When to use the tool:
When the user asks to summarize session recordings:
- "summarize" synonyms: "watch", "analyze", "review", and similar
- "session recordings" synonyms: "sessions", "recordings", "replays", "user sessions", and similar

# When NOT to use the tool:
- When the user asks to find, search for, or look up session recordings, but doesn't ask to summarize them
- When users asks to update, change, or adjust session recordings filters

# Synonyms
- "summarize": "watch", "analyze", "review", and similar
- "session recordings": "sessions", "recordings", "replays", "user sessions", and similar

# Managing context
If the conversation history contains context about the current filters or session recordings, follow these steps:
- Convert the user query into a `session_summarization_query`
- The query should be used to understand the user's intent
- Check if the user provides specific session IDs or refers to the current session and populate `specific_session_ids_to_summarize` accordingly
- Decide if the query is relevant to the current filters and set `should_use_current_filters` accordingly
- Generate the `summary_title` based on the user's query and the current filters

Otherwise:
- Convert the user query into a `session_summarization_query`
- The query should be used to search for relevant sessions and then summarize them
- Check if the user provides specific session IDs and populate `specific_session_ids_to_summarize` accordingly
- Assume the `should_use_current_filters` should be always `false`
- Assume the `specific_session_ids_to_summarize` should be always empty list
- Generate the `summary_title` based on the user's query

# Additional guidelines
- CRITICAL: Always pass the user's complete, unmodified query to the `session_summarization_query` parameter
- DO NOT truncate, summarize, or extract keywords from the user's query
- The query is used to find relevant sessions - context helps find better matches
- Use explicit tool definition to make a decision
- IMPORTANT: `should_use_current_filters` and `specific_session_ids_to_summarize` are mutually exclusive - only one can be set at a time:
  * If the user provides specific session IDs or refers to a specific session (e.g., "this session", "session abc-123", "sessions abc-123 and def-456") → populate `specific_session_ids_to_summarize` and set `should_use_current_filters=false`
  * If the user refers to multiple sessions or wants to use filters without specifying IDs (e.g., "these sessions", "all sessions", "sessions from yesterday") → set `should_use_current_filters` appropriately and keep `specific_session_ids_to_summarize` empty
""".strip()


class SessionSummarizationToolArgs(BaseModel):
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
    specific_session_ids_to_summarize: list[str] = Field(
        default_factory=list,
        description="""
        - List of specific session IDs (UUIDs) to summarize.
        - Should be populated when the user provides specific session IDs or refers to the current session they are viewing.
        - IMPORTANT: Should be empty list if the user wants to use filters or search for sessions.
        - Examples:
          * Populate with session IDs if:
            - The user provides explicit session IDs in their query (e.g., "summarize session 01234567-89ab-cdef-0123-456789abcdef")
            - The user provides multiple session IDs (e.g., "summarize sessions abc-123 and def-456")
            - The user refers to the current session AND `current_session_id` is present in the `search_session_recordings` context (e.g., "this session", "the session", "current session", "session I'm looking at", "session I'm watching")
            - The user combines current session with explicit IDs (e.g., "summarize this session and session abc-123")
          * Set to empty list if:
            - `current_session_id` is not present in the context AND user doesn't provide explicit session IDs
            - The user asks to summarize multiple sessions without specifying IDs (e.g., "these sessions", "all sessions", "sessions from yesterday")
            - The user wants to follow current filters
            - The user specifies search criteria or filters (e.g., "sessions from user X", "mobile sessions")
            - The user asks to find or search for sessions
        """,
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
    name: Literal["session_summarization"] = "session_summarization"
    description: str = SESSION_SUMMARIZATION_TOOL_PROMPT
    context_prompt_template: str = "Summarizes session recordings based on the user's query and current filters"
    args_schema: type[BaseModel] = SessionSummarizationToolArgs
    show_tool_call_message: bool = False

    async def _arun_impl(
        self,
        session_summarization_query: str,
        should_use_current_filters: bool,
        specific_session_ids_to_summarize: list[str],
        summary_title: str,
    ) -> tuple[str, ToolMessagesArtifact | None]:
        node = SessionSummarizationNode(self._team, self._user)
        chain: RunnableLambda[AssistantState, PartialAssistantState | None] = RunnableLambda(node)
        copied_state = self._state.model_copy(
            deep=True,
            update={
                "root_tool_call_id": self.tool_call_id,
                "session_summarization_query": session_summarization_query,
                "should_use_current_filters": should_use_current_filters,
                "specific_session_ids_to_summarize": specific_session_ids_to_summarize,
                "summary_title": summary_title,
            },
        )
        result = await chain.ainvoke(copied_state)
        if not result or not result.messages:
            raise MaxToolFatalError(
                "Session summarization failed: The summarization node did not return any results. "
                "This indicates an internal system error."
            )
        return "", ToolMessagesArtifact(messages=result.messages)
