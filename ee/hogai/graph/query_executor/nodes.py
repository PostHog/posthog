import json
from time import sleep
from typing import Any
from uuid import uuid4

from django.conf import settings
from django.core.serializers.json import DjangoJSONEncoder
from langchain_core.runnables import RunnableConfig
from rest_framework.exceptions import APIException

from .format import (
    FunnelResultsFormatter,
    RetentionResultsFormatter,
    SQLResultsFormatter,
    TrendsResultsFormatter,
)
from .prompts import (
    FALLBACK_EXAMPLE_PROMPT,
    FUNNEL_STEPS_EXAMPLE_PROMPT,
    FUNNEL_TIME_TO_CONVERT_EXAMPLE_PROMPT,
    FUNNEL_TRENDS_EXAMPLE_PROMPT,
    QUERY_RESULTS_PROMPT,
    RETENTION_EXAMPLE_PROMPT,
    TRENDS_EXAMPLE_PROMPT,
    SQL_EXAMPLE_PROMPT,
)
from ..base import AssistantNode
from ee.hogai.utils.types import AssistantNodeName, AssistantState, PartialAssistantState
from posthog.api.services.query import process_query_dict
from posthog.clickhouse.client.execute_async import get_query_status
from posthog.errors import ExposedCHQueryError
from posthog.exceptions_capture import capture_exception
from posthog.hogql.errors import ExposedHogQLError
from posthog.hogql_queries.query_runner import ExecutionMode
from posthog.schema import (
    AssistantFunnelsQuery,
    AssistantHogQLQuery,
    AssistantRetentionQuery,
    AssistantToolCallMessage,
    AssistantTrendsQuery,
    FailureMessage,
    FunnelVizType,
    VisualizationMessage,
)


class QueryExecutorNode(AssistantNode):
    name = AssistantNodeName.QUERY_EXECUTOR

    def run(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState | None:
        viz_message = state.messages[-1]
        if not isinstance(viz_message, VisualizationMessage):
            raise ValueError(f"Expected a visualization message, found {type(viz_message)}")
        if viz_message.answer is None:
            raise ValueError("Did not find query in the visualization message")

        tool_call_id = state.root_tool_call_id
        if not tool_call_id:
            return None

        try:
            results_response = process_query_dict(  # type: ignore
                self._team,  # TODO: Add user
                viz_message.answer.model_dump(mode="json"),
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
        except Exception as err:
            capture_exception(err)
            return PartialAssistantState(
                messages=[FailureMessage(content="There was an unknown error running this query.", id=str(uuid4()))]
            )

        try:
            results = self._compress_results(viz_message, results_response)
            example_prompt = self._get_example_prompt(viz_message)
        except Exception as err:
            if isinstance(err, NotImplementedError):
                raise
            capture_exception(err)
            # In case something is wrong with the compression, we fall back to the plain JSON.
            results = json.dumps(results_response["results"], cls=DjangoJSONEncoder, separators=(",", ":"))
            example_prompt = FALLBACK_EXAMPLE_PROMPT

        formatted_query_result = QUERY_RESULTS_PROMPT.format(
            example=example_prompt,
            query_kind=viz_message.answer.kind,
            results=results,
            utc_datetime_display=self.utc_now,
            project_datetime_display=self.project_now,
            project_timezone=self.project_timezone,
        )

        return PartialAssistantState(
            messages=[
                AssistantToolCallMessage(content=formatted_query_result, id=str(uuid4()), tool_call_id=tool_call_id)
            ],
            # Resetting values to empty strings because Nones are not supported by LangGraph.
            root_tool_call_id="",
            root_tool_insight_plan="",
            root_tool_insight_type="",
        )

    def _compress_results(self, viz_message: VisualizationMessage, response: dict[str, Any]) -> str:
        if isinstance(viz_message.answer, AssistantTrendsQuery):
            return TrendsResultsFormatter(viz_message.answer, response["results"]).format()
        elif isinstance(viz_message.answer, AssistantFunnelsQuery):
            return FunnelResultsFormatter(
                viz_message.answer, response["results"], self._team, self._utc_now_datetime
            ).format()
        elif isinstance(viz_message.answer, AssistantRetentionQuery):
            return RetentionResultsFormatter(viz_message.answer, response["results"]).format()
        elif isinstance(viz_message.answer, AssistantHogQLQuery):
            return SQLResultsFormatter(viz_message.answer, response["results"], response["columns"]).format()
        raise NotImplementedError(f"Unsupported query type: {type(viz_message.answer)}")

    def _get_example_prompt(self, viz_message: VisualizationMessage) -> str:
        if isinstance(viz_message.answer, AssistantTrendsQuery):
            return TRENDS_EXAMPLE_PROMPT
        if isinstance(viz_message.answer, AssistantFunnelsQuery):
            if (
                not viz_message.answer.funnelsFilter
                or not viz_message.answer.funnelsFilter.funnelVizType
                or viz_message.answer.funnelsFilter.funnelVizType == FunnelVizType.STEPS
            ):
                return FUNNEL_STEPS_EXAMPLE_PROMPT
            if viz_message.answer.funnelsFilter.funnelVizType == FunnelVizType.TIME_TO_CONVERT:
                return FUNNEL_TIME_TO_CONVERT_EXAMPLE_PROMPT
            return FUNNEL_TRENDS_EXAMPLE_PROMPT
        if isinstance(viz_message.answer, AssistantRetentionQuery):
            return RETENTION_EXAMPLE_PROMPT
        if isinstance(viz_message.answer, AssistantHogQLQuery):
            return SQL_EXAMPLE_PROMPT
        raise NotImplementedError(f"Unsupported query type: {type(viz_message.answer)}")
