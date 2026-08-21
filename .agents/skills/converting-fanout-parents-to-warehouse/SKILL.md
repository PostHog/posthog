---
name: converting-fanout-parents-to-warehouse
description: Convert an existing warehouse source's fan-out children from re-fetching their parent API on every sync (parent_source="api") to reading the parent schema's synced Delta table (parent_source="warehouse"). Use when opting a source into warehouse fan-out parent reuse, deciding whether a fan-out parent qualifies, adding a parent_row_filter, or planning and validating the per-team rollout of a converted source.
---

# Converting fan-out parents to warehouse reuse

A fan-out child re-fetches its whole parent listing on every sync — syncing `issue_hashes` re-pulls all of `issues` first.
Conversion makes the child stream parent rows from the parent schema's already-synced Delta table instead, turning ~N paged API calls into one filtered parquet scan.
It is a soft dependency: any run whose parent table is unusable falls back to the parent-API path, so a conversion can never break a schema that syncs today.

This skill is the conversion procedure.
The runtime machinery and its constraints (fallback gates, streaming rules, sync-type allow-list, physical types, stale-parent 404s) live in `implementing-warehouse-sources` § "Reading the fan-out parent from the warehouse" — read that section first and keep this file free of duplicates of it.

Work the steps in order. Each one can end the conversion; stopping early with "not worth it" or "disqualified" is a correct outcome, not a failure.

## Step 0 — measure whether it pays

The saving is a fixed per-run cost: the parent listing the child no longer re-pulls.
It is worth chasing only when that listing is actually expensive.

Measure, per candidate child, over the production job stats (internal: the dogfood project's `postgres_posthog_externaldataschema` / `externaldatajob` / `externaldatasource` mirror tables; results silently truncate around 100 rows, so aggregate):

- parent `rows_synced` avg and max — the size of the listing every child run re-pulls
- child runs per week across the fleet — how often that cost is paid
- child run duration p50 — how large the parent fetch is relative to the whole run

Skip guidance, not hard rules:

- A parent averaging a handful of rows (one API page) saves one request per run. Do not convert it; the Delta read plus fallback path costs more in moving parts than it returns.
- Filter by `source_type` in every query — schema names collide across sources (`documents`, `coupons` exist as user tables in SQL sources).
- Expect the payoff to concentrate: in a typical source most fan-out parents are tiny and one or two are large. Convert the large ones only; leaving the rest on `parent_source="api"` is the intended end state, not a gap.

**Payoff and parity risk rise together.**
A parent listing gets big by accumulating, and accumulating listings are exactly the ones vendors eventually bound server-side (retention, archiving, plan limits).
Ranking candidates by savings alone selects for the parents most likely to fail step 1 — budget the classification work accordingly instead of treating it as a formality.

## Step 1 — classify the parent

The warehouse read must reproduce the API path's effective row set.
The parent table accumulates every row ever synced, while the vendor's listing usually does not return all of them, so classify what the listing actually bounds before touching config.
The three cases and their handling are specified in `implementing-warehouse-sources`; this is the procedure for deciding which case you are in.

Classify empirically, against a real vendor account — vendor docs under-document server-side clamps, and the dangerous bounds are per-account and invisible in our code:

1. Walk the full listing (every page, not page one) with no explicit bounds, and count.
2. Walk it again with explicit wide bounds (date range, status filters) and compare. A difference reveals what the default request hides; identical counts under both suggest either a full collection or a clamp that overrides parameters — distinguish them in the next step.
3. Take items older than any suspected bound (seed backdated data if the account is too small or too fresh to have any) and call the child endpoints for them directly. Items absent from the listing whose child endpoints still serve normally are the signature of a silent clamp: the snapshot will fan out over rows the API path never would.
4. If the source already windows its parent walk in code (a watermark early-stop, an explicit date filter), the listing's effective set is that window — the warehouse read must be filtered to the same window, never widened to the full table.

Verdicts:

- Full collection confirmed → convert with no filter.
- Bound confirmed and expressible from our side (a fixed window, or the child's own watermark) → convert with `parent_row_filter`.
- Bound depends on state we cannot know (plan tier, retention, archiving policy) → **disqualified**; leave `parent_source="api"` and record why next to the config so nobody re-attempts it blind.
- **No account to probe with → treat as disqualified.** An unverifiable parent fails closed; "the docs say it returns everything" is not a classification.

## Step 2 — convert

The diff for a qualified parent is deliberately small:

- Set `parent_source="warehouse"` on the child's `DependentEndpointConfig` in the source's `settings.py`.
- For a bounded parent, set `parent_row_filter=ParentRowFilter(field=..., not_older_than=...)` beside it. Config-level filters are static; a per-run watermark bound (`not_before`) requires custom source code that builds the filter at resolve time — see Sentry's tag-values iterator for the pattern.
- Wire `get_required_parent_schemas` on the source to `required_parents_from_endpoint_configs(ENDPOINTS, schema_name)` if it doesn't already; add explicit entries only for custom-iterator children that carry no `DependentEndpointConfig`.
- The parent must be a real, selectable schema of the same source producing its own Delta table. A synthetic fan-out parent (an endpoint config that is deliberately not a schema) has no table to read; either map the fan-out onto the real sibling schema that covers the same endpoint — verifying the row set and columns match what the fan-out resolves — or leave the child on the API path.
- Check every `include_from_parent` field against the physical-type caveat in `implementing-warehouse-sources` before shipping; ids are safe, timestamps and nested objects usually are not.

## Step 3 — test

The machinery invariants — fallback gates, 404-ignore injection, flag-off behavior, resume checkpointing, filter validation, version pinning — are owned by the shared suites (`common/rest_source/tests/test_fanout.py`, `test_warehouse_parent.py`, `workflow_activities/tests/test_import_data_sync.py`).
Do not re-test them per source; a conversion that copies those cases is testing the pipeline, not the conversion.

A config-driven conversion adds exactly two things:

- A required-parents contract test: `get_required_parent_schemas` returns the parent for converted children and `[]` for everything else, parameterized over the source's schemas. It is a checked statement of which children opted in — the blast radius a reviewer reads — so it cannot be shared.
- A call into the shared parity harness in `common/rest_source/tests` with the source's own config: the harness fabricates parent rows from the child's fan-out config, serves them through the API path and through a temporary Delta table, and asserts the child emits identical rows both ways. This catches what generic-machinery tests structurally cannot — config-level mistakes such as a `resolve_field` the config doesn't fetch, an `include_from_parent` field whose physical type differs between paths, or a filter field the parent table stores unfilterably. If the harness doesn't exist yet, your conversion is the first config-driven one: build it in the shared tests as part of the conversion, not as a per-source copy.

Custom-iterator children (no `DependentEndpointConfig`) can't ride the harness; they keep bespoke tests for their gating, filtering, and 404 handling — Sentry's suite (`sources/sentry/tests/test_sentry.py`) is the reference.

## Step 4 — validate and roll out

Rollout rides the existing per-team `warehouse-fanout-parent-reuse` flag — a converted source needs no new flag, and flag-off is the rollback for every source at once.
Each run pins its flag decision at start, so a rollback drains: in-flight runs finish on the path they started with.

- First, one dogfood or internal team with the source configured: run the child flag-off then flag-on, and require identical row counts before reading anything else. (If flags don't evaluate in your dev environment, hardcode the gate locally rather than concluding the feature is broken.)
- Widen to real teams only after parity holds, and judge the result in this order:
  1. **Failures before speed.** Count failed runs and `data_imports.fanout_parent_rows_streamed` events with `outcome=failed` first; a duration comparison filtered to completed runs silently excludes exactly the teams a bug is hurting.
  2. **Rows flat.** Child `rows_synced` must match the pre-conversion baseline. A jump means the scan is not bounded the way step 1 concluded — pull the flag and re-classify.
  3. **Duration, paired.** Compare each team against its own pre-conversion runs, not team-vs-team. Zero-row runs isolate the fixed parent-fetch cost and are the cleanest signal; row-heavy runs are dominated by child work and queue time and will look noisy.
- `fanout_parent_rows_streamed` (warehouse path: rows, outcome, filtered) against `fanout_parent_rows_consumed` (either path: running total handed to the child) is the per-run fan-out size comparison — those two logs are how you verify the warehouse set matches the API set in production, per team, without guessing.
