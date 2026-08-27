---
name: building-react-quill-canvases
description: >
  Author the React + Quill implementation of a PostHog canvas: the single-component contract, the
  allowed imports, Quill (PostHog's design system) component and composition rules, theme-aware
  design tokens, loading skeletons, and the in-canvas date picker. Use after building-canvases has
  routed a canvas request to a React implementation — dashboards, data boards, forms, tools, or any
  canvas that should look native to PostHog.
---

# Building React + Quill canvases

The whole application is one React/TSX file (`src/canvas.tsx` in the source project). It must
`export default` a single React component that takes no props — the host mounts it. Do not import
react-dom or call createRoot.

Start from the working scaffold in [references/starter-scaffold.md](references/starter-scaffold.md)
on a first build: it already wires the date picker, theme tokens, per-query loading state (every
card fills in independently as its own data lands), and correct typed-node result reading. Keep
that wiring; replace the sample metrics and layout.

## Imports

Use React, Quill, Recharts, Lucide, and Day.js for the standard application shell. The platform
also admits ten optional libraries for specialized work. Read
[references/platform-libraries.md](references/platform-libraries.md) before choosing one.

Other bare imports, dynamic `import()`, `require()`, `<script>` tags, and remote code fail
validation. Direct network requests and external images, fonts, media, or frames require an exact
HTTPS origin in `capabilities.network.origins`. They work only in the **published** canvas — the
edit-mode preview blocks direct network access regardless of declaration. Stylesheets from declared
origins are allowed; remote scripts remain blocked, so bundle code with the canvas.

## Quill component rules

A PostHog data board must be built entirely from `@posthog/quill` components — never a native
control or a styled `<div>` standing in for one:

- Dropdown/picker → `Select` (never a native `<select>`); button → `Button` (never `<button>`);
  text field → `Input`/`Textarea`; checkbox → `Checkbox`; label → `Label`.
- Table → `Table` (`TableHeader` > `TableRow` > `TableHead`, then `TableBody` > `TableRow` > `TableCell`);
  panel → `Card` (`CardHeader` + `CardTitle` + `CardContent`); pill → `Badge`; titles → `Heading`; body → `Text`.
- The only non-Quill tags allowed are plain layout `<div>`s and `recharts` elements.
- Quill is built on Base UI: compose compound parts (`Select` + `SelectTrigger`/`SelectContent`/`SelectItem`),
  use controlled `value` + `onValueChange`, and swap a part's element with the `render` prop
  (e.g. `<PopoverTrigger render={<Button …/>} />`) instead of wrapping it.
- Quill components are already themed — never restyle one with Tailwind classes or inline `style`;
  use their `variant`/`size` props. Put layout utilities (`flex`, `grid`, `gap-4`, `p-4`) on your own
  wrapper `<div>`s.
- Buttons: default to `variant="outline"`; `variant="primary"` for the one main action only.

## Styling and theme

- Give the canvas's outermost element `h-screen` (`height: 100vh`) so it fills the iframe viewport.
  Do not use `h-full` there: a published canvas's artifact shell gives its `html`, `body`, and
  `#root` elements no explicit height, so a percentage root height collapses to content height.
  Nested elements may use `h-full` once their parent establishes a height.
- Style with Tailwind utilities and Quill components; reserve inline `style` for genuinely dynamic
  runtime values (fixed sizes use arbitrary-value utilities like `h-[280px]`).
- Write specific interface copy. Never use lorem ipsum or placeholder labels in a finished canvas.
- The canvas follows the user's PostHog theme; a `.dark` class on the document root flips at runtime.
  Color only from the design-token utilities — surfaces `bg-background bg-card bg-muted bg-primary
bg-success bg-warning bg-info bg-destructive`; text `text-foreground text-muted-foreground
text-card-foreground`; borders `border-border`. Never a hardcoded hex or light-only color.
- Status tokens invert the usual convention: the bare token (`bg-success`) is a pale background fill
  and `-foreground` (`text-success-foreground`) is the strong readable color. Colored text or icons
  always use the `-foreground` utility; a filled pill pairs `bg-success text-success-foreground`.
  Prefer the Quill `Badge` (`variant="success"`/`"destructive"`) for deltas so you don't hand-pick.
- `bg-secondary`, `text-secondary`, `bg-accent`, and `bg-popover` are not defined in the canvas — avoid them.
- recharts strokes/fills use token CSS variables (`stroke="var(--primary)"`, grid/axes in
  `var(--border)`/`var(--muted-foreground)`).
- Write Unicode glyphs (curly quotes, ellipsis, arrows, emoji) as literal characters in JSX —
  `\uXXXX` escapes render verbatim in JSX text.

## Loading, error, and empty states

Every data point renders a skeleton in its own `Card` while loading or refreshing: `SkeletonText`
(matching `lines` and text-size `className`) for text/number values, `Skeleton` for blocks/charts.

Render progressively — each query owns its loading state. The chrome (heading, date picker,
card frames with skeletons inside) renders immediately, every independent query fires
concurrently on mount, and each card swaps its skeleton for data the moment its own query
resolves, so a slow query only holds back its own card. Never drive the whole canvas off one
shared `loading` flag or a `Promise.all` across independent queries — that makes the fastest
metric wait for the slowest. Set each section's loading state true again on refresh; never show
a blank or a jumping layout. Content the first paint doesn't show (an inactive tab, a collapsed
section, a drill-down) defers its query until the user reveals it.

A failed query and an empty result are different states — never let one render as the other.
`.catch` on every `ph.query`/`ph.loadInsight` must set an error state that renders visibly (the
message plus a Retry button wired to the refresh nonce, as in the starter scaffold), not fall
through to zeros, an empty chart, or a "no data yet" message. A query that silently swallows its
error makes real breakage (a missing table, an auth failure, a bad query) look like missing data.
Reserve the empty state for a query that succeeded with no rows.

## Data-product patterns

Treat these as starting shapes and adapt them to the request and available data.

### Product dashboard

- Build a live board from verified PostHog data, never a static mockup.
- Start with a `Heading`, then a responsive grid of compact `Card` KPIs, trend charts, and useful
  breakdown tables.
- Show a `Badge` delta for KPIs when a meaningful comparison period exists.
- Use a `LineChart` for time series and a `BarChart` for discrete categories. Do not turn every
  result into a table.
- Give every KPI, chart, and table its own loading, empty, and error state.
- Make every figure verifiable: an insight-backed card gets a "View in PostHog" affordance opening
  its saved insight (`ph.openExternal` with a URL minted by `generate-app-url`); an ad-hoc
  `ph.query` card gets a "View query" `Dialog` or `Collapsible` showing the exact query that ran —
  see "Verifiability" in `querying-canvas-data`.

### Web analytics board

Use this shape when the request or legacy requested pattern says `web-analytics`:

1. Show Visitors, Page views, Sessions, Session duration, and Bounce rate as KPI cards, with deltas
   against the previous equal-length period.
2. Plot unique visitors over time, with a second line for the previous period when comparison data
   is available.
3. Follow with compact tables for top paths, traffic sources or channels, devices, and geography.
4. Prefix countries with flag emoji. Add retention or active-hours views only when the available
   data makes them useful.

Use the web analytics query kinds described in `querying-canvas-data`; do not recreate bounce rate,
sessionization, attribution, or unique visitors in HogQL. Format large values for display, such as
`236K`, while preserving the raw value for calculations and accessible labels.

### Interactive explorer

Use controlled Quill inputs for each dimension, event, or date choice. Keep result sets small and
refresh every dependent query when a control changes.

### Checklist or runbook

For a checklist, QA runbook, launch plan, onboarding sequence, or any list of steps people work
through and tick off, start from the complete, validated project in
[references/checklist-example.md](references/checklist-example.md). Its load-bearing parts — the
typed content module separate from the component, one shared `ph.state` key per step, the
debounced ref-alongside-state update path, an expected outcome on every step, and visible
load/save failure states — are what break when improvised. Keep them; replace the content.

## Date window

A data board owns its own date control — render Quill's `DateTimePicker` (never a custom Select or
native date input) inside a `Popover` whose trigger is a Quill `Button`. `PopoverContent` gets
exactly `className="w-auto p-0"` and nothing is added to `DateTimePicker` beyond
`value`/`onApply`/`onCancel` (it self-sizes; don't pass `compact` or widths). Re-run every query
when the window changes — see the `querying-canvas-data` skill for feeding it into `dateRange`.

## State and actions

Persisting values across reloads (`ph.state`, with user/shared scopes) and writing into PostHog
from a button (`ph.actions.invoke`, e.g. filing a task or an annotation) have their own API
contracts, capability declarations, and gesture rules — read the "Runtime memory" and "PostHog
writes" sections of the `querying-canvas-data` skill before using either. Wire actions to a
`Button` `onClick` that disables itself while the call is in flight, and render the returned
error (they are real PostHog writes, throttled server-side).
