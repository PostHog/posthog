---
name: canvas-templates
description: How PostHog "canvas" dashboards work end-to-end — the two rendering tiers (json-render vs freeform React-in-iframe), the agent system prompts that steer each, and the RIGHT way to fetch PostHog data (typed query nodes through ph.query, not hand-rolled HogQL). Use when changing canvas templates, the freeform sandbox, the ph.* data shim, canvas data fetching, or the agent prompts that build dashboards / web-analytics boards.
---

# Canvas templates & data

PostHog "canvases" are agent-built dashboards/apps. There are **two rendering
tiers** and a strict **data path**. Get the tier and the data path right and most
canvas work is straightforward; get them wrong and you ship correctness bugs.

## The two tiers

A canvas's `kind` (set at create time, persisted in file meta) decides everything:

| Tier | `kind` | What the agent writes | Renderer | Data path |
| --- | --- | --- | --- | --- |
| **json-render** | `"json-render"` | JSONL patches against a component catalog | `ViewRenderer` (Quill component tree) | `state.queries` HogQL, re-run by `dashboardsService` on refresh |
| **freeform / React** | `"freeform"` | a single-file React app | sandboxed `<iframe>` (`FreeformCanvas`) | the `ph.*` shim → host → PostHog |

Which template maps to which tier: `REACT_TIER_TEMPLATE_IDS` in
`packages/core/src/canvas/freeformSchemas.ts`. Today `dashboard`, `web-analytics`,
and the generic `freeform` template render React; everything else is json-render.
Legacy canvases created before a template moved tiers keep their stored `kind` —
**there is no migration**, so both renderers must keep working.

Key files:
- `packages/core/src/canvas/canvasTemplates.ts` — the agent **system prompts** +
  per-template rules. This is where you steer agent behavior. Two prompt families:
  - `BASE_RULES` + `DASHBOARD_RULES` / `WEB_ANALYTICS_RULES` → json-render (catalog-built).
  - `FREEFORM_BASE` + `buildFreeformPrompt(...)` → React tier. `freeformSystemPromptFor(id)`
    picks the prompt for a `kind:"freeform"` canvas by templateId.
- `packages/core/src/canvas/canvasDataService.ts` — host-side `ph.query` / `ph.capture`.
- `packages/ui/src/features/canvas/freeform/` — the iframe: `FreeformCanvas.tsx`
  (postMessage broker), `sandboxRuntime.ts` (the iframe HTML + the `ph` shim),
  `freeformDataBridge.ts` (routes a `ph.*` call to the host tRPC).

## Data: the RIGHT way (read this before touching queries)

> **Reuse PostHog's query runners; don't reinvent metrics in SQL.**

The freeform app talks to PostHog ONLY through the injected `ph` global — the host
holds the token, the iframe never sees it. The one call that matters:

```js
const { columns, results } = await ph.query(arg)
```

`arg` is **either** a typed query node **or** an inline HogQL string:

- **PREFERRED — a typed query node:** `ph.query({ kind: "TrendsQuery", series: [...], dateRange: {...} })`.
  The product's OWN query runners compute it, so the numbers **match the PostHog
  UI exactly** (sessionization, unique users, breakdowns, math, bounce rate) and
  the node's `dateRange` handles the window. The agent gets the node by creating/
  opening an insight via the PostHog MCP tools and copying its `query` node.
- **ESCAPE HATCH — inline HogQL:** `ph.query("SELECT …")`. Only for shapes a typed
  node can't express. The agent owns the SQL and its correctness.

Why this split exists: hand-rolled HogQL for standard metrics (especially web
analytics — bounce rate, channel attribution, sessionization) subtly diverges from
the product's numbers. Typed nodes are the same wheel the UI uses; don't re-cut it.

> **⚠️ The result SHAPE differs by kind — get it wrong and every value reads 0.**
> - HogQL → `{ columns: string[], results: rows[][] }` (read `results[row][col]`).
> - Typed node (TrendsQuery/etc.) → `results` is an array of **series objects**
>   (`{ data: number[], days: string[], count, aggregated_value, compare_label, … }`),
>   NOT rows. KPI total = `results[0].count`/`.aggregated_value`; series =
>   `results[0].data`; the `compareFilter` previous period is a second series
>   (match `compare_label === "previous"`, don't assume index order).
> `CanvasDataService.query` passes typed-node results through untouched and only
> row-coerces HogQL — see the `isTyped` branch. The first build of this missed it
> and rendered all-zeros despite the query running fine.

### The data path end-to-end

```
ph.query(arg)                                   iframe  (sandboxRuntime.ts shim)
  └─ postMessage "data-request"
       └─ FreeformCanvas route()                 ui      (FreeformCanvas.tsx)
            └─ handleFreeformDataRequest("query") ui      (freeformDataBridge.ts)
                 └─ tRPC canvasData.query         host    (canvas-data.router.ts)
                      └─ CanvasDataService.query   core    (canvasDataService.ts)
                           └─ runQuery(node)        core   (posthogApi.ts)
                                └─ POST /api/projects/<id>/query/
                                     { query: <node>, refresh: "blocking" }
```

- `runQuery(authService, node, { refresh })` is the one place that POSTs to the
  query endpoint. `runHogQLQuery(...)` is a thin wrapper that boxes a string into
  `{ kind: "HogQLQuery", query }`. Both live in `posthogApi.ts`.
- `refresh: "blocking"` = the cached avenue (serve a fresh cached result, else
  compute). Same cache insights use — so typed nodes are cached, not recomputed.
- `canvasDataQueryInput` (`freeformSchemas.ts`) accepts `{ query?, hogql?, params? }`
  and refines that exactly one of `query` / `hogql` is present.

To add a new `ph.*` capability: add the method to the shim (`sandboxRuntime.ts`
`window.ph`), route it in `freeformDataBridge.ts`, add a tRPC procedure
(`canvas-data.router.ts`) backed by a `CanvasDataService` method. Never let the
iframe hold a token — it posts a request; the host runs the authenticated call.

> **`ph.run(insightShortId)` is stubbed** (`freeformDataBridge.ts` throws). It's
> the *view/published* tier's model: a shared canvas can't ship inline queries to
> anonymous viewers, so publish converts validated query nodes → saved insights +
> an allowlist and the canvas references them by id. Implement it there, not in edit.

## Dates

The freeform app owns its date control (the toolbar picker is hidden for freeform —
it drove json-render `state.queries`, see `WebsiteLayout.tsx`). The agent renders
Quill's `DateTimePicker` and feeds the window into the typed node's `dateRange`
(`{ date_from, date_to }`) — the runner handles timezone/bucketing/half-open.

> **`DateTimePicker` must be `compact` in the canvas.** Without the `compact`
> prop it auto-detects layout via `useMediaQuery('(min-width: 64rem)')` against the
> **iframe viewport** — which is full-width, so it picks the wide dual-calendar
> layout and overflows the popover it's anchored in. The prompt forces `compact`. The
inline-HogQL fallback must use half-open `timestamp >= toDateTime(fromUnix) AND
timestamp < toDateTime(toUnix)` (integer unix = UTC), never `now()` / `INTERVAL` /
inclusive `<= to`. These rules live in `FREEFORM_DATE_CONTROL_RULES`.

## Styling (freeform sandbox)

The iframe loads Quill's compiled CSS + tokens AND the Tailwind Play CDN
(`sandboxRuntime.ts`), with **Preflight disabled** (its unlayered form reset
overrode Quill's `@layer components` styles). So in a freeform canvas: build from
`@posthog/quill` components, Tailwind utilities work, and you do NOT restyle Quill
components. Allowed imports are the `FREEFORM_WHITELIST` (`freeformWhitelist.ts`);
the Quill version is `QUILL_VERSION` there (must match the CSS `<link>` URLs).

## Editing the agent prompts

- Steer the React data templates by editing the rule arrays in `canvasTemplates.ts`
  (`FREEFORM_QUILL_RULES`, `FREEFORM_DATE_CONTROL_RULES`, `FREEFORM_DASHBOARD_RULES`,
  `FREEFORM_WEB_ANALYTICS_RULES`). Generic `freeform` stays rule-free ("anything goes").
- The agent can't WebFetch at runtime (denied tool) — prompt rules must be
  self-contained; URLs are knowledge pointers only.
- Prompt strings are plain TS array entries; biome lints the file. Avoid `${...}`
  inside a normal string literal (biome flags it as a template placeholder).

## Checks after any change

```bash
pnpm --filter @posthog/core typecheck && pnpm --filter @posthog/core test -- --run
pnpm --filter @posthog/ui typecheck
npx biome lint packages/core/src/canvas packages/ui/src/features/canvas
```

Then **verify in the running app** — most of this tier (sandbox styling, the data
path, the date picker, refresh) is not covered by unit tests. Use the
`test-electron-app` skill to drive a real canvas over CDP.
