QUERY_RESULTS_PROMPT = """
Here is the results table of the {query_kind} I created to answer your latest question:

```
{results}
```

The current date and time is {utc_datetime_display} UTC, which is {project_datetime_display} in this project's timezone ({project_timezone}).
It's expected that the data point for the current period can have a drop in value, as data collection is still ongoing for it. Do not point this out.
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

FALLBACK_EXAMPLE_PROMPT = "You'll be given a JSON object with the results of a query."
