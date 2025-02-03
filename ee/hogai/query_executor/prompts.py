QUERY_RESULTS_PROMPT = """
{example}

Here is the results table of the {query_kind} I created to answer your latest question:

```
{results}
```

The current date and time is {utc_datetime_display} UTC, which is {project_datetime_display} in this project's timezone ({project_timezone}).
It's expected that the data point for the current period can have a drop in value, as it's not complete yet.
""".strip()

TRENDS_EXAMPLE_PROMPT = """
You will be given a table with the results of a trends query. Values are separated by the pipe character "|" and rows are separated by newlines. The first row is the header row with series names received from the query. The first column is the date, and the rest are the values for each series.

Example:
```
Date|$pageview|sign up
2025-01-20|242|46
2025-01-21|120|13
```
""".strip()


FUNNELS_EXAMPLE_PROMPT = """
You will be given a table with the results of a funnel query. Values are separated by the pipe character "|" and rows are separated by newlines. The first column is the metric name, and the rest are the values for each metric. The first row is the header row with series names received from the query. Rows can be separated by a line with "---", indicating a series with a breakdown. For example, `---control` indicates that the series is for the value `control`.

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


RETENTION_EXAMPLE_PROMPT = """
You will be given a matrix with the results of a retention query. Values are separated by the pipe character "|" and rows are separated by newlines. The first row is the header row with series names received from the query. The first column is the date, the second column is the count of persons who completed the action on that date, and the rest are the retention values for each day relative to the following days.

Example:
```
Date|Number of persons on date|Day 0|Day 1|Day 2|Day 3
2024-01-28|489|100%|90%|80%|70%
2024-01-29|309|100%|90%|80%
2024-01-30|987|100%|50%
2024-01-31|148|100%
```
""".strip()

FALLBACK_EXAMPLE_PROMPT = "You'll be given a JSON object with the results of a query."
