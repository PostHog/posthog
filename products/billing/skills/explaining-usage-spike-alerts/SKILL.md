---
name: explaining-usage-spike-alerts
description: >
  Explains PostHog billing usage spike, drop, and change alert emails.
  Use when the user asks why they got "We've detected a change in your usage",
  follows a usage alert CTA, asks Max to explain a spike alert for specific usage
  types or dates, or asks whether a billing usage alert was real or noisy.
  Reconstructs the alert from usage-dashboard filters, compares the alert day to
  weekday/weekend baselines, attributes the delta by project, and drills into
  billable sources only when the product supports it.
---

# Explaining usage spike alerts

Use this skill for the narrow "why did I get this billing usage alert?" workflow.
The goal is to explain the alert, not to run a broad cost review. For generic bill,
spend, plan, or optimization questions, use `investigating-billing-costs`.

Spike alerts can fire for usage increases, drops, or changes. Treat "spike" in user
prompts as shorthand for any alert direction unless the prompt clearly says increase.

## Available tools

| Tool                             | Purpose                                                                 |
| -------------------------------- | ----------------------------------------------------------------------- |
| `posthog:billing-list`           | Org billing context, subscribed products, team names, and usage summary |
| `posthog:billing-usage-retrieve` | Time-series usage by day, usage type, and team                          |
| `posthog:billing-spend-retrieve` | Optional spend context when the user asks about dollars                 |
| `posthog:execute-sql`            | Product-specific drilldown after the alert day and project are known    |

Read `references/spike-alert-mechanics.md` when you need detector thresholds, URL
parameter meanings, or usage type mappings.

## Inputs to look for

Alert context usually comes from a usage dashboard URL or a Max prompt generated from
that URL. Extract:

- `usage_types`: JSON array of billing usage type identifiers, for example `["event_count_in_period"]`
- `date_to`: the alert day shown at the right edge of the usage chart
- `date_from`: the start of the chart window, usually about 29 days before `date_to`
- `interval`: normally `day`
- Product or usage type names from the email copy or prompt

If the usage type or alert day is missing, ask for the alert email, dashboard link, or
the date/product from the alert. Do not guess the exact metric from a vague "my usage
changed" prompt.

## Workflow

### Step 1. Recreate the alert view

Call `posthog:billing-usage-retrieve` using the alert parameters:

- `start_date`: `date_from`
- `end_date`: `date_to`
- `interval`: `day`
- `usage_types`: the parsed `usage_types`
- `breakdowns`: `["type","team"]`

If the response shape makes the total hard to read, make a second call with
`breakdowns: ["type"]`. Keep the window anchored on the alert link unless you need a
small extension to compare against the same weekday/weekend class.

Call `posthog:billing-list` for context, product names, plan state, docs links, and
team name hints. Do not use `usage_summary` as the source of truth for the alert,
because it only reflects the current billing period.

### Step 2. Explain why it fired

Treat `date_to` as the alert day. Compare that day to prior days in the same day class:

- weekday alert day: compare to prior weekdays in the visible range
- weekend alert day: compare to prior weekend days in the visible range

Prefer this over comparing only to yesterday. The detector normalizes against separate
weekday/weekend baselines, so weekend traffic can look normal next to Friday but still
be unusual compared with previous weekends.

Report:

- direction: higher, lower, or changed
- alert day value
- same-class baseline
- absolute delta and ratio, when the values make the math meaningful
- whether this is an exact detector result or a reconstruction from the dashboard data

### Step 3. Attribute the change by project

Use the `team` breakdown to find where the alert came from. For each team, compare the
alert day to that team's same-class baseline for the same usage type. Rank contributors
by absolute delta in the alert direction.

If one project explains most of the movement, say that plainly. If the movement is
spread across many projects, say it is diffuse and avoid over-crediting the largest
project.

### Step 4. Drill down only where the product supports it

Run `posthog:execute-sql` only after you know the usage type, team, and day to inspect.
Scope SQL to the exact team and day whenever possible.

For events, query top billable event names for the affected project and day. Exclude
events billed under other products:

```sql
SELECT event, count() AS c
FROM events
WHERE team_id = {team_id}
  AND timestamp >= {window_start}
  AND timestamp < {window_end}
  AND event NOT IN (
    '$feature_flag_called', '$exception',
    'survey sent', 'survey shown', 'survey dismissed',
    '$ai_generation', '$ai_embedding', '$ai_span', '$ai_trace', '$ai_metric',
    '$ai_feedback', '$ai_evaluation',
    '$ai_trace_summary', '$ai_generation_summary',
    '$ai_trace_clusters', '$ai_generation_clusters'
  )
GROUP BY event
ORDER BY c DESC
LIMIT 20
```

For identified events, top raw event names can explain the volume change, but they may
not exactly explain the identified/anonymous billing split unless that dimension is
available in the billing response.

For feature flag requests, remember the billable metric is `/flags` API requests, not
`$feature_flag_called` events. Do not recommend disabling `$feature_flag_called` to
reduce feature flag request usage.

For recordings, mobile recordings, exceptions, surveys, LLM usage, data warehouse,
CDP, logs, and workflows, start with the usage-dashboard series and team attribution.
Only drill into raw data when there is a reliable product-specific source for that
usage type.

### Step 5. Answer in alert language

Structure the response around the alert, not around a generic analytics investigation:

1. Why you got this
2. Where it came from
3. Is it concerning?
4. What to check next

Be honest about noisy alerts. If the alert is mathematically valid but likely caused by
a normal weekend pattern, holiday, campaign, batch job, or other expected cycle, say
that. If the dashboard data does not support the alert, say that too and suggest
checking the exact email date, product filter, or longer history window.
