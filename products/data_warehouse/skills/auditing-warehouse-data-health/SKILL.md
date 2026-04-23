---
name: auditing-warehouse-data-health
description: >
  Audit the health of a PostHog project's data warehouse — find every broken or degraded pipeline item across
  sources, sync schemas, materialized views, batch exports, and transformations. Use when the user asks "what's
  broken in my warehouse?", "give me a health check", "audit my data pipeline", "why are some dashboards stale?",
  or wants a one-shot triage summary before deciding where to spend time. Produces a prioritized report of issues
  grouped by severity and type, with recommended next steps.
---

# Auditing data warehouse health

This skill produces a project-wide audit of the data warehouse pipeline. Use it when the user wants a **summary of
everything broken**, not a deep-dive on one sync. The deep-dive on individual failures is
`diagnosing-failed-warehouse-syncs`; this skill is the scan that tells them where to look first.

## When to use this skill

- "What's broken in my warehouse?" / "Give me a health check"
- "Audit my data pipeline"
- The user is new to a project and wants to know what they've inherited
- Weekly or monthly review of pipeline health
- Dashboards are stale and the user isn't sure which source is at fault

## Available tools

| Tool                                          | Purpose                                                             |
| --------------------------------------------- | ------------------------------------------------------------------- |
| `data-warehouse-data-health-issues-retrieve`  | One-shot: all failed/degraded items across the whole pipeline       |
| `external-data-sources-list`                  | All sources with status and latest error                            |
| `external-data-schemas-list`                  | All schemas with status, last_synced_at, latest_error               |
| `view-list`                                   | All saved queries / materialized views with status and latest_error |
| `view-run-history`                            | Run history for a specific materialized view                        |
| `external-data-sources-webhook-info-retrieve` | Check per-source webhook state (not covered by data-health-issues)  |

The `data-health-issues` endpoint already aggregates across materializations, sync schemas, sources, batch export
destinations, and transformations — it's the fastest path to a summary. Use the list endpoints when you need more
context than the summary provides (row counts, non-failing items, schema-level detail).

## What counts as an "issue"

The data-health endpoint returns items from five categories:

| `type`               | Trigger                                                                                                                                       | Typical urgency |
| -------------------- | --------------------------------------------------------------------------------------------------------------------------------------------- | --------------- |
| `source`             | `ExternalDataSource.status = Error` — whole source connection broken                                                                          | High            |
| `external_data_sync` | schema in Failed or BillingLimitReached state (the data-health endpoint returns `status: "failed"` or `status: "billing_limit"` respectively) | Medium–High     |
| `materialized_view`  | `DataWarehouseSavedQuery.is_materialized=true, status=Failed`                                                                                 | Medium          |
| `destination`        | Batch export's latest run is FAILED / FAILED_RETRYABLE / TIMEDOUT / TERMINATED                                                                | Medium          |
| `transformation`     | HogFunction transformation in DISABLED / DEGRADED / FORCEFULLY\_\* state                                                                      | Low–Medium      |

Each entry includes `id`, `name`, `type`, `status`, `error`, `failed_at`, `url`, and (for syncs/sources)
`source_type`.

Note the data-health endpoint only reports _active failures_. It doesn't flag:

- Schemas paused by the user (`should_sync = false`)
- Non-materialized views with errors (only materialized views are reported)
- Schemas that are slow or stale but technically `Completed`
- **Webhook problems on `sync_type: "webhook"` schemas.** The bulk-sync safety net can succeed while the webhook
  push channel is silently broken (deregistered, disabled on the remote side, failing signature verification).
  These don't surface in `data-health-issues` — check per-source with `webhook-info-retrieve`.

If the user asks about staleness or unused items, reach beyond this endpoint — see Step 4.

## Workflow

### Step 1 — One-shot pull

Call `data-warehouse-data-health-issues-retrieve`. This returns every actively failing item in one request.

If the response is empty, tell the user their pipeline is healthy and stop. Don't invent problems.

### Step 2 — Group and prioritize

Group the issues by `type` and sort within each group by severity:

1. **Sources in Error first.** A source failure cascades — every schema under it is effectively dead until the
   source reconnects. Fix these first.
2. **Sync schemas next**, in this order:
   - `status: "billing_limit"` entries (billing issue, non-technical — flag and route to billing)
   - `Failed` on heavily-used tables (user asks / check row counts via schemas-list if needed)
   - `Failed` on less-used tables
3. **Materialized views.** Usually independent of sources — a view failure is a HogQL or data issue in the view
   itself.
4. **Batch export destinations.** Affect data going _out_ of PostHog — important but generally not blocking reads.
5. **Transformations.** Affect ingestion. Flag separately since these are HogFunction issues, not warehouse syncs.

### Step 3 — Present the audit

Render a prioritized report. Don't dump the raw JSON — human-readable table per category:

```text
## Data warehouse health — 7 issues

### 🔴 Sources (1)
- Stripe — authentication failed (failed 2h ago)
  → `diagnosing-failed-warehouse-syncs` on this source

### 🟠 Sync schemas (3)
- postgres_prod.orders (Failed 6h ago) — column "updated_at" does not exist
- postgres_prod.invoices (Failed 6h ago) — column "updated_at" does not exist
- hubspot.contacts (BillingLimitReached) — team quota exceeded

### 🟠 Materialized views (2)
- monthly_revenue — view failed (syntax error in HogQL)
- active_users_30d — view failed (missing table reference)

### 🟡 Destinations (1)
- S3 export "daily-events" (FAILED_RETRYABLE 3 runs in a row)

Recommended order:
1. Stripe auth (everything under it is dead)
2. Schema-drift on postgres_prod.orders / invoices — looks like upstream renamed a column
3. Billing limit on hubspot
4. Materialized views (independent — can be tackled any time)
```

The exact format is less important than: prioritized, grouped, actionable, and hinting at the right next skill.

### Step 4 — Go beyond active failures (when asked)

If the user wants more than just "what's on fire" — e.g. "what else should I look at?" — cross-check:

**Stale but "Completed" schemas:**
Call `external-data-schemas-list` and look for schemas with old `last_synced_at` relative to their `sync_frequency`.
A schema on `1hour` frequency that last synced 3 days ago is effectively broken even if status says `Completed`.

**Unused materialized views:**
Call `view-list`. Materialized views cost storage and compute every run. If any are marked materialized but haven't
been queried lately, surface them — `cleaning-up-stale-warehouse-views` territory (not yet implemented, but the data
is available).

**Sources with zero sync activity:**
Sources where every schema has `should_sync: false` or `status = Paused`. These were set up and then abandoned —
candidates for cleanup via `external-data-sources-destroy`.

**Broken webhooks on webhook-type schemas:**
Iterate the sources that have any schema with `sync_type: "webhook"` (visible via `external-data-schemas-list`). For
each, call `external-data-sources-webhook-info-retrieve({source_id})`:

- `exists: false` while a schema is `sync_type: "webhook"` → webhook was never registered, or was deleted. Push
  channel is dead; only the bulk fallback is ingesting.
- `external_status.error` present → remote service is reporting a problem (permission revoked, endpoint
  deleted on their dashboard).
- `external_status.status` not `"enabled"` → remote has disabled the endpoint (often after repeated delivery
  failures).

Report these separately from the primary audit — they're a different shape of problem than the other categories,
and the fix is a different skill (`diagnosing-failed-warehouse-syncs` scenario I, or
`setting-up-a-data-warehouse-source` step 5.5).

Only run these extra checks if the user explicitly asks for a broader audit — they involve more tool calls and
heuristics.

### Step 5 — Offer the next step

End the audit with a clear hand-off:

- "Want me to dig into the Stripe failure?" → hands off to `diagnosing-failed-warehouse-syncs`
- "Want me to fix the schema drift on orders?" → hands off to `tuning-incremental-sync-config`
- "Want to disable the billing-capped schemas?" → one-click via `external-data-schemas-partial-update`

Never start applying fixes autonomously from an audit — the audit's job is to report and recommend, not remediate.
Any fix should be confirmed explicitly before executing.

## Example interaction

```text
User: "Check the health of our data warehouse"

Agent:
- data-warehouse-data-health-issues-retrieve → 4 items
   [{type: "source", name: "Stripe", error: "401 Unauthorized", ...},
    {type: "external_data_sync", name: "postgres_prod.orders",
     error: "column \"updated_at\" does not exist", ...},
    {type: "materialized_view", name: "monthly_revenue",
     error: "syntax error at or near \"FORM\"", ...},
    {type: "destination", name: "S3 daily-events", error: "AccessDenied", ...}]

- Report:
  "Found 4 issues in your data warehouse:

   🔴 Sources (1)
   - Stripe — auth failure 2h ago (401). All 8 tables under it are currently dead.

   🟠 Sync schemas (1)
   - postgres_prod.orders — column `updated_at` was dropped on the source side,
     incremental sync can't find it.

   🟠 Materialized views (1)
   - monthly_revenue — HogQL syntax error ('FORM' instead of 'FROM').

   🟡 Destinations (1)
   - S3 export 'daily-events' — access denied on write.

   Suggest fixing in this order:
   1. Stripe credentials (unblocks everything under it)
   2. orders incremental-field drift
   3. monthly_revenue typo
   4. S3 permissions

   Want me to start on Stripe?"
```

## Important notes

- **The audit is read-only.** Never call destructive tools from the audit flow. Hand off to the diagnosis/tuning
  skills — which in turn confirm before acting.
- **Empty = healthy.** Don't pad an empty audit with hypothetical issues. "No issues found" is a good answer.
- **Source failures cascade.** When reporting a source in Error, also mention which schemas under it are affected
  (or will be, once they try to sync again). The user needs to understand the blast radius.
- **Billing limits aren't technical problems.** Flag them but route to billing / quota discussion, not to a
  recovery action.
- **Transformation issues are separate.** HogFunctions aren't warehouse syncs — they show up in the audit because
  they're part of the broader pipeline, but they live in the `posthog` ingestion side. Route those to pipeline
  skills rather than trying to fix in-place here.
- **`data-health-issues` only surfaces active failures.** For staleness, unused views, or abandoned sources, you
  need to cross-check the list endpoints. Only do this when the user explicitly asks for a deeper audit.
- **Webhook health is separate from schema health.** The data-health endpoint doesn't know about webhook state.
  When a user's request mentions "real-time", "Stripe webhook", or "why is data hours behind on a webhook
  source", go straight to `webhook-info-retrieve` rather than inferring from schema status.
