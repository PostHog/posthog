# Metrics — product guardrails and roadmap

**Status:** decisions — owners @daniel-v, #team-apm.
**Sibling docs:** [`dashboard-mvp.md`](./dashboard-mvp.md) (the alpha stack), [`deployment-layout.md`](./deployment-layout.md) (what runs where).

This doc records the load-bearing product and architecture decisions for taking Metrics from private alpha toward GA:
the invariants we commit to now while changing them is still cheap, the guardrails that must exist before we widen access, and the workstreams we are deliberately _not_ doing yet, each with the trigger that would start it.
Every claim cites the file it was validated against.

## Invariant 1 — user-visible schema never equals physical schema

Users write raw HogQL against `posthog.metrics` (the `/metrics` SQL tab) and save it into insights, dashboards, and alerts.
The moment customer-saved artifacts reference the physical `metrics1` column layout, that layout becomes effectively frozen: any storage change breaks saved customer queries.
This is how metrics platforms end up running multiple storage generations forever — the old layout can't be deleted because live product artifacts still read from it.
We are pre-GA, with two layouts already in ClickHouse (`metrics1` from `posthog/clickhouse/metrics/metrics1.py`, and `metric_series1`/`metric_samples1` from migrations `0283`/`0285`), so this window is the only cheap time to decouple.

**Decision:** re-register `posthog.metrics` as a `LazyTable` (precedent: `PersonsTable` in `posthog/hogql/database/schema/persons.py`) whose expansion is initially _identical_ to today's direct `metrics1` mapping — zero behavior change, pure indirection.
When the already-planned port to the series/samples layout happens ([`deployment-layout.md`](./deployment-layout.md) "post-alpha storage track"), it becomes a flip of the expansion to the `metric_samples` × `metric_series` join:
dual-read validated, per-team flag-gated (a correct use of feature flags — query path, Django-side), and instantly reversible by flipping the expansion back.
The `attribute_field()` helper remains the seam for the query runners' generated SQL;
the LazyTable is the equivalent seam for _user-authored_ SQL, which `attribute_field()` cannot protect.

Note the runner seam is currently leaky: `metric_query_runner.py` references `resource_fingerprint`, `aggregation_temporality`, and `histogram_bounds`/`histogram_counts` outside `attribute_field()`, and its rate/increase window partitions by `(service_name, resource_fingerprint, toString(attributes))` — a hand-rolled approximation of `series_fingerprint`.
The port simplifies that partition key to the real fingerprint.

## Invariant 2 — series identity is assigned once, at ingest

`series_fingerprint` is computed in `rust/capture-logs/src/metric_record.rs` (`compute_series_fingerprint`: SipHash-1-3, fixed key, length-prefixed, key-sorted maps, `metric_type` included in the identity) and carried verbatim to ClickHouse.
Storage never recomputes it, and nothing else may:
a second implementation of the hash anywhere (ClickHouse DDL, a backfill script, another service) is a series-identity split waiting to happen.
Anything that needs the fingerprint reads the stored column.

Corollary: we do not build a string-interning/registry service for series identity.
Hash-at-ingest gives us identity without a registry database, its write-path rate limiters, or its unremovable tables.
The cost — you can't enumerate label strings from the fingerprint — is already paid for by the `metric_attributes` facet table and the `metric_series` rows themselves.

## Guardrail — a new-series budget is the gate for opening ingest beyond the allowlist

Bytes-based limiting already exists and is shared infrastructure
(`MetricsIngestionConsumer` quota check on `metrics_mb_ingested` plus the per-team Redis token bucket in `nodejs/src/ingestion/pipelines/metrics/services/metrics-rate-limiter.service.ts`).
It cannot see the axis that actually kills a metrics store: **series identity**.
A producer comfortably under its byte budget can still put `user_id` or `request_id` in a label and mint millions of unique series,
permanently bloating `metric_series` on the shared logs cluster and degrading every query that joins against it.
Client-side SDK guardrails don't cover this either — remote-write and collector users never run our SDK.

**Decision:** before ingest opens beyond the allowlisted alpha teams, add a per-team budget on the rate of **new** `series_fingerprint`s:

- Existing-series samples are never limited — the budget caps identity _growth_, not traffic.
- An over-budget data point is dropped whole, with a counter and (eventually) an ingestion-warning surface.
  Never strip labels to "save" the point: the fingerprint is computed over the full label set, so stripping silently mints a _different_ series and corrupts identity instead of protecting it.
- Seam: `rust/capture-logs`, where the fingerprint is computed per record.
  The nodejs consumer is the wrong place — it passes opaque Avro batches through without decoding.
- Mechanism: the shared `limiters` crate (novelty check via per-team known-fingerprint cache, Redis-backed for cross-replica agreement), so other signals can reuse it if they ever grow an identity concept.

This is explicitly _not_ an alpha task; it is the pre-beta gate.

## Operability principle — dynamic ingest config uses ingestion's existing patterns, not feature flags

Per-team killswitches and limiter thresholds in the ingest path should be changeable without a deploy.
Ingestion already has two mechanisms for exactly this:
Redis-backed sets/thresholds (the billing quota limiter the metrics consumer already calls; the dynamic threshold source capture landed in `987ed12fd965`) and Postgres team config (how logs drop rules work).
Feature flags are the wrong tool here:
they are per-distinct-id product gating, they aren't wired into capture-logs or the ingestion consumers, and putting the flags service in the ingest hot path creates a dependency loop — the killswitch is needed precisely when this infrastructure is unhealthy.

No new workstream: fold this into the existing INFRA-B item (internal-infra exemption in `metrics-rate-limiter.service.ts`) when it lands, replacing the `METRICS_LIMITER_*` env-var-only configuration.

## Differentiator — cross-signal pivots

Our structural advantage is that metrics live next to every other signal in one query layer.
`metric_samples` already carries `trace_id`/`span_id`, the samples runner (`metric_event_samples_query_runner.py`) already handles the trace-id contract, and `MetricsSamplesPanel` already links metric samples to traces.

- **Trace exemplars** (shipping now): investigations (`investigation.py`) attach `trace_exemplars` from the anomaly window, and the viewer chart overlays exemplar dots that click through to the trace.
- **Metric → logs pivot** (follow-up): same `trace_id` join against the logs product facade.

## Logs-to-metrics rules — review checklist

When the generate-metrics-from-logs work lands, the rules it creates are a machine-driven producer of new series and need the same discipline as any producer, plus rule-level hygiene:

- **Dedup by query hash:** semantically identical rules must collapse to one extracted series, not one per rule copy.
- **Per-team rule budgets:** a bounded number of active rules, enforced at rule creation with a clear error, not silently at ingest.
- **Group-by cardinality gate:** refuse (or disable) a rule whose group-by would mint unbounded series; surface the disablement in the UI.
- **Visible rule state:** materialized status per rule (active / disabled / over-budget) — rules must fail visibly, never be silently eaten by the new-series budget above.

Later, this closes the alerting loop: an alert on a log query can auto-provision a rule so the standing evaluation runs against cheap pre-tallied metrics instead of re-scanning logs.

## Parked workstreams, with triggers

| Workstream                                                                                                     | Trigger to start                                                                         | Notes                                                                                                                                                                                                                                                           |
| -------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Saved/derived metric registry (named per-team metrics resolving to clauses + formula)                          | Packaging demand: SLO-style products, reusable team-defined metrics referenced by alerts | The facade contract already accommodates it — `MetricQueryRequest` is clauses + formula (`facade/contracts.py`); model precedent: `Endpoint`/`EndpointVersion` in `products/endpoints/backend/models.py`; alerts get resolution for free via `MetricsExtractor` |
| Rollup/downsampling tiers (5m/1h aggregate tables, longer TTLs, query-time tier selection in `_pick_interval`) | Retention promises beyond the 30-day `metric_samples` TTL                                | Design against the series/samples schema only, i.e. after the storage port — building rollups off `metrics1` would double the migration                                                                                                                         |

## Anti-patterns we commit to avoiding

- **No silent fallback between data sources.** A query answers from metrics storage or it errors; it never transparently re-runs against a different dataset and pretends the results are equivalent. Fallback magic becomes a permanent complexity tax and makes results unexplainable.
- **No second fingerprint implementation** (Invariant 2).
- **The facade stays the only cross-product seam.** Other products import `products/metrics/backend/facade/` and nothing else, so storage and runners can keep evolving under a stable surface. Widget/consumer PRs that need a new capability fix the facade contract, not reach around it.
