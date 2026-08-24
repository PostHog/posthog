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
