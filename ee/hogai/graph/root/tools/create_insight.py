from collections.abc import Sequence
from typing import cast

import structlog
from posthoganalytics import capture_exception
from pydantic import BaseModel, Field

from posthog.schema import AssistantMessage, AssistantTool, AssistantToolCallMessage, VisualizationMessage

from ee.hogai.tool import MaxTool
from ee.hogai.utils.helpers import extract_stream_update
from ee.hogai.utils.state import is_task_started_update, is_value_update
from ee.hogai.utils.types import AssistantState
from ee.hogai.utils.types.base import AnyAssistantGeneratedQuery, AssistantMessageUnion, InsightArtifact, ToolResult

logger = structlog.get_logger(__name__)


class CreateInsightToolArgs(BaseModel):
    query_description: str = Field(
        description=(
            "A description of the query to generate, encapsulating the details of the user's request. "
            "Include all relevant context from earlier messages too, as the tool won't see that conversation history. "
            "If an existing insight has been used as a starting point, include that insight's filters and query in the description. "
            "Don't be overly prescriptive with event or property names, unless the user indicated they mean this specific name (e.g. with quotes). "
            "If the users seems to ask for a list of entities, rather than a count, state this explicitly."
        )
    )


class CreateInsightTool(MaxTool):
    name = AssistantTool.CREATE_AND_QUERY_INSIGHT
    description = """
    Use this tool to spawn a subagent that will create a product analytics insight for a given description.
    The tool generates a query and returns formatted text results for a specific data question or iterates on a previous query. It only retrieves a single query per call. If the user asks for multiple insights, you need to decompose a query into multiple subqueries and call the tool for each subquery.

    Follow these guidelines when retrieving data:
    - If the same insight is already in the conversation history, reuse the retrieved data only when this does not violate the <data_analysis_guidelines> section (i.e. only when a presence-check, count, or sort on existing columns is enough).
    - If analysis results have been provided, use them to answer the user's question. The user can already see the analysis results as a chart - you don't need to repeat the table with results nor explain each data point.
    - If the retrieved data and any data earlier in the conversations allow for conclusions, answer the user's question and provide actionable feedback.
    - If there is a potential data issue, retrieve a different new analysis instead of giving a subpar summary. Note: empty data is NOT a potential data issue.
    - If the query cannot be answered with a UI-built insight type - trends, funnels, retention - choose the SQL type to answer the question (e.g. for listing events or aggregating in ways that aren't supported in trends/funnels/retention).

    IMPORTANT: Avoid generic advice. Take into account what you know about the product. Your answer needs to be super high-impact and no more than a few sentences.
    Remember: do NOT retrieve data for the same query more than 3 times in a row.

    # Data schema

    The subagent will have access to the read_taxonomy tool. You can pass events, actions, properties, and property values to this tool by specifying the "Data schema" section.

    <example>
    User: Calculate onboarding completion rate for the last week.
    Assistant: I'm going to retrieve the existing data schema first.
    *Retrieves matching events, properties, and property values*
    Assistant: I'm going to create a new trends insight.
    *Calls this tool with the query description: "Trends insight of the onboarding completion rate. Data schema: Relevant matching data schema"*
    </example>

    # Supported insight types
    ## Trends
    A trends insight visualizes events over time using time series. They're useful for finding patterns in historical data.

    The trends insights have the following features:
    - The insight can show multiple trends in one request.
    - Custom formulas can calculate derived metrics, like `A/B*100` to calculate a ratio.
    - Filter and break down data using multiple properties.
    - Compare with the previous period and sample data.
    - Apply various aggregation types, like sum, average, etc., and chart types.
    - And more.

    Examples of use cases include:
    - How the product's most important metrics change over time.
    - Long-term patterns, or cycles in product's usage.
    - The usage of different features side-by-side.
    - How the properties of events vary using aggregation (sum, average, etc).
    - Users can also visualize the same data points in a variety of ways.

    ## Funnel
    A funnel insight visualizes a sequence of events that users go through in a product. They use percentages as the primary aggregation type. Funnels use two or more series, so the conversation history should mention at least two events.

    The funnel insights have the following features:
    - Various visualization types (steps, time-to-convert, historical trends).
    - Filter data and apply exclusion steps.
    - Break down data using a single property.
    - Specify conversion windows, details of conversion calculation, attribution settings.
    - Sample data.
    - And more.

    Examples of use cases include:
    - Conversion rates.
    - Drop off steps.
    - Steps with the highest friction and time to convert.
    - If product changes are improving their funnel over time.
    - Average/median time to convert.
    - Conversion trends over time.

    ## Retention
    A retention insight visualizes how many users return to the product after performing some action. They're useful for understanding user engagement and retention.

    The retention insights have the following features: filter data, sample data, and more.

    Examples of use cases include:
    - How many users come back and perform an action after their first visit.
    - How many users come back to perform action X after performing action Y.
    - How often users return to use a specific feature.

    ## SQL
    The 'sql' insight type allows you to write arbitrary SQL queries to retrieve data.

    The SQL insights have the following features:
    - Filter data using arbitrary SQL.
    - All ClickHouse SQL features.
    - You can nest subqueries as needed.
    """
    args_schema = CreateInsightToolArgs

    async def _arun_impl(self, query_description: str) -> ToolResult:
        # Import here to avoid circular dependency
        from ee.hogai.graph.graph import InsightsAssistantGraph

        input_state = AssistantState(
            messages=cast(AssistantState, self._state).messages if self._state else [],
            root_tool_call_id=self._tool_call_id,
            root_tool_insight_plan=query_description,
        )

        subgraph_result_messages: list[AssistantMessageUnion] = []
        assistant_graph = InsightsAssistantGraph(self._team, self._user).compile_full_graph()
        try:
            async for chunk in assistant_graph.astream(
                input_state,
                self._config,
                subgraphs=True,
                stream_mode=["updates", "debug"],
            ):
                if not chunk:
                    continue

                update = extract_stream_update(chunk)
                if is_value_update(update):
                    _, content = update
                    node_name = next(iter(content.keys()))
                    messages = content[node_name]["messages"]
                    subgraph_result_messages.extend(messages)
                elif is_task_started_update(update):
                    _, task_update = update
                    node_name = task_update["payload"]["name"]  # type: ignore
                    node_input = task_update["payload"]["input"]  # type: ignore
                    reasoning_message = await assistant_graph.aget_reasoning_message_by_node_name[node_name](
                        node_input, ""
                    )
                    if reasoning_message:
                        progress_text = reasoning_message.content
                        await self._update_tool_call_status(progress_text, reasoning_message.substeps)

        except Exception as e:
            capture_exception(e)
            raise

        if len(subgraph_result_messages) == 0 or not subgraph_result_messages[-1]:
            logger.warning("Task failed: no messages received from insights subgraph", tool_call_id=self._tool_call_id)
            return await self._failed_execution()

        last_message = subgraph_result_messages[-1]

        if not isinstance(last_message, AssistantToolCallMessage):
            logger.warning(
                "Task failed: last message is not AssistantToolCallMessage",
                tool_call_id=self._tool_call_id,
            )
            if isinstance(last_message, AssistantMessage):
                # The agent has requested help from the user
                return await self._successful_execution(last_message.content)
            else:
                return await self._failed_execution()

        response = last_message.content

        artifacts = self._extract_artifacts(query_description, subgraph_result_messages)
        if len(artifacts) == 0:
            response += "\n\nNo artifacts were generated."
            logger.warning("Task failed: no artifacts extracted", tool_call_id=self._tool_call_id)
            return await self._failed_execution()

        return await self._successful_execution(response, artifacts)

    def _extract_artifacts(
        self, query_description: str, subgraph_result_messages: list[AssistantMessageUnion]
    ) -> Sequence[InsightArtifact]:
        """Extract artifacts from insights subgraph execution results."""

        last_message = subgraph_result_messages[-1]
        if not isinstance(last_message, AssistantToolCallMessage):
            return []
        response = last_message.content
        artifacts: list[InsightArtifact] = []
        for message in subgraph_result_messages:
            if isinstance(message, VisualizationMessage) and message.id:
                artifact = InsightArtifact(
                    tool_call_id=self._tool_call_id,
                    id=None,  # The InsightsAssistantGraph does not create the insight objects
                    content=response,
                    plan=query_description,
                    query=cast(AnyAssistantGeneratedQuery, message.answer),
                )
                artifacts.append(artifact)
                break
        return artifacts
