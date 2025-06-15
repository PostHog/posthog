from uuid import uuid4

from langchain_core.runnables import RunnableConfig

from ee.hogai.utils.types import AssistantNodeName, AssistantState, PartialAssistantState
from posthog.exceptions_capture import capture_exception
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

from ..base import AssistantNode
from .query_executor import AssistantQueryExecutor
from .prompts import (
    FALLBACK_EXAMPLE_PROMPT,
    FUNNEL_STEPS_EXAMPLE_PROMPT,
    FUNNEL_TIME_TO_CONVERT_EXAMPLE_PROMPT,
    FUNNEL_TRENDS_EXAMPLE_PROMPT,
    QUERY_RESULTS_PROMPT,
    RETENTION_EXAMPLE_PROMPT,
    SQL_EXAMPLE_PROMPT,
    SQL_QUERY_PROMPT,
    TRENDS_EXAMPLE_PROMPT,
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

        query_runner = AssistantQueryExecutor(self._team, self._utc_now_datetime)
        try:
            results, used_fallback = query_runner.run_and_format_query(viz_message.answer)
            example_prompt = FALLBACK_EXAMPLE_PROMPT if used_fallback else self._get_example_prompt(viz_message)
        except Exception as err:
            if isinstance(err, NotImplementedError):
                raise
            capture_exception(err)
            return PartialAssistantState(messages=[FailureMessage(content=str(err), id=str(uuid4()))])

        query_result = QUERY_RESULTS_PROMPT.format(
            query_kind=viz_message.answer.kind,
            results=results,
            utc_datetime_display=self.utc_now,
            project_datetime_display=self.project_now,
            project_timezone=self.project_timezone,
        )

        formatted_query_result = f"{example_prompt}\n\n{query_result}"
        if isinstance(viz_message.answer, AssistantHogQLQuery):
            formatted_query_result = f"{example_prompt}\n\n{SQL_QUERY_PROMPT.format(query=viz_message.answer.query)}\n\n{formatted_query_result}"

        return PartialAssistantState(
            messages=[
                AssistantToolCallMessage(content=formatted_query_result, id=str(uuid4()), tool_call_id=tool_call_id)
            ],
            # Resetting values to empty strings because Nones are not supported by LangGraph.
            root_tool_call_id="",
            root_tool_insight_plan="",
            root_tool_insight_type="",
        )

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
