---
name: querying-canvas-data
description: >
  Get PostHog data into a canvas correctly: the host-injected `ph` SDK (loadInsight, query,
  capture, openExternal, navigate), the data hierarchy (saved insights first, typed query nodes
  second, inline HogQL last), per-insight-type result shapes, date-range wiring, and event capture
  from a canvas. Use whenever a canvas shows metrics, charts, tables, or any PostHog data, or
  needs to send analytics events.
---

# Querying canvas data

The global `ph` object (injected by the host — never imported, never initialized) is the only way
a canvas talks to PostHog. Credentials stay in the host; `fetch()`, posthog-js, and hand-rolled
clients fail in the sandbox.

## Data hierarchy — back every metric with a saved insight

1. **Preferred — save an insight, load it by reference.** Use the PostHog MCP insight tools to
   create/save an insight that computes the metric with an insight query type (TrendsQuery,
   FunnelsQuery, RetentionQuery, PathsQuery, or the web-analytics kinds WebOverviewQuery /
   WebStatsTableQuery — not raw SQL). Confirm its numbers, note the `short_id`, and render it with
   `await ph.loadInsight(shortId, { dateRange })`. These are proven queries — numbers match the
   PostHog UI exactly (sessionization, unique users, breakdowns, bounce rate). Never fabricate a
   query or guess event/property names; discover and save them via MCP first.
2. **Secondary — an ad-hoc typed node**: `ph.query({ kind: "TrendsQuery", series: [...], dateRange: {...} })`
   when saving an insight genuinely doesn't fit.
3. **Last resort — inline HogQL**: `ph.query("SELECT …")`, only when no insight kind can express
   the metric; you then own the SQL and its date window.

For web-analytics boards specifically, use the web-analytics query kinds — raw HogQL subtly gets
bounce rate, sessionization, channel attribution, and unique-visitor counts wrong.

Whatever tier you use, **declare it in the project's `capabilities`** before publishing: every
`ph.loadInsight` short id in `capabilities.posthog.insights`, every `ph.capture` event name in
`captureEvents`, and `inlineQueries: true` for any `ph.query` use. The host rejects undeclared
calls at runtime, and validation fails on undeclared literals.

## Result shapes — read them correctly or every value renders 0

- **Trends-style results** (insight query types, via `ph.loadInsight` or a typed node): `results`
  is an array of **series objects**, not rows. Each series has `data: number[]` (per interval),
  `days: string[]` (ISO), `labels: string[]`, `count` (sum), `aggregated_value` (single-value
  total), `label`, and optional `compare_label: "current" | "previous"`. A KPI total is
  `results[0].count` (or `.aggregated_value`); a line chart plots `results[0].data` over
  `results[0].days`. With a compare period, find the prior series by `compare_label === "previous"`
  — never by index. `columns` is empty here.
- **SQL results**: `{ columns: string[], results: rows[][] }` — each row an array of cell values in
  `columns` order.

Load data in `useEffect` with `useState`, show a loading state, and handle empty/error. Aggregate
in the query; never fetch raw event dumps.

## Date windows

- Pass the canvas's date-picker window straight into `dateRange`:
  `ph.loadInsight(shortId, { dateRange: { date_from: win.start.toISOString(), date_to: win.end.toISOString() } })`
  — the saved insight re-scopes to the window with no time SQL. Typed nodes take the same
  `dateRange`. Re-run every query when the window changes.
- A saved **SQL** insight may ignore `dateRange` (its window lives inside the SQL) — a reason to
  prefer insight query types.
- Inline HogQL escape hatch only: never bake `now()` or a hardcoded INTERVAL. Compute unix bounds
  (`Math.floor(win.start.getTime() / 1000)`) and write half-open
  `timestamp >= toDateTime(fromUnix) AND timestamp < toDateTime(toUnix)`. Prior period = the
  equal-length window immediately before; bucket with `toStartOfDay`/`toStartOfHour`.

## Side effects

- `ph.capture(event, properties?, distinctId?)` — analytics events for interactions
  (fire-and-forget). Session replay, `$session_id`, and person attribution are handled by the
  host automatically; never roll your own capture.
- `ph.openExternal(url)` — opens `https://posthog.com` / `*.posthog.com` URLs only, and only from
  a user interaction (opens outside focus are ignored). Don't link elsewhere.
- `ph.navigate.toTask(id)` / `.toNewTask()` / `.toCanvas(id)` / `.toNewCanvas()` — in-app
  navigation within the canvas's own channel.
