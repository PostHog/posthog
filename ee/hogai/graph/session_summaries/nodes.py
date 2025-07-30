from typing import Any, Literal
from uuid import uuid4
import time
from langchain_core.runnables import RunnableConfig
import structlog
from asgiref.sync import async_to_sync
from ee.hogai.utils.types import AssistantState, PartialAssistantState
from posthog.schema import AssistantToolCallMessage
from ee.hogai.graph.base import AssistantNode
from products.replay.backend.max_tools import (
    MULTIPLE_FILTERS_PROMPT,
    PRODUCT_DESCRIPTION_PROMPT,
    SESSION_REPLAY_EXAMPLES_PROMPT,
    SESSION_REPLAY_RESPONSE_FORMATS_PROMPT,
)
from ee.hogai.graph.filter_options.graph import FilterOptionsGraph


class SessionSummarizationNode(AssistantNode):
    logger = structlog.get_logger(__name__)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    async def _generate_replay_filters(self) -> dict:
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
                "change": "show me sessions of the user test@posthog.com",
                "current_filters": {},  # Empty state, as we need results from the query-to-filter
            }
        )
        return result

    def _get_session_ids_from_query(self, graph_result: dict[str, Any]) -> list[str]:
        from posthog.schema import RecordingsQuery
        from posthog.session_recordings.queries_to_replace.session_recording_list_from_query import (
            SessionRecordingListFromQuery,
        )

        # Extract the generated filters
        max_filters = graph_result["generated_filter_options"]["data"]  # This is MaxRecordingUniversalFilters

        # Convert MaxRecordingUniversalFilters to RecordingsQuery format
        # The key is to convert filter_group to properties format
        properties = []
        if max_filters.filter_group and max_filters.filter_group.values:
            for inner_group in max_filters.filter_group.values:
                if hasattr(inner_group, "values"):
                    properties.extend(inner_group.values)

        # Create RecordingsQuery
        recordings_query = RecordingsQuery(
            date_from=max_filters.date_from,
            date_to=max_filters.date_to,
            properties=properties,
            filter_test_accounts=max_filters.filter_test_accounts,
            order=max_filters.order,
            # Handle duration filters
            having_predicates=(
                [
                    {"key": "duration", "type": "recording", "operator": dur.operator, "value": dur.value}
                    for dur in (max_filters.duration or [])
                ]
                if max_filters.duration
                else None
            ),
        )

        # Execute the query to get session IDs
        query_runner = SessionRecordingListFromQuery(
            team=self._team, query=recordings_query, hogql_query_modifiers=None
        )

        # Get the results
        results = query_runner.run()
        # Extract session IDs
        session_ids = [recording["session_id"] for recording in results.results]
        print("*" * 50)
        print("SESSION IDS")
        print(session_ids)

    def run(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState | None:
        start_time = time.time()
        session_id = state.summarization_session_id
        conversation_id = config.get("configurable", {}).get("thread_id", "unknown")
        filter_results = async_to_sync(self._generate_replay_filters)()
        session_ids = self._get_session_ids_from_query(filter_results)
        try:
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

    def router(self, _: AssistantState) -> Literal["end", "root"]:
        return "root"
