from datetime import datetime
from time import sleep
from typing import Any
from uuid import uuid4

from django.conf import settings
from langchain_core.runnables import RunnableConfig
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field
from rest_framework.exceptions import APIException

from ee.hogai.graph.base import AssistantNode
from ee.hogai.utils.types import AssistantState, PartialAssistantState
from ee.session_recordings.session_summary.summarize_session import ReplaySummarizer
from posthog.api.services.query import process_query_dict
from posthog.clickhouse.client.execute_async import get_query_status
from posthog.errors import ExposedCHQueryError
from posthog.hogql.errors import ExposedHogQLError
from posthog.hogql_queries.query_runner import ExecutionMode
from posthog.models import Insight
from posthog.schema import (
    ActorsQuery,
    AssistantToolCallMessage,
    FailureMessage,
    FunnelsActorsQuery,
    FunnelsQuery,
    FunnelVizType,
    HogQLQuery,
    InsightActorsQuery,
    RetentionQuery,
    TrendsQuery,
)


class QueryParser(BaseModel):
    root: FunnelsQuery | TrendsQuery | RetentionQuery | HogQLQuery = Field(discriminator="kind")


def build_actors_query(
    query: FunnelsQuery | TrendsQuery | RetentionQuery | HogQLQuery,
    config: dict[str, Any],
) -> ActorsQuery:
    if isinstance(query, FunnelsQuery):
        funnels_actors_query = FunnelsActorsQuery(source=query, includeRecordings=True)
        if query.funnelsFilter and query.funnelsFilter.funnelVizType == FunnelVizType.TRENDS:
            funnels_actors_query.funnelTrendsDropOff = config.get("funnel_drop_off", False)
            funnels_actors_query.funnelTrendsEntrancePeriodStart = datetime(2025, 1, 1).isoformat()
        dropoff_inc = 1
        if config.get("funnel_drop_off", False):
            dropoff_inc = -1
        if config.get("funnel_step"):
            funnels_actors_query.funnelStep = (config.get("funnel_step") + 1) * dropoff_inc
        else:
            funnels_actors_query.funnelStep = len(query.series) * dropoff_inc

        return ActorsQuery(
            source=funnels_actors_query,
            select=["actor", "matched_recordings"],
            search="",
            properties=[],
        )
    elif isinstance(query, TrendsQuery):
        return ActorsQuery(
            source=InsightActorsQuery(source=query, includeRecordings=True),
            select=["actor", "matched_recordings"],
            search="",
            properties=[],
        )
    return None


class SessionReplayAnalyzerNode(AssistantNode):
    def run(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState:
        insight = Insight.objects.get(id=state.session_replay_analysis["insight_id"], team=self._team)

        actors_query = build_actors_query(
            QueryParser.model_validate({"root": insight.query}).root, state.session_replay_analysis
        )

        if not actors_query:
            return PartialAssistantState(session_replay_analysis=None, root_tool_call_id=None)

        try:
            results_response = process_query_dict(  # type: ignore
                self._team,  # TODO: Add user
                actors_query.model_dump(exclude_unset=False, exclude_none=False, mode="json"),
                # Celery doesn't run in tests, so there we use force_blocking instead
                # This does mean that the waiting logic is not tested
                execution_mode=(
                    ExecutionMode.RECENT_CACHE_CALCULATE_ASYNC_IF_STALE
                    if not settings.TEST
                    else ExecutionMode.CALCULATE_BLOCKING_ALWAYS
                ),
            ).model_dump(mode="json")
            # If response has an async query_status, that's always the thing to use
            if query_status := results_response.get("query_status"):
                if not query_status["complete"]:
                    # If it's an in-progress (likely just kicked off) status, let's poll until complete
                    for wait_ms in range(100, 12000, 100):  # 726 s in total, if my math is correct
                        sleep(wait_ms / 1000)
                        query_status = get_query_status(team_id=self._team.pk, query_id=query_status["id"]).model_dump(
                            mode="json"
                        )
                        if query_status["complete"]:
                            break
                    else:
                        raise APIException(
                            "Query hasn't completed in time. It's worth trying again, maybe with a shorter time range."
                        )
                # With results ready, let's first check for errors - then actually use the results
                if query_status.get("error"):
                    if error_message := query_status.get("error_message"):
                        raise APIException(error_message)
                    raise Exception("Query failed")
                results_response = query_status["results"]
        except (APIException, ExposedHogQLError, ExposedCHQueryError) as err:
            err_message = str(err)
            if isinstance(err, APIException):
                if isinstance(err.detail, dict):
                    err_message = ", ".join(f"{key}: {value}" for key, value in err.detail.items())
                elif isinstance(err.detail, list):
                    err_message = ", ".join(map(str, err.detail))
            return PartialAssistantState(
                messages=[
                    FailureMessage(content=f"There was an error running this query: {err_message}", id=str(uuid4()))
                ]
            )

        session_ids = []
        for result in results_response["results"]:
            print(result)
            try:
                for unique_session in result[1]:
                    print(unique_session)
                    session_ids.append(unique_session)
            except Exception as e:
                print(e)
                pass

        if not session_ids:
            return PartialAssistantState(
                messages=[
                    AssistantToolCallMessage(
                        content="No recordings found. Use funnel for the analysis.",
                        tool_call_id=state.root_tool_call_id,
                    )
                ],
                root_tool_call_id="",
                session_replay_analysis={},
            )
        summarizer = ReplaySummarizer(session_ids[0], self._get_user(config), self._team)
        res = ""
        for chunk in summarizer.summarize_recording():
            res += chunk
        return PartialAssistantState(
            messages=[
                AssistantToolCallMessage(content="Session replay summary:\n{res}", tool_call_id=state.root_tool_call_id)
            ],
            root_tool_call_id="",
            session_replay_analysis={},
        )

    @property
    def _model(self):
        return ChatOpenAI(model="gpt-4.1", temperature=0)
