# Brainstorm: surfacing error spikes / log anomalies on the Metrics UI

Status: brainstorm / not yet scoped for implementation.

## Goal

Metrics already overlays trace exemplars on its charts (`MetricsExemplarMarkers`,
`metricsSamplesLogic.traceExemplars`) — clickable dots at the timestamps where a
metric emission carried a `trace_id`, pivoting into the tracing product. This doc
explores extending that same pattern to two more signals, each behind its own
toggle:

- **Error Tracking spikes** — "an issue spiked around here"
- **Logs anomalies** — "log volume for this service looked anomalous around here"

The appeal: both would be _read-time_ integrations (call another product's
existing query surface at render time), not ClickHouse schema or ingestion
changes — matching the ingestion-averse framing of this brainstorm.

## Status quo: Error Tracking spikes

Error Tracking already runs **continuous, persisted** spike detection —
Metrics would not need to compute anything new.

- Detection: Rust (`rust/cymbal/.../alerting/spike_detection.rs`), a
  threshold + multiplier-over-baseline check against 5-minute Redis buckets,
  per issue and per team.
- Every detected spike is persisted to Postgres as `ErrorTrackingSpikeEvent`
  (`team`, `issue`, `detected_at`, `computed_baseline`, `current_bucket_value`)
  via a Temporal workflow (`ErrorTrackingIssueSpikingWorkflow`).
- Already exposed through Error Tracking's facade (it's an isolated product,
  so this is the sanctioned access path):
  `error_tracking.backend.facade.api.list_spike_events(team_id, issue_ids=None, date_from, date_to, ...)`.
  `issue_ids` is optional — **a team-wide "every error spike in this window"
  call already works today, zero backend changes required.**

**The gap: no service attribution, anywhere, on this path.** Confirmed by
reading the exception ingestion pipeline directly:

- The `$exception` event schema (`posthog/taxonomy/taxonomy.py`, cymbal) has
  no `service`/`service.name`/resource-attribute field at all — not just
  unsurfaced, genuinely never captured. Cymbal's own source has zero hits for
  `service_name`/`otel`/`resource` tied to the exception payload.
- Issue grouping/fingerprinting hashes stack-frame shape (function/module/
  source), not service identity.
- Structural reason: error tracking's ingestion pipeline is entirely separate
  from the OTEL-based pipeline that captures `service.name`
  (`rust/capture/src/otel/attribution.rs`, which only feeds logs/traces/
  metrics). Nothing suggests this was a deliberate exclusion — it reads as
  error tracking having grown up around browser/frontend exception capture
  before the OTEL observability stack existed, and the two were never unified.

**A real, already-captured correlation path exists, and it's more precise
than service_name would be:** exceptions carry `$trace_id`/`$span_id`
(zero-padded when unset). Error Tracking's own agent skill
(`investigating-error-issue/SKILL.md`) documents pivoting via trace_id into
logs to find `service.name`. Since metric samples already carry `trace_id`
too (the existing exemplar mechanism), an **exact per-datapoint join** is
possible today with no new ingestion: take the trace_id off a metric sample,
check whether any `$exception` event shares it. This only covers exceptions
inside an already-traced request (likely a minority), so it's a
complement to — not a replacement for — the coarser team-wide spike view.

### Implication for Metrics UI integration

Two tiers, cleanly separated by effort:

1. **Team-wide "Error spikes" toggle — buildable now.** Call
   `list_spike_events(team, date_from, date_to)` for the visible window,
   render markers at `detected_at`. No correlation to the specific metric's
   service; shows every spike on the team. Cheapest possible version of this
   feature.
2. **Per-metric-precise overlay — needs a design choice.** Either (a) extend
   Error Tracking's spike event/issue contract with a service attribute (a
   real but modest facade/model change, not an ingestion pipeline change —
   the underlying `events` table already has whatever properties the SDK
   sent; it's about promoting one), or (b) join on `trace_id` between a
   metric's own sample exemplars and `$exception` events sharing that trace
   — exact but only covers traced-request exceptions.

## Status quo: Logs anomaly detection

Different shape from Error Tracking: real, working, but **deliberately not
persisted.**

- Core detection: `products/apm/backend/logic/anomaly_detection/` — pure
  functions, no migrations, no table. Its own docstring: _"no rollup table,
  no scheduled evaluation, no persisted issues. Everything is computed per
  request."_
- Reachable via `run_scan(team, service_name, eval_start, eval_end)`
  (`products/logs/backend/anomaly_scan.py`), exposed at
  `POST /api/projects/{team_id}/logs/anomalies/scan`. Synchronous, one
  service at a time, capped at a 7-day window. Returns `ScanIssue` objects
  with `opened_at`/`last_anomalous_at`/`anomalous_bucket_times` — literal
  marker timestamps.
- Feature-flagged (`logs-anomalies`), explicitly labeled experimental.
- Only "storage" is a 60-second Django cache keyed by
  `team/service_name/eval_start/eval_end`.
- **Keyed by `service_name`** — which is already a first-class column on
  `metric_series1`. Unlike Error Tracking, correlating a specific metric to
  its service's log anomalies needs **no new correlation key** — call
  `run_scan(team, service_name=<the metric's service_name>, ...)` directly.

### Implication for Metrics UI integration

This is the better correlation fit (exact service match, no design choice
needed) but the worse cost profile:

- Every chart view with the toggle on would trigger a live ClickHouse scan,
  mitigated only by the existing 60s cache. **Needs a caching/rate-limiting
  adjustment before this is wired into a UI surface that could re-render
  on every pan/zoom/filter change** — e.g., a longer or metrics-side cache,
  or only firing the scan when the toggle is actively enabled rather than on
  every render. Not scoped in this doc; flagged as a prerequisite.
- Ties Metrics' behavior to a still-experimental, separately-flagged feature
  (`logs-anomalies`) — a stability/ownership dependency worth naming
  explicitly to the logs/APM team before building against it.

## Summary comparison

| Source                | Query exists today?                                     | Correlation key to a metric                                                  | What's actually needed                                                                                        |
| --------------------- | ------------------------------------------------------- | ---------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------- |
| Error Tracking spikes | Yes — `list_spike_events`, team-wide, zero code changes | None yet (team-wide only), or exact via shared `trace_id` on traced requests | UI toggle + overlay; optional: add service attribution to spike events for scoped filtering                   |
| Log anomalies         | Yes — `run_scan`, JIT only                              | `service_name` (already on metric series)                                    | UI toggle + overlay; caching/rate-limit work before production use; accept dependency on an experimental flag |

## Section: Metrics MCP integration

### Current MCP status quo (researched, not yet acted on)

Mechanism: each product declares exposed endpoints in
`products/<product>/mcp/tools.yaml`; `hogli build:openapi` generates real tool
handlers into `services/mcp/src/tools/generated/`, which the MCP server
registers as live tools. `ui_apps:` blocks in the same YAML generate
interactive result visualizations.

- **Metrics MCP** (`products/metrics/mcp/tools.yaml`): `query-metrics`,
  `metric-names-list`, `characterize-metric-anomaly` are enabled.
  **`metrics-samples-create` (the trace-exemplar/pivot endpoint) is defined
  but `enabled: false`** — an agent cannot pull trace-linked metric samples
  via MCP today, even though the human UI has it.
- **Logs MCP** (`products/logs/mcp/tools.yaml`): query/count/patterns/
  attributes tools, plus **`logs-anomalies-scan` is already `enabled: true`**
  (feature-flag gated) — an agent can already trigger the anomaly detector
  directly today, just not yet cross-referenced with a specific metric
  automatically.
- **Error Tracking MCP** (`products/error_tracking/mcp/tools.yaml`): issue
  query/list/merge/split tools are enabled. **`error-tracking-spike-events-list`
  and the spike-detection-config tools are `enabled: false`** — spike data
  isn't reachable via MCP today.
- **No tool anywhere does server-side cross-product correlation.** The
  existing pattern (see `characterize-metric-anomaly.md`,
  `query-metrics.md`) is prompt-driven chaining: the tool description
  literally instructs the calling agent to separately call `query-logs` and
  APM span tools around an anomaly's onset window. There is no internal
  fan-out to another product's API from within a tool handler.

### Proposed approach: extend `characterize-metric-anomaly`, don't build a new tool

Follows the codebase's established convention (expose primitives + prompt
guidance, not a monolithic do-everything tool) rather than introducing a new
pattern.

1. **Flip two feature flags, no new code:**
   - Enable `metrics-samples-create` in `products/metrics/mcp/tools.yaml` so
     an agent can pull trace-linked samples for a metric via MCP (closes the
     gap between what the human UI can do and what an agent can do).
   - Enable `error-tracking-spike-events-list` in
     `products/error_tracking/mcp/tools.yaml` so an agent can query team-wide
     spike events for a time window.
2. **Extend `characterize-metric-anomaly.md`'s tool description/prompt** to
   add an explicit correlation step, mirroring its existing "then correlate:
   query logs... and traces..." guidance:
   - After characterizing the anomaly window, instruct the agent to:
     - Call `error-tracking-spike-events-list` for the same window (team-wide
       today; scoped once/if service attribution lands) and report any
       overlapping issue spikes.
     - Call `logs-anomalies-scan` with the metric's own `service_name` and
       the anomaly window (this tool is already enabled — no flag change
       needed) and report any overlapping log anomalies.
   - This reuses `_implicated_service` from
     `products/metrics/backend/investigation.py`, which already derives a
     service name from a metric's top movers — the same value that would
     feed `logs-anomalies-scan`'s `service_name` param.
3. **Do not build a bespoke "get red moments for this metric" tool.** It
   would duplicate what prompt-guided chaining of existing primitives
   already achieves, and would be the first tool in the codebase to do
   server-side cross-product fan-out — a bigger architectural decision than
   this brainstorm is trying to make.

### Open questions for follow-up

- Should `error-tracking-spike-events-list`, once enabled, take a
  `service_name`-shaped filter to avoid the agent (and the human UI) always
  seeing team-wide noise? This is the same "no service attribution" gap as
  the UI-side integration above — solving it once would benefit both.
- Does the logs-anomalies caching fix (needed for the UI toggle) also
  reduce risk for the MCP path, since an agent-driven investigation could
  also call `run_scan` repeatedly within one session?

## PoC scope (minimal, verifiable against a local `hogli` instance)

Picks the Error Tracking path only — it needs no caching work and no
dependency on an experimental flag, unlike logs anomalies. Team-wide only
(no service scoping); that's the documented gap above, not a PoC omission.

### Backend

1. `tach.toml`: add `"products.error_tracking"` to `products.metrics`'s
   `depends_on`. Currently metrics depends only on `posthog` — the trace
   pivot never needed a backend cross-product import (it reads `trace_id`
   directly off `metric_samples`, and only the frontend imports
   `products/tracing/frontend/traceLinks`). This is a new, real dependency
   edge, not a workaround; both products are isolated, and
   `error_tracking.backend.facade.api` is already exposed to depending
   modules under the canonical "Facade + views" interface every isolated
   product shares.
2. `products/metrics/backend/facade/contracts.py`: add a `MetricErrorSpike`
   dataclass (`detected_at: str`, `issue_id: str`, `issue_name: str | None`).
3. `products/metrics/backend/facade/api.py`: add
   `list_metric_error_spikes(*, team, date_from, date_to) -> list[MetricErrorSpike]`,
   calling `error_tracking.backend.facade.api.list_spike_events(team_id=team.id, date_from=..., date_to=...)`
   and adapting the result. Module-level import, not deferred — this is a
   permanent dependency, not a circular-import workaround.
4. `products/metrics/backend/presentation/api.py`: add an `error_spikes` GET
   action on `MetricsViewSet`, mirroring the existing `attribute_values`
   action's shape (query params `dateFrom`/`dateTo`, response
   `{"results": [...]}`). Same `metrics:read` scope as every other action;
   no new permission surface.
5. `hogli build:openapi` to regenerate the generated frontend types
   (`products/metrics/frontend/generated/api*.ts`).

### Frontend

6. `metricsSamplesLogic.tsx`: add a `loadErrorSpikes` loader, a
   `showErrorSpikes` toggle (reducer + action), and a selector adapting
   results into the exemplar-marker shape.
7. `MetricsExemplarMarkers.tsx`: add an optional per-marker `color`, so error
   spikes render visually distinct from trace exemplars (default unchanged,
   backwards compatible).
8. `MetricsViewer.tsx`: merge trace exemplars and error-spike exemplars into
   the existing `exemplarMarkers` array passed to `MetricsSeriesChart` (no
   change needed to that component); add a `LemonSwitch` toggle; clicking an
   error-spike dot navigates to `urls.errorTrackingIssue(issueId, { timestamp })`.

### Explicitly out of scope for the PoC

- Service-name scoping (documented gap above; needs either a facade/model
  change in Error Tracking or the trace_id-join approach).
- Logs anomaly overlay (needs the caching fix first; separate follow-up).
- MCP tool flag flips (`metrics-samples-create`, `error-tracking-spike-events-list`)
  and the `characterize-metric-anomaly.md` prompt extension — tracked above,
  not needed to prove the UI overlay works.
- Access-control polish beyond reusing the existing `metrics:read` scope.

### Verification plan — executed

Real spike events require cymbal + Redis + a Temporal workflow to fire
Error Tracking's actual detector — too much infrastructure to stand up just
to prove this overlay. Verification instead:

1. **Done.** `tach check --dependencies --interfaces` passes with the new
   `products.metrics` → `products.error_tracking` edge.
2. **Done, at the facade layer.** Seeded an `ErrorTrackingIssue` +
   `ErrorTrackingSpikeEvent` directly against the shared local Postgres
   (via `manage.py shell`, since the infra containers were already up from
   another worktree) and called `list_metric_error_spikes(...)` directly —
   confirmed it returns the seeded row correctly, end to end through the
   real cross-product facade call.
3. **Done, at the HTTP layer.** Added `TestMetricsErrorSpikesApi` (Django
   `APIBaseTest`) exercising the actual `GET .../metrics/error_spikes/`
   endpoint against a seeded spike, plus extended the existing
   `test_none_access_blocks_every_metrics_action_before_validation`
   parameterized case with `error_spikes` so the access-control gate is
   covered like every other action. `pytest products/metrics/backend/tests/test_api.py`:
   18/18 pass. A broader `pytest products/metrics/backend/tests/` run is
   clean except two pre-existing failures in
   `test_metrics_query_runner.py` (a `TeamCustomerAnalyticsConfig` fixture
   gap in the generic `/query/` endpoint's cache-key path) — unrelated to
   this change, confirmed by reading the stack trace: neither file touches
   `error_tracking` or the new action.
4. **Done, at the frontend logic/component layer.** Regenerated OpenAPI
   types (`hogli build:openapi-schema` + the orval `openapi:types` step;
   the chained `build:widget-types` step failed on an unrelated missing
   `orval` package in this fresh worktree — fixed by `pnpm install`, since
   it wasn't specific to this change) and confirmed `metricsErrorSpikesRetrieve`
   / `_MetricErrorSpikeApi` landed in `products/metrics/frontend/generated/`.
   Extended `metricsSamplesLogic.test.ts` (2 new cases: the toggle gates the
   fetch, and enabling it fetches + derives `errorSpikeExemplars` correctly)
   and `MetricsExemplarMarkers.test.tsx` (1 new case: a marker-specific
   `color` renders distinctly from the default). All pass; the pre-existing
   suites for both files are unaffected. `pnpm typescript:check` is clean
   for every file this PR touches (two unrelated pre-existing gaps
   remain — `@posthog/hogvm` isn't built in this fresh worktree — in files
   this PR doesn't touch).
5. **Not done: live browser confirmation.** Starting this worktree's own
   `hogli start -y -d` hit a `debugpy` port collision — another worktree's
   backend process was already holding the debug port on this machine.
   Rather than kill a process that may belong to someone else's active
   session, verification stopped at the pytest/Jest layer above, which
   exercises the real endpoint and real logic more rigorously than a manual
   click-through would. Loading the Metrics viewer and clicking a live
   marker is the one open item if a human wants to eyeball the actual
   chart rendering — it needs a port-free `hogli start` and a team with
   `METRICS` feature-flagged on and real metrics ingested.

## Open design questions (deferred)

Manual verification against seeded data surfaced a design question worth
settling before this goes past PoC, not a bug: the PoC currently renders
trace exemplars and error-spike markers as the same kind of visual element
(a small circle) in the same position (pinned to the plot baseline),
distinguished only by color.

- **Same element type or not?** A shared dot shape reads as "these are the
  same kind of thing, just colored differently," which may undersell that
  one pivots to a trace and the other to an error-tracking issue with very
  different downstream context. A distinct shape or icon per kind (not just
  color) could make the two pivots more discoverable at a glance, especially
  for a colorblind user for whom blue-vs-red is not a reliable signal.
- **Baseline placement or not?** Both marker kinds sit at the bottom of the
  chart regardless of the metric value at that timestamp, which keeps them
  from occluding the series lines but also decouples them from "what the
  metric was doing" at that moment. Placing a marker at (or near) the
  series value itself would tie it more directly to the spike/anomaly it
  represents, at the cost of more collision handling against the plotted
  lines and against each other.

Neither question blocks the PoC's purpose (proving the query path and the
click-through exist); both are worth a real design pass before this
overlay ships beyond a feature-flagged alpha.
