# Experiment exposure rewrite at ingestion

Design notes for moving experiment analysis off `$feature_flag_called` and the per-flag
`$feature/<key>` properties, onto a dedicated `$experiment_exposure` event and a single
`$experiment_exposures` property, by rewriting events during ingestion rather than waiting on SDK
releases.

Companion to the exposure RFC (`requests-for-comments-internal#1223`) and the flag/experiment
integration RFC (`requests-for-comments-internal#1097`). This document records what the code and the
production data actually support, which differs from both RFCs in a few places that matter.

## Where the cost actually is

Two separate things carry flag data, and they are worth very different amounts. Sizing for both was
measured separately; the figures live in the internal analysis rather than in this repo.

| Component                                                                               | Relative weight                                       |
| --------------------------------------------------------------------------------------- | ----------------------------------------------------- |
| Whole `$feature_flag_called` events                                                     | the smaller share of flag-attributable property bytes |
| `$feature/<key>`, `$active_feature_flags`, `$feature_flag_payloads` on all other events | roughly three times the above                         |

Both are also heavily concentrated rather than evenly spread: a small number of projects that attach
very large numbers of flags to every event dominate the totals, so an instance-wide average
overstates what a typical project would save.

Two consequences for planning:

1. The RFC's in-scope work (duplicate the flag-called event, eventually drop it) addresses the
   smaller share. The per-event properties it puts out of scope are the larger prize, which is why
   this design covers both halves even though only one can ship without customer comms.
2. Before quoting any of this as a saving, note that all of these measurements are of
   **uncompressed** bytes.
   `$active_feature_flags` repeats the same array on every event and `$feature/<key>` values are
   almost all `true`/`false` or a short variant name, so they compress far better than the average
   property. The real on-disk saving is materially lower than the uncompressed share, and nothing in
   the ingestion metrics can tell us by how much. Getting that number needs a ClickHouse experiment
   comparing `data_compressed_bytes` for two tables built from the same events, one with the flag
   keys stripped.

## Classifying an exposure without a lookup

The goal is to decide, from the event payload alone, whether a flag evaluation is an experiment
exposure, so ingestion needs no flag or experiment lookup.

Sampling live `$feature_flag_called` traffic for the candidate signals gives a clear ordering:
a boolean `$feature_flag_response` is by far the most common case, a variant-string response is a
minority, a small remainder has no response property at all, `$feature_flag_id` is missing on a large
fraction, and `$feature_flag_has_experiment` is present on only a tiny sliver.

Three things follow.

**`$feature_flag_has_experiment` already exists but is not usable alone yet.** RFC 1223 says "we
don't yet have an explicit signal that a flag is related to an experiment". The signal does exist and
is wired end to end: the Rust `/flags` service computes it from the flag's linked-experiment check
and returns it in `FlagDetailsMetadata`, and it is a documented event property. It is simply not
being sent by SDKs at meaningful volume. So this is an SDK-adoption gap, not a missing capability,
and the heuristic below is a bridge rather than a permanent design.

**Do not key exposures by flag id.** `$feature_flag_id` is absent on a large fraction of
flag-called events, so the map key has to be the flag key, which is always present.

**The multivariate heuristic works today and breaks under RFC 1097.** Treating a non-boolean
response as an experiment captures the minority of flag-called events that could plausibly be
exposures. But RFC 1097 decouples a flag's return type from its release type specifically so an experiment can
run on a boolean flag, and it also requires that a targeted-release rule returning a variant-shaped
value must _not_ be counted as an exposure. Once that lands, the value's type stops correlating with
experiment membership in both directions.

The classifier therefore prefers `$feature_flag_has_experiment` when present and falls back to the
response type, so that improving SDK adoption improves accuracy without another ingestion change. The
long-term fix is for `/flags` to report the rule type that produced the value, per RFC 1097, at which
point the fallback should be deleted rather than tuned.

## Custom exposure criteria is the real constraint on the properties half

An experiment can be configured to count exposures on a custom event or an action instead of
`$feature_flag_called`. In that mode the variant is read from `$feature/<flag_key>` **on the
customer's own event**:

- `products/experiments/backend/hogql_queries/experiment_exposure_query_builder.py`,
  `ExposureQueryBuilder.build_variant_property` returns `properties.$feature/<flag_key>` for
  anything that is not the default `$feature_flag_called` event.
- `products/experiments/backend/hogql_queries/exposure_query_logic.py`,
  `get_exposure_event_and_property` makes the same decision for callers outside the builder.

This is why the per-flag properties cannot simply be deleted, and it is the whole reason RFC 1223 put
them out of scope. It is a solvable problem rather than a blocker: if every event carries a
`$experiment_exposures` map of flag key to variant, custom exposure has an equivalent source, and the
per-flag properties become removable.

Only variant-valued entries need preserving. An experiment requires a variant, and boolean
`$feature/<key>` values come from boolean flags that cannot host an experiment under today's model.
Boolean entries are the large majority of `$feature/` bytes, so excluding them is what makes the
map much smaller than what it replaces. That exclusion has the same expiry date as the classifier heuristic: it must
become rule-type-driven when experiments on boolean flags ship.

**Stripping still needs customer comms, for a different reason than the RFC gives.** Experiments can
be migrated off `$feature/<key>` transparently. But those properties are also a general filtering and
breakdown surface in ordinary insights, and customers filter on boolean flag values there. Removing
them breaks saved insights regardless of what experiments do. So the mapping is safe to ship now and
the stripping is not, and the savings live almost entirely in the stripping.

## Rollout modes

`INGESTION_EXPERIMENT_EXPOSURE_MODE`, matching the shape already used by the `$feature_flag_called`
dedup feature:

- `disabled`: no classification, no counters. The default, so merging changes nothing.
- `metrics`: classify every flag-called event and every event carrying `$feature/*`, and record what
  the rewrite would produce. Mutates nothing, emits nothing. Intended to run fleet-wide to size the
  migration.
- `enabled`: additionally write the `$experiment_exposures` property and emit the duplicate
  `$experiment_exposure` event, gated to `INGESTION_EXPERIMENT_EXPOSURE_TEAMS`.

`metrics` is deliberately not the default even though it is non-mutating, because it adds a
serialization pass on a large fraction of events. Turning it on is an env-var change requiring no
deploy, which keeps the "always-on monitoring" goal one flag flip away rather than baking a
fleet-wide cost change into a merge.

Counters (`ingestion_experiment_exposure_*`) are labelled so the two halves can be read separately:
`flag_called` versus `exposure` bytes size the event duplication, `feature_properties` versus
`exposures_map` bytes size the property mapping.

## Migration sequence

1. **Metrics fleet-wide.** Confirm the modelled savings against the numbers above, and see the
   per-team distribution rather than the average.
2. **Enable for one internal project first.** Both the duplicate event and the property mapping,
   additive only. Verify
   exposure counts match between `$feature_flag_called` and `$experiment_exposure` for the same
   experiments.
3. **Teach the query layer to read either source.** The modern engine has a genuine chokepoint at
   `ExposureQueryBuilder.build_variant_property`, so exposure, mean, ratio and retention metrics
   follow from one change. Four other places reimplement the same decision and need their own
   change: `exposure_query_logic.get_exposure_event_and_property`, the legacy
   `ExperimentTrendsQueryRunner` and `ExperimentFunnelsQueryRunner`, `max_tools.py`, and the
   deliberate frontend duplicate in `frontend/src/scenes/experiments/exposureContract.ts`.
   A start-date cutoff per RFC 1223 avoids backfilling.
4. **Roll the duplicate out broadly, then stop capturing `$feature_flag_called`.** This is where the
   smaller component is realized. Until then the duplicate is a net cost increase, not a saving.
5. **Strip the per-event flag properties.** The larger component, and the step that needs customer
   comms because of the insights surface, not the experiments one.

## Materialization

`$feature/<key>` is already served by a materialized `Map(String, String)` column. `property_groups`
defines a `feature_flags` group matching `$feature/%`, the column exists and is populated on
`sharded_events` in production, and HogQL rewrites `properties.$feature/foo` into
`properties_group_feature_flags['$feature/foo']` with bloom-filter indexes on keys and values.
`PropertyGroupsMode.OPTIMIZED` is the Cloud default, so this is live rather than dormant.

Two corrections to the assumptions this work started from:

- There is no need to add a Map column for flag values. One exists. The premise that these
  properties are parsed out of the raw JSON blob on every query does not hold on Cloud. If experiment
  queries are slow, the cause is elsewhere and should be measured before any migration is written.
- `$active_feature_flags` is not the precedent for the "one column, many values" pattern. It is
  materialized as a scalar string (an `Array(String)` JSON subcolumn in the new events schema), and
  it holds only flag keys with no variant values, so it demonstrates nothing about keyed lookup.
  `properties_group_feature_flags` is the precedent to cite.

A new `$experiment_exposures` map property will be picked up by the `custom` property group
automatically, since it does not match the `$feature/%` or `$ai_%` filters. If experiment queries
want their own column, the pattern to copy is `PropertyGroupDefinition` in
`posthog/clickhouse/property_groups.py`, not the `materialize()` helper, which only produces scalar
columns. Adding one is a sharded-table migration plus a partition-by-partition
`MATERIALIZE COLUMN` backfill, so it should wait until step 3 shows a measured query problem.
