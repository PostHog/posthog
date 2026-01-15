# Trends Guidelines

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

## General Knowledge

Trends insights enable users to plot data from people, events, and properties however they want. They're useful for finding patterns in data, as well as monitoring users' product to ensure everything is running smoothly. Users can use multiple independent series in a single query to see trends. They can also use a formula to calculate a metric. Each series has its own set of property filters, so you must define them for each series. Trends insights do not require breakdowns or filters by default.

## Aggregation

**Determine the math aggregation** the user is asking for, such as totals, averages, ratios, or custom formulas. If not specified, choose a reasonable default based on the event type (e.g., total count). By default, the total count should be used. You can aggregate data by events, event's property values, or users. If you're aggregating by users or groups, there's no need to check for their existence, as events without required associations will automatically be filtered out.

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
- `average` by the `$session_duration` property to find out what was the average session duration of an event.
- `99th percentile by users` to find out what was the 99th percentile of the event count by users.

## Math Formulas

If the math aggregation is more complex or not listed above, use custom formulas to perform mathematical operations like calculating percentages or metrics. If you use a formula, you must use the following syntax: `A/B`, where `A` and `B` are the names of the series. You can combine math aggregations and formulas.

When using a formula, you must:

- Identify and specify **all** events and actions needed to solve the formula.
- Carefully review the list of available events and actions to find appropriate entities for each part of the formula.
- Ensure that you find events and actions corresponding to both the numerator and denominator in ratio calculations.

Examples of using math formulas:

- If you want to calculate the percentage of users who have completed onboarding, you need to find and use events or actions similar to `$identify` and `onboarding complete`, so the formula will be `A / B * 100`, where `A` is `onboarding complete` (unique users) and `B` is `$identify` (unique users).
- To calculate conversion rate: `A / B * 100` where A is conversions and B is total events
- To calculate average value: `A / B` where A is sum of property and B is count

## Time Interval

Specify the time interval (group by's by time) in the `Time interval` section on the plan. Available intervals are: `hour`, `day`, `week`, `month`.

Unless the user has specified otherwise, use the following default interval:

- If the time period is less than two days, use the `hour` interval.
- If the time period is less than a month, use the `day` interval.
- If the time period is less than three months, use the `week` interval.
- Otherwise, use the `month` interval.

## Breakdowns

Breakdowns are used to segment data by property values of maximum three properties. They divide all defined trends series to multiple subseries based on the values of the property. Include breakdowns **only when they are essential to directly answer the user's question**. You must not add breakdowns if the question can be addressed without additional segmentation. Always use the minimum set of breakdowns needed to answer the question.

When using breakdowns, you must:

- **Identify the property group** and name for each breakdown.
- **Provide the property name** for each breakdown.
- **Validate that the property value accurately reflects the intended criteria**.

Examples of using breakdowns:

- page views trend by country: you need to find a property such as `$geoip_country_code` and set it as a breakdown.
- number of users who have completed onboarding by an organization: you need to find a property such as `organization name` and set it as a breakdown.

## Plan Template

```
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
```
