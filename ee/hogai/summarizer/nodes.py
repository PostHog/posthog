import datetime
from time import sleep
from uuid import uuid4

from django.conf import settings
from django.utils import timezone
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableConfig
from langchain_openai import ChatOpenAI
from rest_framework.exceptions import APIException
from sentry_sdk import capture_exception

from ee.hogai.summarizer.format import (
    compress_and_format_funnels_results,
    compress_and_format_retention_results,
    compress_and_format_trends_results,
)
from ee.hogai.summarizer.prompts import SUMMARIZER_INSTRUCTION_PROMPT, SUMMARIZER_SYSTEM_PROMPT
from ee.hogai.utils.nodes import AssistantNode
from ee.hogai.utils.types import AssistantNodeName, AssistantState, PartialAssistantState
from posthog.api.services.query import process_query_dict
from posthog.clickhouse.client.execute_async import get_query_status
from posthog.errors import ExposedCHQueryError
from posthog.hogql.errors import ExposedHogQLError
from posthog.hogql_queries.query_runner import ExecutionMode
from posthog.schema import (
    AssistantFunnelsQuery,
    AssistantMessage,
    AssistantRetentionQuery,
    AssistantTrendsQuery,
    FailureMessage,
    HumanMessage,
    VisualizationMessage,
)


class SummarizerNode(AssistantNode):
    name = AssistantNodeName.SUMMARIZER

    def run(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState:
        viz_message = state.messages[-1]
        if not isinstance(viz_message, VisualizationMessage):
            raise ValueError("Can only run summarization with a visualization message as the last one in the state")
        if viz_message.answer is None:
            raise ValueError("Did not found query in the visualization message")

        try:
            results_response = process_query_dict(  # type: ignore
                self._team,  # TODO: Add user
                viz_message.answer.model_dump(mode="json"),  # We need mode="json" so that
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

        summarization_prompt = ChatPromptTemplate(self._construct_messages(state))

        chain = summarization_prompt | self._model

        utc_now = timezone.now().astimezone(datetime.UTC)
        project_now = utc_now.astimezone(self._team.timezone_info)

        message = chain.invoke(
            {
                "query_kind": viz_message.answer.kind,
                "core_memory": self.core_memory_text,
                "results": self._compress_results(viz_message, results_response["results"]),
                "utc_datetime_display": utc_now.strftime("%Y-%m-%d %H:%M:%S"),
                "project_datetime_display": project_now.strftime("%Y-%m-%d %H:%M:%S"),
                "project_timezone": self._team.timezone_info.tzname(utc_now),
            },
            config,
        )

        return PartialAssistantState(messages=[AssistantMessage(content=str(message.content), id=str(uuid4()))])

    @property
    def _model(self):
        return ChatOpenAI(
            model="gpt-4o", temperature=0.5, streaming=True, stream_usage=True
        )  # Slightly higher temp than earlier steps

    def _construct_messages(self, state: AssistantState) -> list[tuple[str, str]]:
        conversation: list[tuple[str, str]] = [("system", SUMMARIZER_SYSTEM_PROMPT)]

        for message in state.messages:
            if isinstance(message, HumanMessage):
                conversation.append(("human", message.content))
            elif isinstance(message, AssistantMessage):
                conversation.append(("assistant", message.content))

        conversation.append(("human", SUMMARIZER_INSTRUCTION_PROMPT))
        return conversation

    def _compress_results(self, viz_message: VisualizationMessage, results: list[dict]) -> str:
        if isinstance(viz_message.answer, AssistantTrendsQuery):
            return compress_and_format_trends_results(results)
        elif isinstance(viz_message.answer, AssistantFunnelsQuery):
            return compress_and_format_funnels_results(results)
        elif isinstance(viz_message.answer, AssistantRetentionQuery):
            return compress_and_format_retention_results(results)
        raise NotImplementedError(f"Unsupported query type: {type(viz_message.answer)}")
