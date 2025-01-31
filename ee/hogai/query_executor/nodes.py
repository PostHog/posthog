import datetime
import json
from time import sleep
from uuid import uuid4

from django.conf import settings
from django.core.serializers.json import DjangoJSONEncoder
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableConfig
from rest_framework.exceptions import APIException
from sentry_sdk import capture_exception

from ee.hogai.query_executor.prompts import QUERY_RESULTS_PROMPT
from ee.hogai.utils.nodes import AssistantNode
from ee.hogai.utils.types import AssistantNodeName, AssistantState, PartialAssistantState
from posthog.api.services.query import process_query_dict
from posthog.clickhouse.client.execute_async import get_query_status
from posthog.errors import ExposedCHQueryError
from posthog.hogql.errors import ExposedHogQLError
from posthog.hogql_queries.query_runner import ExecutionMode
from posthog.schema import AssistantMessage, FailureMessage, VisualizationMessage


class QueryExecutorNode(AssistantNode):
    name = AssistantNodeName.QUERY_EXECUTOR

    def run(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState:
        viz_message = state.messages[-1]
        if not isinstance(viz_message, VisualizationMessage):
            raise ValueError("Can only run summarization with a visualization message as the last one in the state")
        if viz_message.answer is None:
            raise ValueError("Did not found query in the visualization message")

        try:
            results_response = process_query_dict(  # type: ignore
                self._team,  # TODO: Add user
                viz_message.answer.model_dump(mode="json"),
                # Celery doesn't run in tests, so there we use force_blocking instead
                # This does mean that the waiting logic is not tested
                execution_mode=ExecutionMode.RECENT_CACHE_CALCULATE_ASYNC_IF_STALE
                if not settings.TEST
                else ExecutionMode.CALCULATE_BLOCKING_ALWAYS,
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

        utc_now = datetime.datetime.now(datetime.UTC)
        project_now = utc_now.astimezone(self._team.timezone_info)

        return PartialAssistantState(
            messages=[
                AssistantMessage(
                    content=ChatPromptTemplate.from_messages(
                        messages=[("assistant", QUERY_RESULTS_PROMPT)],
                        template_format="mustache",
                    ).format(
                        query=viz_message.answer.model_dump_json(exclude_unset=True, exclude_none=True),
                        results=json.dumps(results_response["results"], cls=DjangoJSONEncoder),
                        utc_datetime_display=utc_now.strftime("%Y-%m-%d %H:%M:%S"),
                        project_datetime_display=project_now.strftime("%Y-%m-%d %H:%M:%S"),
                        project_timezone=self._team.timezone_info.tzname(utc_now),
                    ),
                    id=str(uuid4()),
                )
            ]
        )
