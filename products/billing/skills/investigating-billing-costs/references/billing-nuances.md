# Billing nuances

Non-obvious facts about how PostHog bills that the agent should know before explaining
costs to a customer. Each of these trips up first-time analyzers.

## Events excluded from the billable events product

Several events are **dropped at usage-report time** and never counted toward the events
product bill. Source of truth: `get_teams_with_billable_event_count_in_period` in
`posthog/tasks/usage_report.py`.

- `$feature_flag_called` — billed under `feature_flag_requests` (see next section)
- `$exception` — billed under error tracking
- `survey sent`, `survey shown`, `survey dismissed` — billed under surveys. Note the event
  names use spaces and have no `$` prefix.
- AI analytics events — billed under `llm_analytics` / `ai_credits`:
  - `$ai_generation`, `$ai_embedding`, `$ai_span`, `$ai_trace`, `$ai_metric`
  - `$ai_feedback`, `$ai_evaluation`
  - `$ai_trace_summary`, `$ai_generation_summary`, `$ai_trace_clusters`,
    `$ai_generation_clusters`

**Practical consequence**: when drilling into raw `events` in ClickHouse to explain an
events-product bill, always filter these out, or at minimum flag them separately in your
summary. A raw `SELECT event, count() FROM events GROUP BY event` will overstate billable
volume by whatever slice is flag-evaluations / survey events / AI traces — and recommending
"disable `$feature_flag_called` capture" to lower the events bill is wrong advice (the
event isn't in the events bill to begin with).

Canonical SQL shape for a billable-events drill-down:

```sql
SELECT event, count() AS c
FROM events
WHERE team_id = {team_id}
  AND timestamp >= {start} AND timestamp < {end}
  AND event NOT IN (
    '$feature_flag_called', '$exception',
    'survey sent', 'survey shown', 'survey dismissed',
    '$ai_generation', '$ai_embedding', '$ai_span', '$ai_trace', '$ai_metric',
    '$ai_feedback', '$ai_evaluation',
    '$ai_trace_summary', '$ai_generation_summary',
    '$ai_trace_clusters', '$ai_generation_clusters'
  )
GROUP BY event ORDER BY c DESC LIMIT 20
```

## Feature flags are billed by `/flags` requests, not events

Feature flag cost comes from `/flags` endpoint requests (for flag evaluation), NOT from
`$feature_flag_called` events. The event is optional. If the customer has disabled the event
but is still making flag requests, they are still being billed.

This matters because:

- "Stop sending `$feature_flag_called`" does NOT reduce flag costs
- Reducing flag costs requires reducing evaluation requests (local evaluation, bootstrapping,
  disabling on first load, etc.)

## Identified events cost 4x anonymous events

In product analytics, identified events (those with a `distinct_id` that has been associated
with a user via `identify()`) are priced at 4x the rate of anonymous events. If a spike is
specifically in identified events, the relevant question is "does every event actually need
to be identified".

## Quota limit reset takes 15-30 minutes

After a customer increases or removes their custom spending limit, the limit does not reset
immediately. The quota-limiting job runs every 15 minutes, so it can take up to 30 minutes
for the new limit to take effect. If the customer just changed limits and expects immediate
results, warn them about this.

## Startup program distorts the picture

If `billing_context.startup_program_label` is set, the customer is getting credits under
PostHog's startup program. Their effective cost does not fully reflect their usage until
the program expires. When analyzing spend:

- Normal cost-reduction tactics still work, but the urgency is lower
- Tell the customer the program's expiry date and what their bill might look like then

## `autocapture` is the single biggest event-volume driver on most accounts

PostHog captures `$autocapture`, `$pageview`, `$pageleave`, `$rageclick`, etc. automatically.
On a typical account these account for 60-80% of event volume. Before suggesting any of the
subtler cost reductions, always verify what fraction of the customer's events are
autocapture-generated.

## Projections vs current usage

`billing-list` returns both `total_current_amount_usd` (period-to-date) and
`projected_total_amount_usd` (forecast for the full period). When a customer says "my bill
is too high", clarify whether they mean:

- Their period-to-date charge so far
- The projected total they'll pay at the end of the period
- The bill they already received for a previous period

Spike investigation is most useful for case 1 and 2. For case 3, the data is in
`billing-list.previous_bills` or in Stripe, not in the usage/spend endpoints.
