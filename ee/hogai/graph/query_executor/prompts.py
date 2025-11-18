QUERY_RESULTS_PROMPT = """
Here is the results table of the {{{query_kind}}} I created to answer your latest question:

```
{{{results}}}
```

<system_reminder>
The current date and time is {{{utc_datetime_display}}} UTC, which is {{{project_datetime_display}}} in this project's timezone ({{{project_timezone}}}).
{{#currency}}
Assume currency values are in {{currency}} and ALWAYS include the proper prefix when displaying values that are likely to be currency values.
{{/currency}}
It's expected that the data point for the current period may show a drop in value, as data collection for it is still ongoing. Do not point this out.
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

REVENUE_ANALYTICS_GROSS_REVENUE_EXAMPLE_PROMPT = """
You are given a table with the gross revenue results for a given period as specified. The results might be broken down by different values (e.g. product name, country, etc.). In the table, values are separated by the pipe character "|" and rows are separated by newlines. The first row is the header row with the different sources and breakdowns. The other rows are the results of the query.
When referencing these numbers, make sure you're using the proper currency prefix based on the project's base currency.

Example:
```
Gross revenue for period: 2024-11-01 to 2025-02-01
Breakdown by revenue_analytics_product.name
Date|stripe.posthog_test - Product F|stripe.posthog_test - Product E
2024-11-01|647.24356|64.24353
2024-12-01|2507.2184|207.2432
```
"""

REVENUE_ANALYTICS_METRICS_EXAMPLE_PROMPT = """
You are given a table with some metrics revenue results for a given period. We include results for total/new/churned subscriptions and customers and also ARPU and LTV. The results might be broken down by different values (e.g. product name, country, etc.). In the table, values are separated by the pipe character "|" and rows are separated by newlines. The first row is the header row with the different sources and breakdowns. The other rows are the results of the query.
For LTV, if there are no customers, the value is set to N/A. If there are customers but none has churned, the value is set to 0.
When referencing these numbers, make sure you're using the proper currency prefix based on the project's base currency.

Example:
```
Revenue metrics for period: 2024-11-01 to 2025-02-01
Breakdown by revenue_analytics_product.name

Subscription Count
Date|stripe.posthog_test - Product E|stripe.posthog_test - Product F
2024-11-01|0|1
2024-12-01|0|2

New Subscription Count
Date|stripe.posthog_test - Product E|stripe.posthog_test - Product F
2024-11-01|0|0
2024-12-01|0|1

Churned Subscription Count
Date|stripe.posthog_test - Product E|stripe.posthog_test - Product F
2024-11-01|0|0
2024-12-01|0|0

Customer Count
Date|stripe.posthog_test - Product E|stripe.posthog_test - Product F
2024-11-01|0|1
2024-12-01|0|2

New Customer Count
Date|stripe.posthog_test - Product E|stripe.posthog_test - Product F
2024-11-01|0|0
2024-12-01|0|1
"2025-01-01|3|1
"2025-02-01|3|1

Churned Customer Count
Date|stripe.posthog_test - Product E|stripe.posthog_test - Product F
2024-11-01|0|0
2024-12-01|0|0

ARPU
Date|stripe.posthog_test - Product E|stripe.posthog_test - Product F
2024-11-01|212.51292|152.235
2024-12-01|277.54371|215.3234

LTV
Date|stripe.posthog_test - Product E|stripe.posthog_test - Product F
2024-11-01|25.5|N/A
2024-12-01|0|0
```
"""

REVENUE_ANALYTICS_MRR_EXAMPLE_PROMPT = """
You are given a table with the gross revenue results for a given period as specified. The results might be broken down by different values (e.g. product name, country, etc.). In the table, values are separated by the pipe character "|" and rows are separated by newlines. The first row is the header row with the different sources and breakdowns. The other rows are the results of the query.
Besides total MRR, we also include results for new, expansion, contraction and churn MRR.
When referencing these numbers, make sure you're using the proper currency prefix based on the project's base currency.

Example:
```
MRR metrics for period: 2024-11-01 to 2025-02-01
Breakdown by revenue_analytics_product.name

Total MRR
Date|stripe.posthog_test - Product C|stripe.posthog_test - Product D
2024-11-30|5.75833|5.325
2024-12-31|24.35234|4.335
2025-01-31|19.96086|19.865
2025-02-28|9.84295|19.845

New MRR
Date|stripe.posthog_test - Product C|stripe.posthog_test - Product D
2024-11-30|0|0
2024-12-31|5.75833|5.7325
2025-01-31|18.59401|18.01
2025-02-28|0|0

Expansion MRR
Date|stripe.posthog_test - Product C|stripe.posthog_test - Product D
2024-11-30|0|0
2024-12-31|0|0
2025-01-31|0|8.38045
2025-02-28|8.38045|25.12

Contraction MRR
Date|stripe.posthog_test - Product C|stripe.posthog_test - Product D
2024-11-30|0|0
2024-12-31|-4.39147|-45.391
2025-01-31|-18.49837|-1.497
2025-02-28|0|0

Churned MRR
Date|stripe.posthog_test - Product C|stripe.posthog_test - Product D
2024-11-30|0|0
2024-12-31|0|0
2025-01-31|0|0
2025-02-28|0|0
```
"""

REVENUE_ANALYTICS_TOP_CUSTOMERS_EXAMPLE_PROMPT = """
You are given a table with the results of a revenue analytics top customers query. Values are separated by the pipe character "|" and rows are separated by newlines. The first row is the header row with the different sources and breakdowns. The other rows are the results of the query.
The results might be grouped by month or a total sum for the whole period. The table will specify the grouping.
When referencing these numbers, make sure you're using the proper currency prefix based on the project's base currency.

Example 1 - grouped by month:
```
Top customers for period: 2024-11-01 to 2025-02-01
Grouped by month
Customer Name|2025-02-01|2025-03-01
John Doe|5.23615|73.23614
Jane Doe|26.01009|84.0101
John Doe Jr Jr|668.67503|864.03
Jane Smith|85.47825|84.25
John Smith|615.99731|814.915
John Doe Jr|1105.82156|8104.56
```

Example 2 - grouped by all:
```
Top customers for period: 2024-11-01 to 2025-02-01
Customer Name|Revenue
John Doe Jr|1105.82156
John Doe Jr Jr|668.67503
John Smith|615.99731
Jane Smith|85.47825
Jane Doe|26.01009
John Doe|5.23615
```
"""

FALLBACK_EXAMPLE_PROMPT = "You'll be given a JSON object with the results of a query."
