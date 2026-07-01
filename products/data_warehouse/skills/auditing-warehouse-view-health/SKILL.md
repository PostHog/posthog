---
name: auditing-warehouse-view-health
description: >
  Audit the health of a PostHog project's materialized views (saved queries) — find every failed materialization and
  flag unused or stale materialized views that cost storage and compute. Use when the user asks "which of my views are
  broken?", "why is this materialized view failing?", "are any of my views wasting compute?", or wants a one-shot
  triage of view health. For source/sync health use `auditing-warehouse-source-health`.
---

# Auditing data warehouse view health

This skill produces a project-wide audit of **materialized views** (materialized saved queries) in the data warehouse
— which ones are failing, and which are materialized but unused. Use it when the user wants a summary of view health,
not a deep-dive on one failure.

The health-issues tools report every kind of health check in the project, not just views — source-sync failures,
ingestion warnings, outdated SDKs, web-analytics setup gaps, and more. Source and sync health is covered by
`auditing-warehouse-source-health`. The other health-check kinds are owned by other products — surface them if they
appear, but route them to the relevant team rather than diagnosing here.

## When to use this skill

- "Which of my views are broken?" / "Why is this materialized view failing?"
- "Are any of my materialized views wasting compute?"
- Reviewing view health after a HogQL or schema change
- Dashboards backed by materialized views are stale or erroring

## Available tools

| Tool                    | Purpose                                                                          |
| ----------------------- | -------------------------------------------------------------------------------- |
| `health-issues-summary` | One-shot: active health-issue counts by `kind` and `severity` across the project |
| `health-issues-list`    | Active health issues, filterable by `kind`, `severity`, `status`, `dismissed`    |
| `health-issues-get`     | One issue's full `payload` plus trusted `remediation` (`human` + `agent`)        |
| `view-list`             | All saved queries / materialized views with status and latest_error              |
| `view-run-history`      | Run history for a specific materialized view                                     |

Call `health-issues-summary` for the one-shot counts, then `health-issues-list` with `kind=materialized_view_failure`
for the failing views (always pass `status=active` and `dismissed=false` — the list does **not** default-exclude
resolved or dismissed issues), and `health-issues-get` for a single issue's `remediation`. Use `view-list` when you
need more than the active-failure summary (non-failing views, materialization flags, last-queried info) and
`view-run-history` to see the run trail for a specific view.

## What counts as a view "issue"

From the health-issues tools, this audit cares about a single `kind`:

| `kind`                      | Trigger                                                                | Typical severity |
| --------------------------- | ---------------------------------------------------------------------- | ---------------- |
| `materialized_view_failure` | A saved query failed to materialize (`status=Failed` or a build error) | `warning`        |

Each issue carries a top-level `kind`, `severity` (`critical`/`warning`/`info`), and `status` (`active`/`resolved`),
plus a check-specific `payload` (`pipeline_name`, `pipeline_id`, `error`). `health-issues-get` adds a human `title`,
`summary`, `link`, and trusted `remediation`.

The other `kind`s the health checks return are out of scope for this skill:

- `external_data_failure` (source/sync failures) → `auditing-warehouse-source-health`
- setup-health kinds (`sdk_outdated`, `ingestion_warning`, `web_vitals`, `reverse_proxy`, …) → owned by the relevant
  product (growth / ingestion / web analytics); route, don't diagnose here

Note the health checks only report _active failures_. For views they don't flag:

- Non-materialized views with errors (only materialized views are reported)
- Materialized views that are healthy but unused (costing compute every run) — see Step 4

## Workflow

### Step 1 — One-shot pull

Call `health-issues-summary` for the by-`kind` counts, then `health-issues-list` with
`kind=materialized_view_failure`, `status=active`, `dismissed=false` to pull the failing views. Use
`health-issues-get` on any issue whose `remediation` you want to relay.

If there are no `materialized_view_failure` issues, tell the user their materialized views are healthy and stop.
Don't invent problems.

### Step 2 — Triage failures

Materialized view failures are usually independent of sources — a view failure is a HogQL or data issue in the view
itself (syntax error, missing table reference, type mismatch). For each failing view, surface the `error` and point
at the offending query. Use `view-run-history` if the user wants the failure trail.

### Step 3 — Present the audit

Render a prioritized report. Don't dump the raw JSON — human-readable:

```text
## Materialized view health — 2 issues

### 🟠 Materialized views (2)
- monthly_revenue — view failed (syntax error in HogQL: 'FORM' instead of 'FROM')
- active_users_30d — view failed (missing table reference)

Both are HogQL issues in the view definitions — independent of your sources. Want me to open one?
```

### Step 4 — Go beyond active failures (when asked)

**Unused materialized views:**
Call `view-list`. Materialized views cost storage and compute every run. If any are marked materialized but haven't
been queried lately, surface them as cleanup candidates (the data is available via `view-list`; unmaterialize via
`view-unmaterialize`).

Only run this extra check if the user explicitly asks for a broader audit.

### Step 5 — Offer the next step

End the audit with a clear hand-off — e.g. "Want me to open `monthly_revenue` and fix the HogQL?" Never apply fixes
autonomously from an audit; confirm explicitly before editing or unmaterializing a view.

## Important notes

- **The audit is read-only.** Never call destructive tools (e.g. `view-unmaterialize`, `view-delete`) from the audit
  flow without explicit confirmation.
- **Empty = healthy.** Don't pad an empty audit with hypothetical issues. "No view issues found" is a good answer.
- **View failures are usually self-contained.** Unlike source failures, a failed materialized view rarely cascades —
  it's a query problem in that view. Don't imply a broader outage.
- **Sources, syncs, and setup-health kinds are out of scope here.** They surface through the same health-issues
  tools but belong to other audits/products — route, don't diagnose.
