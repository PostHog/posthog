---
name: querying-canvas-data
description: >
  Get PostHog data into a canvas correctly: the host-injected `ph` SDK (loadInsight, query,
  capture, state, openExternal, navigate), the data hierarchy (saved insights first, typed query nodes
  second, inline HogQL last), verifiability (insight-backed metrics link their saved insight in
  PostHog; ad-hoc queries expose the exact query that ran), per-insight-type result shapes,
  progressive per-query loading, date-range wiring, and event capture from a canvas. Use whenever a
  canvas shows metrics, charts, tables, or any PostHog data, or needs to send analytics events.
---

# Querying canvas data

The global `ph` object (injected by the host — never imported, never initialized) is the only way
a canvas talks to PostHog. Credentials stay in the host; `fetch()`, posthog-js, and hand-rolled
clients cannot reach PostHog from the sandbox. External requests and resources require a non-PostHog
origin declared in `capabilities.network.origins`, and work only in the published canvas — the
edit-mode preview blocks all direct network access. This includes external stylesheets; remote
scripts remain blocked.

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

## Verifiability — every claim must be checkable in PostHog

A number a viewer cannot verify is a number they cannot trust. Every data-backed figure a canvas
shows — a KPI, a chart, a table, a stated conclusion — must carry the verification affordance for
its tier:

1. **Insight-backed metrics link the real insight in PostHog.** For a metric loaded from a saved
   insight (the preferred tier), render a "View in PostHog" affordance that calls
   `ph.openExternal(insightUrl)` from a click. Mint the URL at authoring time with the
   `generate-app-url` MCP tool (path template `/insights/{id}` with the insight's short id) and
   bake the returned URL into the source verbatim — never hand-build one. `ph.openExternal` only
   opens `https://*.posthog.com` URLs and only from a user gesture, so wire it to a button or
   link, never to load or render. Do not also bake the insight's saved query text into the
   source: canvas source is readable by every canvas viewer, while access to the insight itself
   is enforced by PostHog — the link is where a viewer inspects the query, with their own
   permissions applied.
2. **Ad-hoc queries disclose the exact query that ran, viewable in place.** For a figure computed
   by `ph.query` (a typed node or inline HogQL), show the query behind it — the HogQL text, or
   the typed query node pretty-printed as JSON — in a modal or a collapsed disclosure attached to
   the card (a Quill `Dialog` or `Collapsible` in a React canvas, a `<details>` element in an
   HTML one). Render it from the same constant or builder you pass to `ph.query`, so the
   displayed query can never drift from the executed one. This discloses nothing beyond what the
   viewer already runs: `ph.query` executes as the signed-in viewer.

These are not optional polish: a canvas that presents PostHog data without them is incomplete.
Keep the affordances compact — a small link icon per insight-backed card, a "View query"
disclosure per ad-hoc card, or one shared modal listing every ad-hoc query the canvas runs, each
labeled with the figure it backs.

For a status board, set `refresh` to the cache lifetime in seconds. Use a whole number from 30 to
86400 (one day); values outside that range, or fractional ones, fail at runtime:

```js
await ph.loadInsight(shortId, { refresh: 30 })
await ph.query(queryNode, {}, { refresh: 30 })
```

## Result shapes — read them correctly or every value renders 0

- **Trends-style results** (insight query types, via `ph.loadInsight` or a typed node): `results`
  is an array of **series objects**, not rows. Each series has `data: number[]` (per interval),
  `days: string[]` (ISO), `labels: string[]`, `count` (sum), `aggregated_value` (single-value
  total), `label`, and optional `compare_label: "current" | "previous"`. A KPI total is
  `results[0].count` (or `.aggregated_value`); a line chart plots `results[0].data` over
  `results[0].days`. `count` sums the per-interval values, which double-counts a unique-users
  series (`math: "dau"`) for anyone active on several days — for a period-unique KPI, set
  `trendsFilter: { display: "BoldNumber" }` on the query and read `aggregated_value` instead.
  With a compare period, find the prior series by `compare_label === "previous"`
  — never by index. `columns` is empty here.
- **SQL results**: `{ columns: string[], results: rows[][] }` — each row an array of cell values in
  `columns` order.

## Load progressively — render each section when its own data lands

PostHog queries can take several seconds each, and a board usually runs several. Never gate
rendering on all of them:

- Fire independent queries concurrently on mount; never chain unrelated queries with sequential
  `await`s. The host caps a canvas at 8 in-flight data requests and rejects the ninth ("Canvas
  data request exceeds runtime limits") rather than queuing it — a board that needs more than 8
  consolidates them (one query returning every row, sliced client-side) or throttles the overflow
  behind a small concurrency limiter, still with one state per section.
- Give every query its own `{ loading, error, data }` state and let each card, chart, or table
  swap its skeleton for data the moment its own result arrives. One shared `loading` flag or a
  single `Promise.all` across independent queries makes the fastest metric wait for the slowest —
  the canvas must fill in progressively, not appear all at once.
- Render the static chrome (heading, date picker, card frames with skeletons inside) immediately;
  only the value inside each section waits for its query.
- Defer queries the first paint doesn't need: content behind a tab, a collapsed section, or a
  drill-down runs its query when the user reveals it, not on mount.

Load data in `useEffect` with `useState`, and aggregate in the query; never
fetch raw event dumps. Treat a rejected query and an empty result as different states: `.catch`
must set an error state that renders visibly (message + retry), never fall through to zeros, an
empty chart, or a "no data" message — a swallowed error makes real breakage (a missing table, an
auth failure) look like missing data. Reserve the empty state for a query that succeeded with no
rows.

## Date windows

- Pass the canvas's date-picker window straight into `dateRange`:
  `ph.loadInsight(shortId, { dateRange: { date_from: win.start.toISOString(), date_to: win.end.toISOString() } })`
  — the saved insight re-scopes to the window with no time SQL. Typed nodes take the same
  `dateRange`. Re-run every query when the window changes.
- A saved **SQL** insight may ignore `dateRange` (its window lives inside the SQL) — a reason to
  prefer insight query types. If its window comes from a `{variables.…}` placeholder, drive it
  through `variables` (below) instead; `dateRange` will never reach it.
- Inline HogQL escape hatch only: never bake `now()` or a hardcoded INTERVAL. Compute unix bounds
  (`Math.floor(win.start.getTime() / 1000)`) and write half-open
  `timestamp >= toDateTime(fromUnix) AND timestamp < toDateTime(toUnix)`. Prior period = the
  equal-length window immediately before; bucket with `toStartOfDay`/`toStartOfHour`.

## SQL variables

A saved SQL insight whose HogQL contains `{variables.name}` placeholders takes its values per call,
keyed by the variable's **code name** (not its uuid):

```js
await ph.loadInsight(shortId, { variables: { product: 'surveys', month: '2026-07-01' } })
```

This is how one saved insight fills a whole board — the same per-product insight loaded once per
product — rather than every tile resolving the insight's saved default.

- Read the code names off the insight's query first (`insight-get` over MCP). The host **rejects** a
  variable the insight doesn't use, and rejects one whose value didn't take effect, instead of
  silently falling back to the saved value — so a variable mismatch surfaces as a visible error, not
  as another product's numbers.
- Variables are part of the read cache key, so N products means N loads. Prefer **one** insight
  returning every product as rows over the same insight loaded N times, and slice it client-side.
- Values are typed by the variable's definition in PostHog (String / Number / Boolean / Date / List);
  pass the same shape the insight expects, and an array for a multi-select List variable.

## Live Tasks data

For a task inbox, queue, or status board, query `system.tasks` and `system.task_runs` through
`ph.query`. Do not call `posthog:tasks-list` while authoring and embed its response: that produces a
snapshot, while the system tables keep the rendered canvas live.

The tables run as the signed-in viewer. They are project-scoped and require access to the Tasks
resource. `system.tasks` includes only non-internal tasks filed in live public spaces; it excludes
private, personal, unfiled, and internal tasks. Always exclude soft-deleted tasks explicitly.

Join a task to its latest run when the canvas needs current status:

```tsx
const data = await ph.query(`
  SELECT
    t.id,
    t.task_number,
    t.title,
    t.repository,
    t.created_by_id,
    t.created_at,
    t.updated_at,
    latest.status AS latest_run_status
  FROM system.tasks AS t
  LEFT JOIN (
    SELECT
      task_id,
      argMax(status, tuple(created_at, id)) AS status
    FROM system.task_runs
    GROUP BY task_id
  ) AS latest ON latest.task_id = t.id
  WHERE t.deleted = 0
  ORDER BY t.updated_at DESC
  LIMIT 100
`)
```

This is inline HogQL, so declare `capabilities.posthog.inlineQueries: true`. Render links with
`ph.navigate.toTask(id)` rather than constructing task URLs.

Do not promise filters the tables cannot express. `channel_id` is not queryable, so a canvas cannot
currently restrict this query to its own space. Filtering to the current viewer also requires a
known numeric user id; the canvas runtime does not inject one. State these limits when the request
depends on “this space” or “my tasks” instead of silently showing project-wide public tasks.

## Runtime memory — ph.state

Durable key-value storage per canvas. Declare every scope you use in `capabilities.posthog.state`
(`["user"]`, `["shared"]`, or both) — undeclared scopes fail validation and the host refuses them
at runtime. Scope `"user"` (the default when no scope is passed) is private to each viewer;
`"shared"` is one value per canvas, visible to the whole team.

```tsx
const draft = await ph.state.get('draft') // user scope by default; null when unset
await ph.state.set('draft', { text }) // JSON value, capped at 64 KB serialized
await ph.state.set('draft', null) // null deletes the key
await ph.state.set('board', { columns }, { scope: 'shared' }) // team-visible
const entries = await ph.state.list({ scope: 'shared' }) // [{ scope, key, value, updatedAt }]
```

- Load state in an effect on mount and render a skeleton until it resolves; writes are
  last-write-wins, so re-read (or trust your own write) rather than merging.
- 256 keys per scope. Store big data in PostHog (insights, the warehouse) and reference it.
- State is team-visible application data — never secrets, never viewer PII.

When a user asks about a canvas's current progress or settings, do not infer them from source alone.
Call `canvas-state-retrieve` with the canvas id after reading its source. It returns shared state plus
the authenticated user's own user-scoped state for canvases in public channels or their personal
channel. Use `canvas-state-set` when the user asks to change those values; read first, preserve
unrelated keys, and use the scope the canvas source expects.

Canvas discussions use the generic comment tools. Read them with `comments-list` filtered to
`scope=desktop_canvas`, the canvas id as `item_id`, and its `discussion_task_id` as `task_id`. Create
a root comment or reply with `comments-create`, using the same scope and ids (put the task id in
`item_context.taskId`). The same public-channel and personal-channel visibility rules apply.

## PostHog writes — ph.actions

`ph.actions.invoke(verb, payload)` writes into PostHog as the viewer. Declare every verb in
`capabilities.posthog.actions`; undeclared or unregistered verbs fail validation and the host
refuses them at runtime. Invocations must be wired to an explicit user gesture (a button the
viewer clicks) — the host rejects calls made on load or render.

Render the result or the thrown error visibly, and disable the button while the call is in
flight — every invocation is a real PostHog write.

The registry is the source of truth for verbs. Before wiring one, list it with the
`canvases-actions-retrieve` tool: each entry carries `verb`, `summary`, `destructive`, and
`usage` — the payload and result shape, what invoking it actually does, and the confirmation
copy it warrants. Follow a verb's `usage` exactly, including what the success message may claim.
Do not infer a verb's payload from the matching product's own MCP tools or skills — an MCP tool
call (you, now, with your credentials) and a canvas verb (the viewer, later, in the published
canvas) differ in payload shape, auth, and behavior. Invoking looks like:

```tsx
const { result } = await ph.actions.invoke('tasks.create', { title, description })
```

## Side effects

- `ph.capture(event, properties?, distinctId?)` — analytics events for interactions
  (fire-and-forget). Session replay, `$session_id`, and person attribution are handled by the
  host automatically; never initialize recording, set session ids, or roll your own capture.
- `ph.openExternal(url)` — opens `https://posthog.com` / `*.posthog.com` URLs only, and only from
  a user interaction (opens outside focus are ignored). Sandboxed `target="_blank"` navigation is
  blocked, so do not use it as a fallback or link elsewhere.
- `ph.navigate.toTask(id)` / `.toNewTask()` / `.toCanvas(id)` / `.toNewCanvas()` — in-app
  navigation within the canvas's own channel.
