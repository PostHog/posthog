QUERY_RESULTS_PROMPT = """
Here's the query I came up with:

```json
{{{query}}}
```

And here are the results:

```json
{{{results}}}
```

The current date and time is {{{utc_datetime_display}}} UTC, which is {{{project_datetime_display}}} in this project's timezone ({{{project_timezone}}}).
It's expected that the data point for the current period can have a drop in value, as it's not complete yet.
"""
