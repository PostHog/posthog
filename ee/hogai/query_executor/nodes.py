import json
from time import sleep
from uuid import uuid4

from django.conf import settings
from django.core.serializers.json import DjangoJSONEncoder
from langchain_core.runnables import RunnableConfig
from rest_framework.exceptions import APIException

from ee.hogai.query_executor.format import (
    FunnelResultsFormatter,
    RetentionResultsFormatter,
    TrendsResultsFormatter,
)
from ee.hogai.query_executor.prompts import (
    FALLBACK_EXAMPLE_PROMPT,
    FUNNEL_STEPS_EXAMPLE_PROMPT,
    FUNNEL_TIME_TO_CONVERT_EXAMPLE_PROMPT,
    FUNNEL_TRENDS_EXAMPLE_PROMPT,
    QUERY_RESULTS_PROMPT,
    RETENTION_EXAMPLE_PROMPT,
    TRENDS_EXAMPLE_PROMPT,
)
from ee.hogai.utils.nodes import AssistantNode
from ee.hogai.utils.types import AssistantNodeName, AssistantState, PartialAssistantState
from posthog.api.services.query import process_query_dict
from posthog.clickhouse.client.execute_async import get_query_status
from posthog.errors import ExposedCHQueryError
from posthog.exceptions_capture import capture_exception
from posthog.hogql.errors import ExposedHogQLError
from posthog.hogql_queries.query_runner import ExecutionMode
from posthog.schema import (
    AssistantFunnelsQuery,
    AssistantMessage,
    AssistantRetentionQuery,
    AssistantTrendsQuery,
    FailureMessage,
    FunnelVizType,
    VisualizationMessage,
)


class QueryExecutorNode(AssistantNode):
    name = AssistantNodeName.QUERY_EXECUTOR

    def run(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState:
        viz_message = state.messages[-1]
        if not isinstance(viz_message, VisualizationMessage):
            raise ValueError("Can only run summarization with a visualization message as the last one in the state")
        if viz_message.answer is None:
            raise ValueError("Did not find query in the visualization message")

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
            if results_response.get("query_status") and not results_response["query_status"]["complete"]:
                query_id = results_response["query_status"]["id"]
                for i in range(0, 999):
                    sleep(i / 2)  # We start at 0.5s and every iteration we wait 0.5s more
                    query_status = get_query_status(team_id=self._team.pk, query_id=query_id)
                    if query_status.error:
                        if query_status.error_message:
                            raise APIException(query_status.error_message)
                        else:
                            raise ValueError("Query failed")
                    if query_status.complete:
                        results_response = query_status.results
                        break
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
            results = self._compress_results(viz_message, results_response["results"])
            example_prompt = self._get_example_prompt(viz_message)
        except Exception as err:
            if isinstance(err, NotImplementedError):
                raise
            capture_exception(err)
            # In case something is wrong with the compression, we fall back to the plain JSON.
            results = json.dumps(results_response["results"], cls=DjangoJSONEncoder, separators=(",", ":"))
            example_prompt = FALLBACK_EXAMPLE_PROMPT

        return PartialAssistantState(
            messages=[
                AssistantMessage(
                    content=QUERY_RESULTS_PROMPT.format(
                        example=example_prompt,
                        query_kind=viz_message.answer.kind,
                        results=results,
                        utc_datetime_display=self.utc_now,
                        project_datetime_display=self.project_now,
                        project_timezone=self.project_timezone,
                    ),
                    id=str(uuid4()),
                )
            ]
        )

    def _compress_results(self, viz_message: VisualizationMessage, results: list[dict]) -> str:
        if isinstance(viz_message.answer, AssistantTrendsQuery):
            return TrendsResultsFormatter(viz_message.answer, results).format()
        elif isinstance(viz_message.answer, AssistantFunnelsQuery):
            return FunnelResultsFormatter(viz_message.answer, results, self._team, self._utc_now_datetime).format()
        elif isinstance(viz_message.answer, AssistantRetentionQuery):
            return RetentionResultsFormatter(viz_message.answer, results).format()
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
        raise NotImplementedError(f"Unsupported query type: {type(viz_message.answer)}")
