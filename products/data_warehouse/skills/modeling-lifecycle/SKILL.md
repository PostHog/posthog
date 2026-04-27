---
name: modeling-lifecycle
description: >
  End-to-end workflow for building a data warehouse model on top of PostHog data
  and synced warehouse tables — discover available inputs, profile candidate
  columns, author HogQL, save as a view, validate against real data, optionally
  materialize, and monitor. Use when the user says "build me an MRR model", "I
  need a view for active accounts", "create a saved query for X", "model our
  subscription data", or any other request that ends in a new
  `DataWarehouseSavedQuery`. Also covers iterating on an existing model and the
  rules around when (and when not) to materialize.
---

# Modeling lifecycle

Use this skill any time the user asks for a new data warehouse model, or wants to iterate on an existing one. The
short version of the lifecycle:

```text
discover → profile → author → save → validate → (materialize) → monitor
```

The whole point is that each phase makes the next one cheaper. Skipping discovery leads to redundant models;
skipping profiling leads to HogQL that's syntactically valid but semantically wrong; skipping validation leads to
materialized garbage. Don't shortcut.

## When to use this skill

- "Build me an MRR / ARR / churn / activation / retention model"
- "Create a saved query for X"
- "I need a view that joins Stripe customers to PostHog persons"
- "Update the active_users view to include trial users"
- The user already has views and wants a new one composed from them
- The user has a one-off HogQL query they keep re-running and wants to persist it

If the user instead wants to _connect a new data source_, hand off to `setting-up-a-data-warehouse-source`. If a
sync is failing, hand off to `diagnosing-failed-warehouse-syncs`. If they want to change how an existing source
syncs, hand off to `tuning-incremental-sync-config`. This skill picks up _after_ the data is in PostHog.

## Available tools

| Tool                                         | Phase            | Purpose                                                                    |
| -------------------------------------------- | ---------------- | -------------------------------------------------------------------------- |
| `posthog:read-data-warehouse-schema`         | Discover         | Enumerate every queryable table (events, persons, synced sources, views)   |
| `external-data-sources-list`                 | Discover         | Which external sources are connected and healthy                           |
| `external-data-schemas-list`                 | Discover         | Which tables under each source are syncing, with last sync time            |
| `view-list`                                  | Discover         | Existing saved queries — short-circuit if one already covers the ask       |
| `view-get`                                   | Discover         | Full SQL + columns + run history for one saved query                       |
| `posthog:execute-sql`                        | Profile / Author | Run ad-hoc HogQL — sample rows, count distinct, validate a draft query     |
| `view-create`                                | Save             | Persist a HogQL query as a saved view                                      |
| `view-update`                                | Iterate          | Change SQL or sync_frequency on an existing view (needs concurrency token) |
| `view-materialize`                           | Materialize      | Create a physical table + 24h refresh schedule for a view                  |
| `view-unmaterialize`                         | Materialize      | Revert materialization, keep the view                                      |
| `view-run`                                   | Materialize      | Trigger a one-off refresh of a materialized view                           |
| `view-run-history`                           | Monitor          | Last 5 materialization runs with status                                    |
| `data-warehouse-data-health-issues-retrieve` | Monitor          | Surface model failures across the project                                  |

## Workflow

### Step 1 — Discover what's already there

Always start with discovery. Building a model that duplicates an existing one is the most common avoidable mistake.

1. `view-list` filtered to the domain (`mrr`, `revenue`, `subscription`, `active_users`, etc.). If something close
   already exists, read it with `view-get` and propose extending it instead of creating a parallel model.
2. `posthog:read-data-warehouse-schema` to see every table available — native (events, persons, sessions, groups),
   warehouse-synced (with prefixes), and existing views. Note which source prefixes show up: `stripe_*`,
   `hubspot_*`, `postgres_prod_*`, etc.
3. `external-data-sources-list` and `external-data-schemas-list` if you need to confirm a source is healthy and
   actively syncing the candidate table — a stale source means a stale model.

If the data the user needs isn't connected at all, stop here and hand off to `suggesting-data-imports` and
`setting-up-a-data-warehouse-source`. Do not invent table names.

### Step 2 — Profile the candidate inputs

This is the step most agents skip and most users regret. The schema tells you `amount: Numeric`. It does not tell
you that 40% of rows have `amount = 0`, that there are 12 distinct currencies, or that `status` is mostly
`succeeded` but also includes `pending`, `refunded`, and a long tail of nulls. Without profiling, you write
technically-valid HogQL against columns you've never seen.

Use `posthog:execute-sql` to answer at least these questions before drafting:

- **Sample rows.** `SELECT * FROM stripe_charges ORDER BY created DESC LIMIT 20` — what do real rows look like?
- **Distinct values for low-cardinality columns.** `SELECT status, count() FROM stripe_charges GROUP BY status`
- **Null rate on columns you plan to filter or aggregate.**
  `SELECT countIf(amount IS NULL) / count() FROM stripe_charges`
- **Range / shape of numeric columns.** `SELECT min(amount), max(amount), quantile(0.5)(amount) FROM stripe_charges`
- **Currencies / units / timezones, if relevant.** `SELECT currency, count() FROM stripe_charges GROUP BY 1`
- **Join cardinality before declaring a join.**
  `SELECT count() FROM stripe_customers WHERE email IS NULL` and the matching test on `persons.properties.$email`.
  A join key with a 30% match rate produces a model that silently drops a third of the data.

Profiling is also where layering choices get made — if a source column is wildly inconsistent (mixed-case status
values, dirty currencies), you'll want a staging layer that cleans it before any aggregate touches it. See
`layering-warehouse-models` for the conventions.

### Step 3 — Author the HogQL

Write the query in your head (or in a scratchpad), then validate it with `posthog:execute-sql` _before_ calling
`view-create`. A failed `view-create` leaves nothing behind, but a successful create with a logically wrong query
pollutes the model namespace and is easy to forget about.

Validation checklist:

1. **Run it with a `LIMIT 100`.** Does it return rows? Are the columns the right shape?
2. **Run a row-count sanity check.** Does the row count match an order-of-magnitude expectation given the inputs?
   A model that "joins customers to invoices" that returns 10x the invoice count means your join fans out.
3. **Spot-check a few well-known rows.** If the user mentioned a specific account/customer, find them in the
   output and confirm the numbers match what they'd expect.
4. **If the query has aggregates, also run the un-aggregated version on a small slice** to make sure the inputs
   look right before you trust the output.

If a query fails with a HogQL error, fix it before calling `view-create`. Don't save broken queries hoping to fix
them later.

### Step 4 — Save as a view

Once the query is validated, persist it with `view-create`:

```json
{
  "name": "stg_stripe__invoices",
  "query": { "kind": "HogQLQuery", "query": "SELECT ..." }
}
```

Naming matters — this view will be referenced by name in every downstream query for as long as it exists. Follow
the conventions in `layering-warehouse-models` (`raw_<source>__<table>`, `stg_<source>__<entity>`,
`int_<grain>`, `final_<domain>`).

After save, `view-get` to confirm the inferred column schema matches what you expected. Surface the column list to
the user — they'll often spot something missing immediately.

### Step 5 — Iterate

If the user wants changes, `view-update` is partial — only send the fields that change.

- **Always retrieve before update.** Get the current `latest_history_id` via `view-get`, then pass it as
  `edited_history_id` on the update. This prevents clobbering a concurrent edit (someone in the UI, a parallel
  agent run). On a 409 conflict, refresh and re-plan rather than retrying blindly.
- **Re-validate after every SQL change.** Run the new query with `posthog:execute-sql` against the stored view
  before assuming the change worked. A view-update succeeds whether the query is right or wrong.
- **If the view is materialized,** be mindful: changing the query will require a re-run. Surface the cost to the
  user before pushing a SQL change to a materialized model.

### Step 6 — Materialize (when appropriate)

`view-materialize` builds a physical table from the view's query and refreshes it on a 24-hour schedule (use
`view-update` with `sync_frequency` to change the cadence). Materialization typically makes queries fast but
costs storage and compute on every refresh. It is often the right balance to materialize intermediate or final
models but not staging models.

**Only materialize what's directly queried by users or dashboards.** Staging (and sometimes intermediate) layers should stay
virtual — they're cheap to recompute on demand and materializing them adds cost for the user without speeding up
the things people actually run.

Defaults to use:

| Layer     | Materialize? | Cadence                                      |
| --------- | ------------ | -------------------------------------------- |
| `raw_*`   | Never        | (synced tables already)                      |
| `stg_*`   | No           | (virtual)                                    |
| `int_*`   | Rarely       | If the query is expensive and reused widely  |
| `final_*` | Usually yes  | `24hour` default; `1hour` if dashboard-bound |

Before flipping `view-materialize` on:

1. Confirm the view's query is settled (Step 5 — no pending changes).
2. Estimate cost mentally — number of input rows × frequency. A `1hour` materialization of a query that scans
   100M rows is expensive; ask the user to confirm before enabling.
3. Set the cadence to match the upstream freshness. There's no point materializing every hour off a Stripe sync
   that runs every 6 hours.

`view-materialize` is rate-limited. If you get a 429, back off and explain rather than retrying immediately.

To revert, `view-unmaterialize` always works and is the safety valve. Mention this every time you materialize so
the user knows there's a graceful exit.

### Step 7 — Monitor

After a model is in use, the lifecycle is "did it run, and is it still right?":

- `view-run-history` for materialized views — last 5 runs with status. Failures here mean the schedule is broken
  and downstream queries are reading stale data.
- `data-warehouse-data-health-issues-retrieve` for the project-wide view of failures (your model + everything
  else). If the user asks "is X up to date?" this is the right tool, not staring at view-list.
- `view-get` exposes `latest_error` and `last_run_at` directly, useful when investigating one model.

If a materialized view is failing, hand off to `auditing-warehouse-data-health` for triage, then to
`diagnosing-failed-warehouse-syncs` for source-level issues or back to Step 5 for query-level issues.

## A worked example: "build me MRR"

Compressed transcript of the canonical greenfield flow.

```text
User: "Can you set up an MRR model from our Stripe data?"

Agent:
1. view-list({search: "mrr"}) → no results
   view-list({search: "revenue"}) → no results
   posthog:read-data-warehouse-schema → confirms stripe_charges, stripe_customers,
   stripe_invoices, stripe_subscriptions are present

2. external-data-schemas-list → all four stripe schemas Completed,
   last_synced within the hour. Healthy inputs.

3. Profile:
   - posthog:execute-sql "SELECT * FROM stripe_subscriptions LIMIT 10"
     → confirm columns: id, customer_id, status, current_period_start/_end, items, ...
   - posthog:execute-sql "SELECT status, count() FROM stripe_subscriptions GROUP BY 1"
     → mostly active + canceled, smaller tail of past_due / trialing / incomplete
   - posthog:execute-sql "SELECT currency, count() FROM stripe_invoices GROUP BY 1"
     → 95% USD, 4% EUR, 1% GBP — agent flags multi-currency to the user before drafting

4. Drafted SQL for stg_stripe__subscriptions (clean enum values, cast period dates).
   posthog:execute-sql "<draft SQL with LIMIT 100>" → returns the expected shape.
   view-create({name: "stg_stripe__subscriptions", ...}). view-get → schema confirmed.

5. Drafted int_subscription_daily (one row per active subscription per day,
   currency-converted to USD). Validated with execute-sql, view-create, view-get.

6. Drafted final_mrr (daily MRR, MoM growth, by plan). Validated, view-create, view-get.

7. Discussed materialization with user. final_mrr → view-materialize at 24hour cadence.
   stg_* and int_* stay virtual. Surfaced view-unmaterialize as the rollback.

8. view-run → first manual refresh. view-run-history → confirmed Completed.
   Reported the three view names + the materialize toggle to the user.
```

## Important notes

- **Profile before you author.** The schema is not enough context. Sample rows and distinct value distributions
  are what tell you whether your draft query is right.
- **Validate before you save.** `view-create` is happy to persist garbage. Run the SELECT through `execute-sql`
  with a LIMIT first.
- **Validate before you update, too.** `view-update` does not re-check the query. Run the new SQL against the
  stored view and confirm the result before moving on.
- **Always thread `edited_history_id` on updates.** Otherwise concurrent edits silently overwrite each other.
- **Materialize sparingly.** Only the layer the user actually queries. Materializing the whole DAG is the most
  common cost mistake.
- **Tell the user about `view-unmaterialize` whenever you materialize.** It's the rollback they didn't know they
  had, and it's always available.
- **Don't invent inputs.** If the table the user named isn't in `read-data-warehouse-schema`, ask — don't
  hallucinate a column or assume a synced table will appear later.
- **Hand off, don't reinvent.** Source setup → `setting-up-a-data-warehouse-source`. Sync failures →
  `diagnosing-failed-warehouse-syncs`. Naming / layer choices → `layering-warehouse-models`. Health audit →
  `auditing-warehouse-data-health`.
