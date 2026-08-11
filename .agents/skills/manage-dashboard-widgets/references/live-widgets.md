# Live widgets (self-updating tiles)

A **live** widget seeds once from `run_widgets`, then self-updates client-side — it does not rely on the dashboard refresh loop for freshness.
This doc is the paved path for building one.
Examples below reference web analytics live widgets, the first consumer of the platform — they show how it is meant to be used rather than code the platform itself ships.

## The contract

Backend SSOT is two `WidgetSpec` fields in `widget_specs/registry.py`:

- **`is_live: bool`** — marks the type as live. Flows into `widget-form-fields.json` (via `hogli build:widget-types`), resolved onto the FE catalog as `entry.live` (read it there, or via `isLiveDashboardWidgetType()` where no entry is at hand); also exposed as `live` on the REST/MCP widget catalog. Do not hand-maintain FE live-type lists.
- **`creation_flag: str | None`** — adds-only rollout gate, resolved generically in `widget_create.py` via `feature_flags.widget_flag_enabled`. Creating a tile requires the flag; already-placed tiles keep rendering when it's off. Not live-specific — any spec may set it — but new live widget families should, as their kill switch.

What `is_live` buys for free: a pulsing "Live" marker in the tile header (`WidgetCardHeader`), a "Live" tag on the Add-widget picker card, and the `live` field agents see in `dashboard-widget-catalog-list`.

Rules a live type must follow (`WidgetSpec` enforces rule 3 at construction — a violating spec fails on any import of the registry, so tests, codegen, and web all catch it; rules 1-2 are conventions, with the merge behavior guarded by `LiveWidgetSlidingWindow.test.ts`):

1. **The `run_widgets` result is a seed, not the state.** Its payload must carry `generatedAt` — the server clock at query time (ISO-8601). See `LiveWidgetSeedPayload` in `widgets/live/liveWidgetTypes.ts`.
2. **Seeds must be idempotent.** Manual tile refresh and dashboard auto-refresh re-run `run_widgets` and re-seed; the platform does **not** skip live tiles (a re-seed heals stream gaps from dropped connections or hidden tabs). Merge seeds so a re-run never double counts — see the sliding-window semantics below.
3. **No `dateRange` or `filterTestAccounts` config.** Live tiles show a fixed real-time window (dateRange contradicts it), and the livestream can't apply test-account filters, so seed and stream would disagree. The header's date range hides automatically for live types (catalog resolution defaults `showDateRange` to false when `live`).

## Backend conventions

The seed query is ordinary product code — a `query_fn` in `products/dashboards/backend/widgets/<type>.py` delegating to the product's query module (the WA seeds will live in a dedicated module such as `products/web_analytics/backend/hogql_queries/live_widget_seeds.py`, named apart from the /web/live page's own client-side seed queries).
Conventions:

- Return `generatedAt` (`datetime.now(UTC).isoformat()` at query time) in every payload.
- Accept and ignore `include_total_count` — it's part of the generic `query_fn` calling convention.
- Keep the window length a constant in product code, mirrored by a FE constant (e.g. a 30-minute window on both sides), and cap payload size — the seed rides the batched `run_widgets` response.

## Frontend toolkit — `products/dashboards/frontend/widgets/live/`

Compose these; don't re-wire SSE/flush/tick by hand:

| Module                                                                        | What it does                                                                                                                                                                              |
| ----------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `liveWidgetTypes.ts` — `isLiveDashboardWidgetType()`, `LiveWidgetSeedPayload` | FE read of `WidgetSpec.is_live` from the generated manifest, plus the base seed-payload interface (`generatedAt`) — extend it in your result types                                        |
| `LiveWidgetSlidingWindow`                                                     | Minute-bucketed window: overall count + named breakdown domains, each fed by an extractor `(event) => string \| null` (null = skip). Encodes the seed-merge correctness rules — see below |
| `liveWidgetStream(options)`                                                   | Kea logic builder: livestream SSE connection (`/events`, `live_events_token`), flush-batched `onEvents` (300ms), 60s `onMinuteTick`, all via `cache.disposables` (pauses on hidden tabs)  |
| `useLiveWidgetSeed(payload, seed)`                                            | The one prop→action React bridge: seeds your logic from the tile's `result` prop (pass `null` while the payload isn't ready)                                                              |
| `components.tsx` — `LiveWidgetEmptyState`                                     | "No data in the window yet" body with optional CTA                                                                                                                                        |
| `components.tsx` — `LiveWidgetIndicator`                                      | The pulsing "Live" header marker (platform-rendered — you don't wire this)                                                                                                                |

**Seed-merge semantics (do not "simplify" these):** the SSE stream reads Kafka (fresh) while seeds read ClickHouse (can lag ingestion). `LiveWidgetSlidingWindow` therefore merges seeds via per-bucket `max` (never replace — an empty lagging re-seed must not wipe stream-accumulated counts) and drops streamed events at or before the domain's seed `generatedAt` (strict `>`), so a re-seed never double counts. `widgets/live/LiveWidgetSlidingWindow.test.ts` guards these.

**kea-typegen constraint:** `liveWidgetStream` only adds `connect`/`events` wiring — typegen cannot see builder-injected symbols, so your logic declares its own actions/reducers/selectors and the builder dispatches into them via `onEvents`/`onMinuteTick` callbacks.

**One connection per dashboard:** make the product's live logic unkeyed and share it across the family's tiles — kea ref-counting keeps one SSE connection no matter how many live tiles are placed, and tears it down when the last unmounts. Reset state in `afterMount` so data can't leak across dashboards.

**Transports:** the shipped helper is livestream SSE. The contract is transport-agnostic — a polling helper with the same `onEvents`/`onMinuteTick` shape could be added for products without livestream data, with no contract changes.

## Recipe: shipping a new live widget family

On top of the normal [new-type checklist](checklist-new-widget-type.md):

1. Spec: `is_live=True`, `creation_flag="<your-rollout-flag>"`, no `dateRange`/`filterTestAccounts` on the config model (enforced at spec construction).
2. Seed query in your product's backend returning `generatedAt`; thin `query_fn` wrapper in `widgets/<type>.py`.
3. Catalog entry as normal — `showDateRange` hides automatically for live types. To keep the picker card hidden pre-release, land the FE catalog entry with the release; `creation_flag` is the backend gate either way ([availability-and-gating.md](availability-and-gating.md)).
4. One unkeyed shared logic on `liveWidgetStream` + `LiveWidgetSlidingWindow` (or your own windowing if minute buckets don't fit — keep the idempotent-seed rule).
5. Components: `useLiveWidgetSeed(payload, seedAction)`, render from selectors, `LiveWidgetEmptyState` when the window is empty.
6. `hogli build:widget-types` (regenerates the manifest the FE catalog reads `live` from), then the normal verify suite.

Web analytics live widgets (`products/dashboards/frontend/widgets/web_analytics/`) are the first consumer to follow this recipe end to end.
