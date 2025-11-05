from typing import Literal

from pydantic import BaseModel, Field

from posthog.schema import AssistantTool, AssistantToolCallMessage, VisualizationMessage

from ee.hogai.context.context import AssistantContextManager
from ee.hogai.graph.insights_graph.graph import InsightsGraph
from ee.hogai.graph.schema_generator.nodes import SchemaGenerationException
from ee.hogai.tool import MaxTool, MaxToolArgs, ToolMessagesArtifact
from ee.hogai.utils.prompt import format_prompt_string
from ee.hogai.utils.types.base import AssistantNodeName, AssistantState

INSIGHT_TOOL_PROMPT = """
Use this tool to generate an insight from a structured plan. It will return a visualization that the user will be able to analyze and textual representation for your analysis.

The tool only generates a single insight per a call. If the user asks for multiple insights, you need to decompose a query into multiple subqueries and call the tool for each subquery.

Follow these guidelines when retrieving data:

- If the same insight is already in the conversation history, reuse the retrieved data only when this does not violate the <data_analysis_guidelines> section (i.e. only when a presence-check, count, or sort on existing columns is enough).
- If analysis results have been provided, use them to answer the user's question. The user can already see the analysis results as a chart - you don't need to repeat the table with results nor explain each data point.
- If the retrieved data and any data earlier in the conversations allow for conclusions, answer the user's question and provide actionable feedback.
- If there is a potential data issue, retrieve a different new analysis instead of giving a subpar summary. Note: empty data is NOT a potential data issue.
- If the query cannot be answered with a UI-built insight type - trends, funnels, retention - choose the SQL type to answer the question (e.g. for listing events or aggregating in ways that aren't supported in trends/funnels/retention).

Remember: do NOT retrieve data for the same query more than 3 times in a row.
Important: If the user request is about analysis of entities that are not collected data (events, properties, etc) like data warehouse entities, use SQL.

CRITICAL: When planning an insight, be minimalist. Only include filters, breakdowns, and settings that are essential to answer the user's specific question. Default settings are usually sufficient unless the user explicitly requests customization.

# Selecting a visualization type

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

A funnel insight visualizes a sequence of events that users go through in a product. They use percentages as the primary aggregation type. Funnels REQUIRE AT LEAST TWO series (events or actions), so the conversation history should mention at least two events.

The funnel insights have the following features:

- Various visualization types (steps, time-to-convert, historical trends).
- Filter data and apply exclusion steps (events only, not actions).
- Break down data using a single property.
- Specify conversion windows (default 14 days), step order (strict/ordered/unordered), and attribution settings.
- Aggregate by users, sessions, or specific group types.
- Sample data.
- Track first-time conversions with special math aggregations.
- And more.

Examples of use cases include:

- Conversion rates between steps.
- Drop off steps (which step loses most users).
- Steps with the highest friction and time to convert.
- If product changes are improving their funnel over time.
- Average/median/histogram of time to convert.
- Conversion trends over time (using trends visualization type).
- First-time user conversions (using first_time_for_user math).

## Retention

A retention insight visualizes how many users return to the product after performing some action. They're useful for understanding user engagement and retention.

The retention insights have the following features: filter data, sample data, and more.

Examples of use cases include:

- How many users come back and perform an action after their first visit.
- How many users come back to perform action X after performing action Y.
- How often users return to use a specific feature.

# Data narrowing

<property_filters>
Use property filters to provide a narrowed results. Only include property filters when they are essential to directly answer the user's question. Avoid adding them if the question can be addressed without additional segmentation and always use the minimum set of property filters needed to answer the question. Properties have one of the four types: String, Numeric, Boolean, and DateTime.

IMPORTANT: Do not check if a property is set unless the user explicitly asks for it.

When using a property filter, you must:

- **Prioritize properties directly related to the context or objective of the user's query.** Avoid using properties for identification like IDs because neither the user nor you can retrieve the data. Instead, prioritize filtering based on general properties like `paidCustomer` or `icp_score`.
- **Ensure that you find both the property group and name.** Property groups must be one of the following: event, person, session{{#groups}}, {{.}}{{/groups}}.
- After selecting a property, **validate that the property value accurately reflects the intended criteria**.
- **Find the suitable operator for type** (e.g., `contains`, `is set`). The operators are listed below.
- If the operator requires a value, use the tool to find the property values. Verify that you can answer the question with given property values. If you can't, try to find a different property or event.
- You set logical operators to combine multiple properties of a single series: AND or OR.

Infer the property groups from the user's request. If your first guess doesn't yield any results, try to adjust the property group. You must make sure that the property name matches the lookup value, e.g. if the user asks to find data about organizations with the name "ACME", you must look for the property like "organization name."

Supported operators for the String type are:

- equals (exact)
- doesn't equal (is_not)
- contains (icontains)
- doesn't contain (not_icontains)
- matches regex (regex)
- doesn't match regex (not_regex)
- is set
- is not set

Supported operators for the Numeric type are:

- equals (exact)
- doesn't equal (is_not)
- greater than (gt)
- less than (lt)
- is set
- is not set

Supported operators for the DateTime type are:

- equals (is_date_exact)
- doesn't equal (is_not for existence check)
- before (is_date_before)
- after (is_date_after)
- is set
- is not set

Supported operators for the Boolean type are:

- equals
- doesn't equal
- is set
- is not set

All operators take a single value except for `equals` and `doesn't equal` which can take one or more values (as an array).
</property_filters>

<time_period_and_property_filters>
You must not filter events by time, so you must not look for time-related properties. Do not verify whether events have a property indicating capture time as they always have, but it's unavailable to you. Instead, include time periods in the insight plan in the `Time period` section. If the question doesn't mention time, use `last 30 days` as a default time period.
Examples:

- If the user asks you "find events that happened between March 1st, 2025, and 2025-03-07", you must include `Time period: from 2025-03-01 to 2025-03-07` in the insight plan.
- If the user asks you "find events for the last month", you must include `Time period: from last month` in the insight plan.
  </time_period_and_property_filters>

# Trends guidelines

<general_knowledge>
Trends insights enable users to plot data from people, events, and properties however they want. They're useful for finding patterns in data, as well as monitoring users' product to ensure everything is running smoothly. Users can use multiple independent series in a single query to see trends. They can also use a formula to calculate a metric. Each series has its own set of property filters, so you must define them for each series. Trends insights do not require breakdowns or filters by default.
</general_knowledge>

<aggregation>
**Determine the math aggregation** the user is asking for, such as totals, averages, ratios, or custom formulas. If not specified, choose a reasonable default based on the event type (e.g., total count). By default, the total count should be used. You can aggregate data by events, event's property values,{{#groups}} {{.}}s,{{/groups}} or users. If you're aggregating by users or groups, there's no need to check for their existence, as events without required associations will automatically be filtered out.

Available math aggregations types for the event count are:

- total count
- average
- minimum
- maximum
- median
- 90th percentile
- 95th percentile
- 99th percentile
- unique users
- unique sessions
- weekly active users
- daily active users
- first time for a user
  {{#groups}}
- unique {{.}}s (requires `math_group_type_index` to be set to the group type index from the group mapping)
  {{/groups}}

Available math aggregation types for event's property values are:

- average
- sum
- minimum
- maximum
- median
- 90th percentile
- 95th percentile
- 99th percentile

Available math aggregation types counting number of events completed per user (intensity of usage) are:

- average
- minimum
- maximum
- median
- 90th percentile
- 95th percentile
- 99th percentile

Examples of using aggregation types:

- `unique users` to find how many distinct users have logged the event per a day.
- `average` by the `$session_diration` property to find out what was the average session duration of an event.
- `99th percentile by users` to find out what was the 99th percentile of the event count by users.
  </aggregation>

<math_formulas>
If the math aggregation is more complex or not listed above, use custom formulas to perform mathematical operations like calculating percentages or metrics. If you use a formula, you must use the following syntax: `A/B`, where `A` and `B` are the names of the series. You can combine math aggregations and formulas.

When using a formula, you must:

- Identify and specify **all** events and actions needed to solve the formula.
- Carefully review the list of available events and actions to find appropriate entities for each part of the formula.
- Ensure that you find events and actions corresponding to both the numerator and denominator in ratio calculations.

Examples of using math formulas:

- If you want to calculate the percentage of users who have completed onboarding, you need to find and use events or actions similar to `$identify` and `onboarding complete`, so the formula will be `A / B * 100`, where `A` is `onboarding complete` (unique users) and `B` is `$identify` (unique users).
- To calculate conversion rate: `A / B * 100` where A is conversions and B is total events
- To calculate average value: `A / B` where A is sum of property and B is count
  </math_formulas>

<time_interval>
Specify the time interval (group by's by time) in the `Time interval` section on the plan. Available intervals are: `hour`, `day`, `week`, `month`.
Unless the user has specified otherwise, use the following default interval:

- If the time period is less than two days, use the `hour` interval.
- If the time period is less than a month, use the `day` interval.
- If the time period is less than three months, use the `week` interval.
- Otherwise, use the `month` interval.
  </time_interval>

<breakdowns>
Breakdowns are used to segment data by property values of maximum three properties. They divide all defined trends series to multiple subseries based on the values of the property. Include breakdowns **only when they are essential to directly answer the user's question**. You must not add breakdowns if the question can be addressed without additional segmentation. Always use the minimum set of breakdowns needed to answer the question.

When using breakdowns, you must:

- **Identify the property group** and name for each breakdown.
- **Provide the property name** for each breakdown.
- **Validate that the property value accurately reflects the intended criteria**.

Examples of using breakdowns:

- page views trend by country: you need to find a property such as `$geoip_country_code` and set it as a breakdown.
- number of users who have completed onboarding by an organization: you need to find a property such as `organization name` and set it as a breakdown.
  </breakdowns>

<plan_example>
Series:

- series 1: event name
    - math operation: total
    - custom name: (optional) custom display name for this series
    - property filter 1:
        - entity
        - property name
        - property type
        - operator
        - property value
    - property filter 2... Repeat for each property filter.
- series 2: action name
    - action id: `numeric id`
    - math operation: average by `property name`.
    - custom name: (optional) custom display name for this series
    - property filter 1:
        - entity
        - property name
        - property type
        - operator
        - property value
    - property filter 2... Repeat for each property filter.
- Repeat for each event.

(if a formula is used)
Formula:
`A/B`, where `A` is the first event and `B` is the second event.

(if a breakdown is used)
Breakdown by:

- breakdown 1:
    - entity
    - property name
- Repeat for each breakdown.

(if comparing to previous period is needed)
Compare to previous period: yes/no
Compare to: (optional) specific relative date like `-1y`, `-14d`, `-30h`

(if a time period or interval is explicitly mentioned)
Time period: from and/or to dates or durations. For example: `last 1 week`, `last 12 days`, `from 2025-01-15 to 2025-01-20`, `2025-01-15`, from `last month` to `2024-11-15`.
Time interval: hour/day/week/month/year

(optional visualization settings)
Display type: (ActionsLineGraph/ActionsBar/ActionsAreaGraph/ActionsLineGraphCumulative/BoldNumber/ActionsBarValue/ActionsPie/ActionsTable/WorldMap)
Show legend: yes/no
Show values on series: yes/no
Y-axis scale: linear/log10
Axis format: numeric/duration/duration_ms/percentage/percentage_scaled/currency
Axis prefix: (e.g., "$")
Axis postfix: (e.g., " clicks")
Decimal places: (number)
</plan_example>

# Funnel guidelines

<general_knowledge>
Funnel insights help stakeholders understand user behavior as users navigate through a product. A funnel consists of a sequence of at least two events or actions, where some users progress to the next step while others drop off. Funnels are perfect for finding conversion rates, average and median conversion time, conversion trends, and distribution of conversion time.
</general_knowledge>

<exclusion_steps>
Users may want to use exclusion events to filter out conversions in which a particular event occurred between specific steps. These events must not be included in the main sequence. You must include start and end indexes for each exclusion where the minimum index is 1 (after first step) and the maximum index is the number of steps in the funnel. Exclusion events cannot be actions, only events.

IMPORTANT: Exclusion steps filter out conversions where the exclusion event occurred BETWEEN the specified steps. This does NOT exclude users who completed the event before the funnel started or after it ended.

For example, there is a sequence with three steps: sign up (step 1), finish onboarding (step 2), purchase (step 3). If the user wants to exclude all conversions in which users navigated away between sign up and finishing onboarding, the exclusion step will be:

```
Exclusions:
- $pageleave
    - start index: 1 (after sign up)
    - end index: 2 (before finish onboarding)
```

</exclusion_steps>

<breakdown>
A breakdown is used to segment data by a single property value. They divide all defined funnel series into multiple subseries based on the values of the property. Include a breakdown **only when it is essential to directly answer the user's question**. You must not add a breakdown if the question can be addressed without additional segmentation.

When using breakdowns, you must:

- **Identify the property group** and name for a breakdown.
- **Provide the property name** for a breakdown.
- **Validate that the property value accurately reflects the intended criteria**.

Examples of using a breakdown:

- page views to sign up funnel by country: you need to find a property such as `$geoip_country_code` and set it as a breakdown.
- conversion rate of users who have completed onboarding after signing up by an organization: you need to find a property such as `organization name` and set it as a breakdown.
  </breakdown>

<reminders>
- You MUST ALWAYS use AT LEAST TWO series (events or actions) in the funnel plan.
</reminders>

<plan_example>'
Sequence:

1. event: event name 1
    - custom name: (optional) custom display name for this step
    - math operation: (optional) first_time_for_user or first_time_for_user_with_filters
    - property filter 1:
        - entity
        - property name
        - property type
        - operator
        - property value
    - property filter 2... Repeat for each property filter.
2. action: action name 2
    - action id: `numeric id`
    - custom name: (optional) custom display name for this step
    - math operation: (optional) first_time_for_user or first_time_for_user_with_filters
    - property filter 1:
        - entity
        - property name
        - property type
        - operator
        - property value
    - property filter 2... Repeat for each property filter.
3. Repeat for each event or action...

(if exclusion steps are used)
Exclusions:

- exclusion event name 1
    - start index: 1
    - end index: 2
- exclusion event name 2... Repeat for each exclusion...

(if a breakdown is used)
Breakdown by:

- entity
- property name

(if aggregating by groups instead of users)
Aggregate by: group type index from group mapping

(if a time period is explicitly mentioned)
Time period: from and/or to dates or durations. For example: `last 1 week`, `last 12 days`, `from 2025-01-15 to 2025-01-20`, `2025-01-15`, from `last month` to `2024-11-15`.

(optional funnel settings)
Visualization type: steps/time_to_convert/trends
Conversion window: number and unit (e.g., 14 days, 1 hour)
Step order: strict/ordered/unordered
Step reference: total/previous (for conversion percentages)
Layout: vertical/horizontal
Bin count: (only for time_to_convert, number of histogram bins)
</plan_example>

# Retention guidelines

<general_knowledge>
Retention is a type of insight that shows you how many users return during subsequent periods.

They're useful for answering questions like:

- Are new sign ups coming back to use your product after trying it?
- Have recent changes improved retention?
  </general_knowledge>

<retention_plan>
Plans of retention insights must always have two events or actions:

- The activation event – an event or action that determines if the user is a part of a cohort (when they "start").
- The retention event – an event or action that determines whether a user has been retained (when they "return").

For activation and retention events, use the `$pageview` event by default or the equivalent for mobile apps `$screen`. Avoid infrequent or inconsistent events like `signed in` unless asked explicitly, as they skew the data.

The activation and retention events can be the same (e.g., both `$pageview` to see if users who viewed pages come back to view pages again) or different (e.g., activation is `signed up` and retention is `completed purchase` to see if sign-ups convert to purchases over time).
</retention_plan>

<plan_example>
Activation:
(if an event is used)

- event: chosen event name
  (or if an action is used)
- action id: `numeric id`
- action name: action name

Retention:

- event: chosen event name (can be the same as activation event, or different)
  (or if an action is used)
- action id: `numeric id`
- action name: action name

(if filters are used)
Filters: - property filter 1: - entity - property name - property type - operator - property value - property filter 2... Repeat for each property filter.

(if a time period is explicitly mentioned)
Time period: from and/or to dates or durations. For example: `last 1 week`, `last 12 days`, `from 2025-01-15 to 2025-01-20`, `2025-01-15`, from `last month` to `2024-11-15`.
</plan_example>

# Reminders

- Ensure that any properties included are directly relevant to the context and objectives of the user's question. Avoid unnecessary or unrelated details.
- Avoid overcomplicating the response with excessive property filters. Focus on the simplest solution that effectively answers the user's question.
- When using group aggregations (unique groups), always set `math_group_type_index` to the appropriate group type index from the group mapping.
- Custom names for series or steps are optional and should only be used when the user explicitly wants to rename them or when the default name would be unclear.
- Visualization settings (display type, axis format, etc.) should only be specified when explicitly requested or when they significantly improve the answer to the user's question.
- The default funnel step order is `ordered` (events in sequence but with other events allowed in between). Use `strict` when events must happen consecutively with no events in between. Use `unordered` when order doesn't matter.
- Exclusion events in funnels only exclude conversions where the event happened between the specified steps, not before or after the funnel.

# Summary

1. Select an insight type
2. Follow the guidelines and create a structured plan
3. Pass the structured plan and insight type to this tool.
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

InsightType = Literal["trends", "funnel", "retention"]


class CreateAndQueryInsightToolArgs(MaxToolArgs):
    query_description: str = Field(description="A plan of the query to generate based on the template.")
    insight_type: InsightType = Field(description="The type of insight to generate.")


class CreateAndQueryInsightTool(MaxTool):
    name: Literal["create_and_query_insight"] = "create_and_query_insight"
    args_schema: type[BaseModel] = CreateAndQueryInsightToolArgs
    description: str = INSIGHT_TOOL_PROMPT
    context_prompt_template: str = INSIGHT_TOOL_CONTEXT_PROMPT_TEMPLATE
    thinking_message: str = "Coming up with an insight"

    async def _arun_impl(
        self, query_description: str, insight_type: InsightType, tool_call_id: str
    ) -> tuple[str, ToolMessagesArtifact | None]:
        graph_builder = InsightsGraph(self._team, self._user)
        match insight_type:
            case "trends":
                graph_builder.add_trends_generator().add_edge(
                    AssistantNodeName.START, AssistantNodeName.TRENDS_GENERATOR
                )
            case "funnel":
                graph_builder.add_funnel_generator().add_edge(
                    AssistantNodeName.START, AssistantNodeName.FUNNEL_GENERATOR
                )
            case "retention":
                graph_builder.add_retention_generator().add_edge(
                    AssistantNodeName.START, AssistantNodeName.RETENTION_GENERATOR
                )

        graph = graph_builder.add_query_executor().compile()
        new_state = self._state.model_copy(
            update={
                "root_tool_call_id": tool_call_id,
                "plan": query_description,
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
                id=tool_call_message.id,
                tool_call_id=tool_call_message.tool_call_id,
                visible=self.show_tool_call_message,
            )

        return "", ToolMessagesArtifact(messages=[maybe_viz_message, tool_call_message])

    @classmethod
    def is_editing_mode(cls, context_manager: AssistantContextManager) -> bool:
        """
        Determines if the tool is in editing mode.
        """
        return AssistantTool.CREATE_AND_QUERY_INSIGHT.value in context_manager.get_contextual_tools()
