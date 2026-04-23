---
name: investigating-billing-costs
description: >
  Investigates PostHog billing costs and usage patterns. Use when the user asks why
  their bill is high, what drove their spend, whether they can reduce costs, to
  understand what they are paying for, investigate a usage spike, review plan
  headroom, or any similar cost or billing question. Walks through: pull billing
  context, pull time-series usage and spend, identify interesting patterns (spikes,
  growth trends, one-project dominance, unused capacity, approaching limits),
  attribute to projects and event types, and surface data-grounded cost reduction
  tactics or upsell opportunities drawn from the billing docs.
---

# Investigating billing costs

A broad cost and usage investigation workflow: why is my bill high, what am I paying
for, is my usage growing, can I reduce costs, are there addons I am wasting, are
there products I should add. All of these start from the same data (billing snapshot
plus time-series usage and spend) and branch based on what the data shows.

## Available tools

| Tool                             | Purpose                                                                        |
| -------------------------------- | ------------------------------------------------------------------------------ |
| `posthog:billing-list`           | Org-level billing snapshot: products, addons, plan, limits, available features |
| `posthog:billing-usage-retrieve` | Time-series usage breakdowns by day, usage type, and team                      |
| `posthog:billing-spend-retrieve` | Time-series spend breakdowns (dollar amounts) with the same dimensions         |
| `posthog:execute-sql`            | Ad-hoc HogQL for drilling into specific events in a project                    |

See `references/usage-data-shape.md` for the exact response shapes and history-item structure.

## When to use

Trigger this skill when the user asks anything like:

- "why is my bill higher than last month"
- "what's driving my PostHog costs"
- "can you help me reduce our PostHog spend"
- "which project uses the most events"
- "we had a usage spike on Thursday, what happened"
- "our invoice jumped, walk me through it"
- "what am I paying for"
- "do I have headroom against my limits"
- "are there addons I'm not using"
- "should I upgrade my plan"

If the question is narrowly about billing _structure_ ("what's on my plan", "do I have
access to group analytics", "when does my period renew") and doesn't need time-series
data, `billing-list` alone is usually enough and this skill is overkill.

## Workflow

Follow these steps in order. Each builds on the previous. Do not skip steps.

### Step 1. Pull billing context

Call `posthog:billing-list`. This establishes:

- Which products are subscribed (decide which usage types are worth investigating)
- Plan tier, billing period, startup program
- `available_product_features` (confirms what the customer has access to before suggesting anything)
- Current period aggregate usage from `usage_summary` and any custom spending limits
- Trial state and projected total

**Heads up: `usage_summary` reflects the CURRENT billing period only.** If the customer's
billing period just rolled over (check `billing_period.current_period_start` against today),
`usage_summary` will be all zeros. That is expected on day zero of a new cycle. Always pull
the time-series via `billing-usage-retrieve` to see the prior period's story.

If `billing-list` returns `has_active_subscription: false`, the customer is on the free
plan. Most cost investigations are moot; focus on whether they are approaching limits.

### Step 2. Pull the time-series

Call `posthog:billing-usage-retrieve` with reasonable defaults:

- `start_date`: 30 days ago (or further back if the user references a specific period)
- `end_date`: today
- `interval`: `day` unless the range is long enough that `week` reads better
- `breakdowns`: `["type","team"]` to get per-product-per-project decomposition in one call
- `usage_types`: omit for all types, OR scope to what the customer actually uses (see step 1)

If the user specifically mentions cost rather than volume, call
`posthog:billing-spend-retrieve` instead (or additionally). Same parameter shape.

### Step 3. Scan for interesting patterns

The pattern in the data tells you what story to tell. Look for:

- **Sharp spike**: a single day (or short window) much higher than adjacent days. The user
  likely noticed this already and wants explanation.
- **Sustained growth**: a steady upward trend over weeks. Customer scaling up, no incident,
  but worth discussing forecasts and limit headroom.
- **Step change**: a new, higher plateau starting on a specific date. Often correlates
  with a deploy, marketing push, or new customer onboard.
- **One-project dominance**: one team accounts for the bulk of a product's usage. Worth
  calling out for attribution or consolidation.
- **Unused capacity**: a subscribed addon with zero or near-zero usage. Candidate to
  remove (revenue-down), but worth confirming first whether the customer just hasn't
  rolled it out yet.
- **Approaching a limit**: aggregate usage at 80%+ of a custom or plan limit. Important
  to surface even if the customer didn't ask.

If nothing jumps out, say so honestly. Offer to look at a longer range or a different
product. Don't fabricate a spike.

See `references/usage-data-shape.md` for how to read `UsageHistoryItem.dates` and `data`
arrays and how to interpret `breakdown_value` when multiple breakdowns are requested.

### Step 4. Attribute to a project

For the product that stood out, find the contributing project using the `team` breakdown.
If the `team_ids` in `breakdown_value` are unfamiliar, look them up from `team_id_options`
in the response, the user's current session context, or ask the user which project name
maps to the ID.

### Step 5. Drill into specific events (events usage only)

If the standout product is Events (product analytics), call `posthog:execute-sql` to find
the top contributing event names for the suspect project and time window.

**Before writing the query, read `references/billing-nuances.md` §"Events excluded from
the billable events product"** and exclude those events from the query. Otherwise the
top-N will be dominated by events that are billed under other products (flag calls,
survey events, AI traces, exceptions) — and the recommendations that follow will be
wrong (e.g. "disable `$feature_flag_called` capture" does not reduce the events bill).

Canonical billable-events drill-down:

```sql
SELECT event, count() AS c
FROM events
WHERE team_id = {team_id}
  AND timestamp >= {window_start} AND timestamp < {window_end}
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

Among remaining events, `$autocapture` and `$pageview`/`$pageleave` are the most common
cost drivers on a typical account.

For non-events products (recordings, feature flag requests, etc.), the `execute-sql`
drill-down is less useful. Skip to step 6.

### Step 6. Summarize and suggest

Produce a response that states:

1. What the data shows (pattern type, magnitude, time range, products involved)
2. Where it comes from (which project, which specific events if applicable)
3. What the customer can do about it, or confirms (if nothing to act on)

For the third part, pull relevant tactics from `references/cost-reduction-strategies.md`.
Do not recite the whole list. Only include strategies that match the data you just
observed. "Your `$autocapture` count is 80% of your events, and you could reduce that by
setting up an allow/ignore list" is useful. "Here's a generic list of cost tips" is not.

## Honesty rule

Investigations often surface opportunities BOTH to reduce spend AND to use more of
PostHog. Play both sides honestly:

- If the customer is paying for a capability they are not using, say so.
- If the customer would benefit from a feature they don't have, suggest it.
- Do not systematically push spend up or spend down. The credible answer is the one that
  matches their data.

When suggesting a PostHog product or addon, always include a link to the relevant docs
page. The `billing-list` response includes `docs_url` on each product and addon.

## References

- `references/cost-reduction-strategies.md` — per-product cost reduction playbook with docs links
- `references/usage-data-shape.md` — response shape for `billing-list`, `billing-usage-retrieve`, `billing-spend-retrieve`
- `references/billing-nuances.md` — non-obvious billing facts (special events, flag billing model, quota timing)
