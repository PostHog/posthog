# Live widgets (self-updating tiles)

A **live** widget seeds once from `run_widgets`, then self-updates client-side — it does not rely on the dashboard refresh loop for freshness.
This doc is the paved path for building one. The first consumer, web analytics live widgets, lands in a separate PR — references to it below show how the platform is meant to be used, not code that ships here.

## The contract

Backend SSOT is two `WidgetSpec` fields in `widget_specs/registry.py`:

- **`is_live: bool`** — marks the type as live. Flows into `widget-form-fields.json` (via `hogli build:widget-types`), where the FE reads it through `isLiveDashboardWidgetType()`; also exposed as `live` on the REST/MCP widget catalog. Do not hand-maintain FE live-type lists.
- **`creation_flag: str | None`** — adds-only rollout gate, resolved generically in `widget_create.py` via `feature_flags.widget_flag_enabled`. Creating a tile requires the flag; already-placed tiles keep rendering when it's off. Not live-specific — any spec may set it — but new live widget families should, as their kill switch.

What `is_live` buys for free: a pulsing "Live" marker in the tile header (`WidgetCardHeader`), a "Live" tag on the Add-widget picker card, and the `live` field agents see in `dashboard-widget-catalog-list`.

Rules a live type must follow (the codegen preflight in `bin/build-dashboard-widget-types.py` enforces rule 3; rules 1-2 are conventions, with the merge behavior guarded by `LiveWidgetSlidingWindow.test.ts`):

1. **The `run_widgets` result is a seed, not the state.** Its payload must carry `generatedAt` — the server clock at query time (ISO-8601). See `LiveWidgetSeedPayload` in `widgets/live/types.ts`.
2. **Seeds must be idempotent.** Manual tile refresh and dashboard auto-refresh re-run `run_widgets` and re-seed; the platform does **not** skip live tiles (a re-seed heals stream gaps from dropped connections or hidden tabs). Merge seeds so a re-run never double counts — see the sliding-window semantics below.
3. **No `dateRange` or `filterTestAccounts` config.** Live tiles show a fixed real-time window (dateRange contradicts it), and the livestream can't apply test-account filters, so seed and stream would disagree. Set catalog `headerMeta: { showDateRange: false }`.

## Backend conventions

The seed query is ordinary product code — a `query_fn` in `products/dashboards/backend/widgets/<type>.py` delegating to the product's query module (the WA seeds will live in a dedicated module such as `products/web_analytics/backend/hogql_queries/live_widget_seeds.py`, named apart from the /web/live page's own client-side seed queries).
Conventions:

- Return `generatedAt` (`datetime.now(UTC).isoformat()` at query time) in every payload.
- Accept and ignore `include_total_count` — it's part of the generic `query_fn` calling convention.
- Keep the window length a constant in product code, mirrored by a FE constant (e.g. a 30-minute window on both sides), and cap payload size — the seed rides the batched `run_widgets` response.

## Frontend toolkit — `products/dashboards/frontend/widgets/live/`

Compose these; don't re-wire SSE/flush/tick by hand:

| Module                                               | What it does                                                                                                                                                                              |
| ---------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `types.ts` — `LiveWidgetSeedPayload`                 | Base interface for seed payloads (`generatedAt`); extend it in your result types                                                                                                          |
| `liveWidgetTypes.ts` — `isLiveDashboardWidgetType()` | FE read of `WidgetSpec.is_live` from the generated manifest                                                                                                                               |
| `LiveWidgetSlidingWindow`                            | Minute-bucketed window: overall count + named breakdown domains, each fed by an extractor `(event) => string \| null` (null = skip). Encodes the seed-merge correctness rules — see below |
| `liveWidgetStream(options)`                          | Kea logic builder: livestream SSE connection (`/events`, `live_events_token`), flush-batched `onEvents` (300ms), 60s `onMinuteTick`, all via `cache.disposables` (pauses on hidden tabs)  |
| `useLiveWidgetSeed(payload, seed, guard?)`           | The one prop→action React bridge: seeds your logic from the tile's `result` prop                                                                                                          |
| `LiveWidgetEmptyState`                               | "No data in the window yet" body with optional CTA                                                                                                                                        |
| `LiveWidgetIndicator`                                | The pulsing "Live" header marker (platform-rendered — you don't wire this)                                                                                                                |

**Seed-merge semantics (do not "simplify" these):** the SSE stream reads Kafka (fresh) while seeds read ClickHouse (can lag ingestion). `LiveWidgetSlidingWindow` therefore merges seeds via per-bucket `max` (never replace — an empty lagging re-seed must not wipe stream-accumulated counts) and drops streamed events at or before the domain's seed `generatedAt` (strict `>`), so a re-seed never double counts. `widgets/live/LiveWidgetSlidingWindow.test.ts` guards these.

**kea-typegen constraint:** `liveWidgetStream` only adds `connect`/`events` wiring — typegen cannot see builder-injected symbols, so your logic declares its own actions/reducers/selectors and the builder dispatches into them via `onEvents`/`onMinuteTick` callbacks.

**One connection per dashboard:** make the product's live logic unkeyed and share it across the family's tiles — kea ref-counting keeps one SSE connection no matter how many live tiles are placed, and tears it down when the last unmounts. Reset state in `afterMount` so data can't leak across dashboards.

**Transports:** the shipped helper is livestream SSE. The contract is transport-agnostic — a polling helper with the same `onEvents`/`onMinuteTick` shape could be added for products without livestream data, with no contract changes.

## Recipe: shipping a new live widget family

On top of the normal [new-type checklist](checklist-new-widget-type.md):

1. Spec: `is_live=True`, `creation_flag="<your-rollout-flag>"`, no `dateRange`/`filterTestAccounts` on the config model.
2. Seed query in your product's backend returning `generatedAt`; thin `query_fn` wrapper in `widgets/<type>.py`.
3. Catalog: `headerMeta: { showDateRange: false }`; optionally gate the group out of the picker pre-release via `DASHBOARD_WIDGET_GROUP_FEATURE_FLAGS` ([availability-and-gating.md](availability-and-gating.md)).
4. One unkeyed shared logic on `liveWidgetStream` + `LiveWidgetSlidingWindow` (or your own windowing if minute buckets don't fit — keep the idempotent-seed rule).
5. Components: `useLiveWidgetSeed(payload, seedAction, guard)`, render from selectors, `LiveWidgetEmptyState` when the window is empty.
6. `hogli build:widget-types` (regenerates the manifest; preflight fails on `dateRange`), then the normal verify suite.

The first consumer to follow this recipe end to end will be web analytics live widgets (`products/dashboards/frontend/widgets/web_analytics/`), landing in a separate PR.
