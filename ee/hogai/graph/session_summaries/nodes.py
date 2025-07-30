from typing import Any, Literal, cast
from uuid import uuid4
import time
from langchain_core.runnables import RunnableConfig
import structlog
from asgiref.sync import async_to_sync
from ee.hogai.utils.types import AssistantState, PartialAssistantState
from posthog.schema import AssistantToolCallMessage, MaxRecordingUniversalFilters
from ee.hogai.graph.base import AssistantNode
from products.replay.backend.max_tools import (
    MULTIPLE_FILTERS_PROMPT,
    PRODUCT_DESCRIPTION_PROMPT,
    SESSION_REPLAY_EXAMPLES_PROMPT,
    SESSION_REPLAY_RESPONSE_FORMATS_PROMPT,
)
from ee.hogai.graph.filter_options.graph import FilterOptionsGraph
from posthog.schema import RecordingsQuery
from posthog.session_recordings.queries_to_replace.session_recording_list_from_query import (
    SessionRecordingListFromQuery,
)


class SessionSummarizationNode(AssistantNode):
    logger = structlog.get_logger(__name__)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    async def _generate_replay_filters(self, plain_text_query: str) -> MaxRecordingUniversalFilters | None:
        """Generates replay filters to get session ids by querying a compiled Universal filters graph."""
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
        # Extract the generated filters
        filters_data = result.get("generated_filter_options", {}).get("data", None)
        if not filters_data:
            return None
        max_filters = cast(MaxRecordingUniversalFilters, filters_data)
        return max_filters

    def _get_session_ids_with_filters(self, replay_filters: MaxRecordingUniversalFilters) -> list[str] | None:
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

    def run(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState | None:
        start_time = time.time()
        conversation_id = config.get("configurable", {}).get("thread_id", "unknown")
        # If query was not provided for some reason
        if not state.session_summarization_query:
            self._log_failure(
                f"Session summarization query is not provided: {state.session_summarization_query}",
                conversation_id, start_time
            )
            return self._create_error_response(self._base_error_message, state.root_tool_call_id)
        try:
            # Generate filters to get session ids from DB
            replay_filters = async_to_sync(self._generate_replay_filters)(state.session_summarization_query)
            if not replay_filters:
                self._log_failure(
                    f"No Replay filters were generated for session summarization: {state.session_summarization_query}",
                    conversation_id, start_time
                )
                return self._create_error_response(self._base_error_message, state.root_tool_call_id)
            # Query the filters to get session ids
            session_ids = self._get_session_ids_with_filters(replay_filters)
            if not session_ids:
                self._log_failure(
                    f"No session ids found for the provided filters: {replay_filters}",
                    conversation_id, start_time
                )
                return self._create_error_response(self._base_error_message, state.root_tool_call_id)
            # TODO: Replace with actual session summarization
            return PartialAssistantState(
                messages=[
                    AssistantToolCallMessage(
                        content=f"In the session with id {session_id} I found the following insights: User tried to sign up, but encountered lots of API errors, so abandoned the flow.",
                        tool_call_id=state.root_tool_call_id or "unknown",
                        id=str(uuid4()),
                    ),
                ],
                summarization_session_id=None,
                root_tool_call_id=None,
            )
        except Exception as e:
            execution_time = time.time() - start_time
            self.logger.exception(
                f"Session summarization failed",
                extra={
                    "team_id": getattr(self._team, "id", "unknown"),
                    "conversation_id": conversation_id,
                    "session_id": session_id,
                    "execution_time_ms": round(execution_time * 1000, 2),
                    "error": str(e),
                },
            )
            return self._create_error_response(
                "INSTRUCTIONS: Tell the user that you encountered an issue while summarizing the session and suggest they try again with a different session id.",
                state.root_tool_call_id,
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
    def _base_error_message(self) -> str:
        return "INSTRUCTIONS: Tell the user that you encountered an issue while summarizing the session and suggest they try again with a different question."

    def router(self, _: AssistantState) -> Literal["end", "root"]:
        return "root"
