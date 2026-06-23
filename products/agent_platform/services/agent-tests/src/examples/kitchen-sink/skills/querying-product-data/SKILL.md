---
description: Answering questions from PostHog product data via `@posthog/query` (HogQL) and the curated PostHog MCP tools — picking the right surface, common rollups (events, persons, costs), and how this runs AS the linked user (so unlinked → a connect link, not an error). Load whenever the user asks about their analytics, events, flags, or LLM spend.
---

# Querying product data

You can read a team's PostHog data two ways. Pick the lighter one.

## Two surfaces

1. **`@posthog/query` — raw HogQL.** Maximum power, for anything ad-hoc:
   custom aggregations, event breakdowns, person filters. You write
   SQL-ish HogQL and get rows back.
2. **The `posthog__*` MCP tools — curated.** Higher-level, typed,
   safer for common asks. Prefer these when one fits:
   - `posthog__docs-search` — "how do I…" PostHog product questions.
   - `posthog__insights-get-all` / `posthog__insight-query` — existing
     insights.
   - `posthog__dashboards-get-all` / `posthog__dashboard-get`.
   - `posthog__feature-flag-get-all`, `posthog__experiment-get-all`,
     `posthog__error-tracking-list-issues`.
   - `posthog__execute-sql` — the MCP's own SQL path.
   - `posthog__get-llm-total-costs-for-project` — LLM spend rollup.
   - `posthog__projects-get` / `posthog__switch-project`.

Rule of thumb: **a curated tool if one matches the ask; `@posthog/query`
when you need a shape no curated tool gives you.** Don't hand-roll HogQL
for "list my dashboards."

## Which project?

`@posthog/*` and the MCP act within a project. In console sessions, call
`get_context` to read the user's current `project_id`. If you're acting
across projects, `posthog__switch-project` first. Don't assume project 1.

## You run AS the user

Both surfaces use the **`posthog` identity provider** — they execute
with the asking user's own token and scopes (`query:read`,
`insight:read`, `dashboard:read`, …). Consequence:

- If the user **hasn't linked**, the call comes back `link_required`,
  **not** an error. Load **`acting-as-you`** and hand them a connect
  link via `@posthog/identity-connect`. Don't report "I can't access
  your data" — report "link your PostHog account and I'm in."
- You only see what _they_ can see. A scope they don't have → a clean
  "you'd need X access," not a crash.

## Common rollups (HogQL starting points)

- **Event volume, last 24h:**
  `SELECT count() FROM events WHERE timestamp > now() - INTERVAL 1 DAY`
- **Top events:**
  `SELECT event, count() AS c FROM events WHERE timestamp > now() - INTERVAL 7 DAY GROUP BY event ORDER BY c DESC LIMIT 20`
- **Active persons:**
  `SELECT count(DISTINCT person_id) FROM events WHERE timestamp > now() - INTERVAL 7 DAY`
- **Errors:** filter `event = '$exception'`, or use
  `posthog__error-tracking-list-issues` for the triaged view.

> Person-on-events caveat: `person.properties.*` on the events table
> reflect the value _at ingest time_, not the person's current value.
> Don't promise "current" person state from an events query.

## Answer like an analyst, not a database

Lead with the number and what it means ("~1.2M events/day, flat WoW"),
then offer the query or a deeper cut. Don't dump a raw result table when
a sentence answers the question.
