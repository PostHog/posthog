INSIGHT_RESULT_TEMPLATE = """
Name: {{{insight_name}}}
{{#insight_id}}
Insight ID: {{{insight_id}}}
{{/insight_id}}
{{#insight_description}}
Description: {{{insight_description}}}
{{/insight_description}}
{{#insight_url}}
Insight URL: {{{insight_url}}}
{{/insight_url}}
{{^insight_url}}
This insight cannot be accessed via a URL.
{{/insight_url}}
{{#query_schema}}

Query schema:
```json
{{{query_schema}}}
```
{{/query_schema}}
{{#results}}

{{{results}}}
{{/results}}
""".strip()


QUERY_RESULTS_PROMPT = """
Here is the results table of the {{{query_kind}}} insight:

```
{{{results}}}
```

{{#insight_schema}}
Here is the insight schema used to retrieve the results above:
```json
{{{insight_schema}}}
```

{{/insight_schema}}
<system_reminder>
The current date and time is {{{utc_datetime_display}}} UTC, which is {{{project_datetime_display}}} in this project's timezone ({{{project_timezone}}}).
{{#sql_query}}
Always add `LIMIT 100` to your queries. The maximum allowed limit is 500 rows. If you need more data, paginate using LIMIT and OFFSET in subsequent queries.
{{/sql_query}}
It's expected that the data point for the current period may show a drop in value, as data collection for it is still ongoing. Do not point this out.
Do not copy the results table as the user sees it in the UI.{{#include_url_reminder}}
{{/include_url_reminder}}
{{#has_truncated_values}}
Some JSON/array values were truncated. You can write a more specific SQL query to explore individual properties or array elements if needed.
{{/has_truncated_values}}
</system_reminder>
""".strip()

TRENDS_EXAMPLE_PROMPT = """
You are given a table with the results of a trends query. Values are separated by the pipe character "|" and rows are separated by newlines. The first row is the header row with series names received from the query. The first column is the date, and the rest are the values for each series.

Example:
```
Date|$pageview|sign up
2025-01-20|242|46
2025-01-21|120|13
```
""".strip()

SQL_QUERY_PROMPT = """
Here is the generated HogQL (a PostHog's subset of ClickHouse SQL) query used to retrieve the results:

```
{query}
```
""".strip()

FUNNEL_STEPS_EXAMPLE_PROMPT = """
You are given a table with the results of a funnel query. Values are separated by the pipe character "|" and rows are separated by newlines. The first column is the metric name, and the rest are the values for each metric. The first row is the header row with series names received from the query. Rows can be separated by a line with "---", indicating a series with a breakdown. For example, `---control` indicates that the series is for the value `control`.

Example:
```
Metric|$pageview|sign up
Total person count|100|50
Conversion rate|100%|50%
Dropoff rate|0%|50%
Average conversion time|-|1d
Median conversion time|-|1d
```
""".strip()

FUNNEL_TIME_TO_CONVERT_EXAMPLE_PROMPT = """
You are given a table with the results of a time-to-convert funnel query. Values are separated by the pipe character "|" and rows are separated by newlines. The first column is the average time to convert, and the rest are the distribution values for users who converted in the given period.

Example:
```
Events: $pageview -> sign up
Average time to convert|User distribution
3m|70%
4m|30%
```
""".strip()

FUNNEL_TRENDS_EXAMPLE_PROMPT = """
You are given a table with the results of a funnel query tracking conversion rates over time. Values are separated by the pipe character "|" and rows are separated by newlines. The first column is the metric name, and the rest are the values for each metric. The first row is the header row with series names received from the query and associated metrics: conversion and drop-off rates. Series can have a breakdown indicated by a word `breakdown` in the name.

Example:
```
Date|$pageview -> sign up conversion|$pageview -> sign up drop-off
2025-01-05|20%|80%
2025-01-12|91%|9%
```
""".strip()


LIFECYCLE_EXAMPLE_PROMPT = """
You are given a table with the results of a lifecycle query. Values are separated by the pipe character "|" and rows are separated by newlines. The first row is the header row. The first column is the date, and the remaining columns show the count of users in each lifecycle status for that period: New (first-time users), Returning (active in the previous period), Resurrecting (returning after inactivity), and Dormant (previously active but inactive, shown as negative values). If the query has multiple event series, each series is shown in a separate section with an "Event:" header.

Important: for event and action series, lifecycle queries only include users with person profiles. Events with `$process_person_profile: false` are excluded entirely; these come from anonymous users on SDKs configured with `person_profiles: 'identified_only'`, the default in posthog-js. Data warehouse series are not affected by this exclusion.

Example:
```
Date|New|Returning|Resurrecting|Dormant
2025-10-01|6936|29541|13263|-16735
2025-11-01|7101|30794|12662|-18946
```
""".strip()

PATHS_EXAMPLE_PROMPT = """
You are given a table with the results of a paths query. Values are separated by the pipe character "|" and rows are separated by newlines. The first row is the header row. Each row represents an edge in the user path graph, showing the source step, target step, the number of users who traversed that edge, and the average time to convert between steps. Source and target values are prefixed with their step number (e.g., "1_/home" means step 1 at "/home").

Example:
```
Source|Target|Users|Avg. conversion time
1_/home|2_/pricing|150|2m 30s
1_/home|2_/docs|80|1m 15s
2_/pricing|3_/signup|120|45s
2_/docs|3_/signup|40|3m
```
""".strip()

RETENTION_EXAMPLE_PROMPT = """
You are given a matrix with the results of a retention query. Values are separated by the pipe character "|" and rows are separated by newlines. The first row is the header row with series names received from the query. The first column is the date, the second column is the count of persons who completed the action on that date, and the rest are the retention values for each day relative to the following days.

Example:
```
Date|Number of persons on date|Day 0|Day 1|Day 2|Day 3
2024-01-28|489|100%|90%|80%|70%
2024-01-29|309|100%|90%|80%
2024-01-30|987|100%|50%
2024-01-31|148|100%
```
""".strip()

SQL_EXAMPLE_PROMPT = """
You are given a table with the results of a SQL query. Values are separated by the pipe character "|" and rows are separated by newlines. The first row is the header row with column names. The other rows are the results of the query.

Example:
```
column1|column2|column3
value1|value2|value3
value4|value5|value6
```
""".strip()

STICKINESS_EXAMPLE_PROMPT = """
You are given a table with the results of a stickiness query. Values are separated by the pipe character "|" and rows are separated by newlines. The first row is the header row with series names received from the query. The first column is the interval (number of days/weeks the event was performed), and the rest are the values for each series.

Example:
```
Interval|$pageview|signup
1 day|200|100
2 days|150|120
3 days|100|80
```
""".strip()

BOX_PLOT_EXAMPLE_PROMPT = """
You are given a table with the results of a box plot query showing statistical distributions of a numeric property over time. Values are separated by the pipe character "|" and rows are separated by newlines. The first row is the header row. Each row shows the distribution statistics for a date period: minimum, 25th percentile (P25), median, 75th percentile (P75), maximum, and mean.

Example:
```
Date|Min|P25|Median|P75|Max|Mean
2025-01-20|1.2|5.5|12.3|25.8|100.4|18.7
2025-01-21|0.8|4.2|10.1|22.5|95.2|16.3
```
""".strip()

FALLBACK_EXAMPLE_PROMPT = "You'll be given a JSON object with the results of a query."
