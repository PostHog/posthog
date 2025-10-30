from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from posthog.schema import AssistantTool, AssistantToolCallMessage, VisualizationMessage

from ee.hogai.context.context import AssistantContextManager
from ee.hogai.graph.insights_graph.graph import InsightsGraph
from ee.hogai.graph.schema_generator.nodes import SchemaGenerationException
from ee.hogai.tool import MaxTool, MaxToolArgs, ToolMessagesArtifact
from ee.hogai.utils.prompt import format_prompt_string
from ee.hogai.utils.types.base import AssistantState

INSIGHT_TOOL_PROMPT = """
Use this tool to create a product analytics insight for a given natural language description by spawning a subagent.
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

You can pass events, actions, properties, and property values to this tool by specifying the "Data schema" section.

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
""".strip()

INSIGHT_TOOL_CONTEXT_PROMPT_TEMPLATE = """
The user is currently editing an insight (aka query). Here is that insight's current definition, which can be edited using the `create_and_query_insight` tool:

```json
{current_query}
```

<system_reminder>
Do not remove any fields from the current insight definition. Do not change any other fields than the ones the user asked for. Keep the rest as is.
</system_reminder>
""".strip()

INSIGHT_TOOL_FAILURE_SYSTEM_REMINDER_PROMPT = """
<system_reminder>
Inform the user that you've encountered an error during the creation of the insight. Afterwards, try to generate a new insight with a different query.
Terminate if the error persists.
</system_reminder>
""".strip()

INSIGHT_TOOL_HANDLED_FAILURE_PROMPT = """
The agent has encountered the error while creating an insight.

Generated output:
```
{{{output}}}
```

Error message:
```
{{{error_message}}}
```

{{{system_reminder}}}
""".strip()


INSIGHT_TOOL_UNHANDLED_FAILURE_PROMPT = """
The agent has encountered an unknown error while creating an insight.
{{{system_reminder}}}
""".strip()


class CreateAndQueryInsightToolArgs(MaxToolArgs):
    query_description: str = Field(
        description=(
            "A description of the query to generate, encapsulating the details of the user's request. "
            "Include all relevant context from earlier messages too, as the tool won't see that conversation history. "
            "If an existing insight has been used as a starting point, include that insight's filters and query in the description. "
            "Don't be overly prescriptive with event or property names, unless the user indicated they mean this specific name (e.g. with quotes). "
            "If the users seems to ask for a list of entities, rather than a count, state this explicitly."
        )
    )


class CreateAndQueryInsightTool(MaxTool):
    name: Literal["create_and_query_insight"] = "create_and_query_insight"
    args_schema: type[BaseModel] = CreateAndQueryInsightToolArgs
    description: str = INSIGHT_TOOL_PROMPT
    context_prompt_template: str = INSIGHT_TOOL_CONTEXT_PROMPT_TEMPLATE
    thinking_message: str = "Coming up with an insight"

    async def _arun_impl(self, query_description: str, tool_call_id: str) -> tuple[str, ToolMessagesArtifact | None]:
        graph = InsightsGraph(self._team, self._user).compile_full_graph()
        new_state = self._state.model_copy(
            update={
                "root_tool_call_id": tool_call_id,
                "root_tool_insight_plan": query_description,
            },
            deep=True,
        )
        try:
            dict_state = await graph.ainvoke(new_state)
        except SchemaGenerationException as e:
            return format_prompt_string(
                INSIGHT_TOOL_HANDLED_FAILURE_PROMPT,
                output=e.llm_output,
                error_message=e.validation_message,
                system_reminder=INSIGHT_TOOL_FAILURE_SYSTEM_REMINDER_PROMPT,
            ), None

        updated_state = AssistantState.model_validate(dict_state)
        maybe_viz_message, tool_call_message = updated_state.messages[-2:]

        if not isinstance(tool_call_message, AssistantToolCallMessage):
            return format_prompt_string(
                INSIGHT_TOOL_UNHANDLED_FAILURE_PROMPT, system_reminder=INSIGHT_TOOL_FAILURE_SYSTEM_REMINDER_PROMPT
            ), None

        # If the previous message is not a visualization message, the agent has requested human feedback.
        if not isinstance(maybe_viz_message, VisualizationMessage):
            return "", ToolMessagesArtifact(messages=[tool_call_message])

        # If the contextual tool is available, we're editing an insight.
        # Add the UI payload to the tool call message.
        if self.is_editing_mode(self._context_manager):
            tool_call_message = AssistantToolCallMessage(
                content=tool_call_message.content,
                ui_payload={self.get_name(): maybe_viz_message.answer.model_dump(exclude_none=True)},
                id=str(uuid4()),
                tool_call_id=tool_call_message.tool_call_id,
            )

        return "", ToolMessagesArtifact(messages=[maybe_viz_message, tool_call_message])

    @classmethod
    def is_editing_mode(cls, context_manager: AssistantContextManager) -> bool:
        """
        Determines if the tool is in editing mode.
        """
        return AssistantTool.EDIT_CURRENT_INSIGHT.value in context_manager.get_contextual_tools()
