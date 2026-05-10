---
name: explaining-billing-usage-changes
description: >
  Explains focused PostHog billing usage spikes, drops, and unusual usage changes.
  Use when the user asks what caused a usage spike or drop for a product/date,
  asks why they got "We've detected a change in your usage", follows a usage
  alert CTA, asks PostHog AI to explain a billing usage change, or asks whether a
  usage alert was real or noisy. Compares the day to weekday/weekend baselines,
  attributes the delta by project, and drills into billable sources only when the
  product supports it.
---

# Explaining billing usage changes

Use this skill for focused "what caused this billing usage change?" workflows. The
question may come from an alert email, a usage dashboard link, a PostHog AI prompt, or
a user who noticed a spike/drop themselves. The goal is to explain the usage movement,
not to run a broad cost review. For generic bill, spend, plan, or optimization
questions, use `investigating-billing-costs`.

Spike alerts can fire for usage increases, drops, or changes. Treat "spike" in user
prompts as shorthand for any alert direction unless the prompt clearly says increase.

## Available tools

| Tool                             | Purpose                                                                 |
| -------------------------------- | ----------------------------------------------------------------------- |
| `posthog:billing-list`           | Org billing context, subscribed products, team names, and usage summary |
| `posthog:billing-usage-retrieve` | Time-series usage by day, usage type, and team                          |
| `posthog:billing-spend-retrieve` | Optional spend context when the user asks about dollars                 |
| `posthog:execute-sql`            | Product-specific drilldown after the alert day and project are known    |

Read `references/spike-alert-mechanics.md` when you need alert detector thresholds,
URL parameter meanings, or usage type mappings.

## Inputs to look for

The best input is a usage dashboard URL, but the skill should also work from a product
name and date in a normal user prompt. Extract whatever is available:

- `usage_types`: JSON array of billing usage type identifiers, for example `["event_count_in_period"]`
- `date_to`: the alert day shown at the right edge of the usage chart
- `date_from`: the start of the chart window, usually about 29 days before `date_to`
- `interval`: normally `day`
- Product or usage type names from the email copy, dashboard, or prompt

If the usage type is missing but the user named a product, map it to the closest billing
usage type and say what you inferred. If the date is missing, pull the last 30 days and
look for the most obvious candidate day. Only ask for more context when the prompt is too
vague to choose a product or time window.

## Workflow

### Step 1. Recreate the focused usage view

Call `posthog:billing-usage-retrieve` using the dashboard or prompt parameters:

- `start_date`: `date_from`, or about 30 days before the suspected change
- `end_date`: `date_to`, the named date, or today if the user did not name a date
- `interval`: `day`
- `usage_types`: the parsed or inferred `usage_types`, or omit if the product is unclear
- `breakdowns`: `["type","team"]`

If the response shape makes the total hard to read, make a second call with
`breakdowns: ["type"]`. Keep dashboard-linked investigations anchored on the provided
date range unless you need a small extension to compare against the same weekday/weekend
class.

Call `posthog:billing-list` for context, product names, plan state, docs links, and
team name hints. Do not use `usage_summary` as the source of truth for the alert,
because it only reflects the current billing period.

### Step 2. Explain why the day looks unusual

If `date_to` came from an alert link, treat it as the alert day. Otherwise identify the
suspected spike/drop day from the prompt or the most obvious outlier in the series.
Compare that day to prior days in the same day class:

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
- whether this is an exact alert explanation or a reconstruction from usage data

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

### Step 5. Answer in focused usage-change language

Structure the response around the usage change, not around a generic analytics
investigation:

1. What changed
2. Where it came from
3. Is it concerning?
4. What to check next

Be honest about noisy alerts. If the alert is mathematically valid but likely caused by
a normal weekend pattern, holiday, campaign, batch job, or other expected cycle, say
that. If the dashboard data does not support the alert, say that too and suggest
checking the exact email date, product filter, or longer history window.
