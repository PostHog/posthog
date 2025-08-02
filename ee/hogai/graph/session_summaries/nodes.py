import asyncio
import time
from typing import cast, Literal, Any
from uuid import uuid4

import structlog
from asgiref.sync import async_to_sync
from langchain_core.runnables import RunnableConfig

from ee.hogai.graph.base import AssistantNode
from ee.hogai.session_summaries.constants import SESSION_SUMMARIES_STREAMING_MODEL
from ee.hogai.session_summaries.session_group.summarize_session_group import find_sessions_timestamps
from ee.hogai.session_summaries.session_group.summary_notebooks import create_summary_notebook
from ee.hogai.utils.types import AssistantState, PartialAssistantState
from posthog.schema import MaxRecordingUniversalFilters, RecordingsQuery, AssistantToolCallMessage
from posthog.temporal.ai.session_summary.summarize_session import execute_summarize_session
from posthog.temporal.ai.session_summary.summarize_session_group import execute_summarize_session_group


class SessionSummarizationNode(AssistantNode):
    logger = structlog.get_logger(__name__)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    async def _generate_replay_filters(self, plain_text_query: str) -> MaxRecordingUniversalFilters | None:
        """Generates replay filters to get session ids by querying a compiled Universal filters graph."""
        from ee.hogai.graph.filter_options.prompts import PRODUCT_DESCRIPTION_PROMPT
        from products.replay.backend.prompts import SESSION_REPLAY_RESPONSE_FORMATS_PROMPT
        from products.replay.backend.prompts import SESSION_REPLAY_EXAMPLES_PROMPT
        from products.replay.backend.prompts import MULTIPLE_FILTERS_PROMPT
        from ee.hogai.graph.filter_options.graph import FilterOptionsGraph

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
        if (
            not result
            or not isinstance(result, dict)
            or not result.get("generated_filter_options")
            or not result["generated_filter_options"].get("data")
        ):
            self.logger.error(
                f"Invalid result from filter options graph: {result}",
                extra={
                    "team_id": getattr(self._team, "id", "unknown"),
                    "user_id": getattr(self._user, "id", "unknown"),
                    "result": result,
                },
            )
            return None
        # Extract the generated filters
        filters_data = result["generated_filter_options"]["data"]
        if not filters_data:
            return None
        max_filters = cast(MaxRecordingUniversalFilters, filters_data)
        return max_filters

    def _get_session_ids_with_filters(self, replay_filters: MaxRecordingUniversalFilters) -> list[str] | None:
        from posthog.session_recordings.queries_to_replace.session_recording_list_from_query import (
            SessionRecordingListFromQuery,
        )

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

    async def _summarize_sessions_into_content(self, session_ids: list[str]) -> str:
        """Summarizes the sessions using the provided session IDs."""
        # If a small amount of sessions - we won't be able to extract lots of patters,
        # so it's ok to summarize them one by one and answer fast (without notebook creation)
        if len(session_ids) <= 5:
            summaries_tasks = [
                # As it's used as a direct output, use faster streaming model instead
                execute_summarize_session(
                    session_id=sid,
                    user_id=self._user.id,
                    team=self._team,
                    model_to_use=SESSION_SUMMARIES_STREAMING_MODEL,
                )
                for sid in session_ids
            ]
            summaries: list[str] = await asyncio.gather(*summaries_tasks)
            # TODO: Add layer to convert JSON into more readable text for Max to returns to user
            content = "\n".join(summaries)
            return content
        # If a large amount of sessions - we will summarize them in a group and create a notebook
        # to provide a more detailed overview of the patterns and insights.
        min_timestamp, max_timestamp = find_sessions_timestamps(session_ids=session_ids, team=self._team)
        summary = execute_summarize_session_group(
            session_ids=session_ids,
            user_id=self._user.pk,
            team=self._team,
            min_timestamp=min_timestamp,
            max_timestamp=max_timestamp,
            extra_summary_context=None,
            local_reads_prod=False,
        )
        create_summary_notebook(session_ids=session_ids, user=self._user, team=self._team, summary=summary)
        content = summary.model_dump_json(exclude_none=True)
        return content

    def run(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState | None:
        start_time = time.time()
        conversation_id = config.get("configurable", {}).get("thread_id", "unknown")
        # If query was not provided for some reason
        if not state.session_summarization_query:
            self._log_failure(
                f"Session summarization query is not provided: {state.session_summarization_query}",
                conversation_id,
                start_time,
            )
            return self._create_error_response(self._base_error_instructions, state.root_tool_call_id)
        try:
            # Generate filters to get session ids from DB
            replay_filters = async_to_sync(self._generate_replay_filters)(state.session_summarization_query)
            if not replay_filters:
                self._log_failure(
                    f"No Replay filters were generated for session summarization: {state.session_summarization_query}",
                    conversation_id,
                    start_time,
                )
                return self._create_error_response(self._base_error_instructions, state.root_tool_call_id)
            # Query the filters to get session ids
            session_ids = self._get_session_ids_with_filters(replay_filters)
            # TODO: Remove after testing
            # Limit to 5 to test fast summarization
            session_ids = session_ids[:5] if session_ids else []
            if not session_ids:
                self._log_failure(
                    f"No session ids found for the provided filters: {replay_filters}", conversation_id, start_time
                )
                return self._create_error_response(self._base_error_instructions, state.root_tool_call_id)
            summaries_content = async_to_sync(self._summarize_sessions_into_content)(session_ids)
            return PartialAssistantState(
                messages=[
                    AssistantToolCallMessage(
                        content=summaries_content,
                        tool_call_id=state.root_tool_call_id or "unknown",
                        id=str(uuid4()),
                    ),
                ],
                session_summarization_query=None,
                root_tool_call_id=None,
            )
        except Exception as err:
            self._log_failure("Session summarization failed", conversation_id, start_time, err)
            return self._create_error_response(self._base_error_instructions, state.root_tool_call_id)

    def _create_error_response(self, message: str, root_tool_call_id: str | None) -> PartialAssistantState:
        return PartialAssistantState(
            messages=[
                AssistantToolCallMessage(
                    content=message,
                    tool_call_id=root_tool_call_id or "unknown",
                    id=str(uuid4()),
                ),
            ],
            session_summarization_query=None,
            root_tool_call_id=None,
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
    def _base_error_instructions(self) -> str:
        return "INSTRUCTIONS: Tell the user that you encountered an issue while summarizing the session and suggest they try again with a different question."

    def router(self, _: AssistantState) -> Literal["end", "root"]:
        return "root"
