---
name: converting-fanout-parents-to-warehouse
description: Convert an existing warehouse source's fan-out children from re-fetching their parent API on every sync (parent_source="api") to reading the parent schema's synced Delta table (parent_source="warehouse"). Use when opting a source into warehouse fan-out parent reuse, deciding whether a fan-out parent qualifies, adding a parent_row_filter, or planning and validating the per-team rollout of a converted source.
---

# Converting fan-out parents to warehouse reuse

A fan-out child re-fetches its whole parent listing on every sync — syncing `issue_hashes` re-pulls all of `issues` first.
Conversion makes the child stream parent rows from the parent schema's already-synced Delta table instead, replacing the paged listing with one filtered parquet scan.
It is a soft dependency: any run whose parent table is unusable falls back to the parent-API path, so a conversion can never break a schema that syncs today.

This skill is the conversion procedure.
The runtime machinery and its constraints (fallback gates, streaming rules, sync-type allow-list, physical types, stale-parent 404s) live in `implementing-warehouse-sources` § "Reading the fan-out parent from the warehouse" — read that section first and keep this file free of duplicates of it.

All paths below are relative to `products/warehouse_sources/backend/temporal/data_imports/`.

Work the steps in order. Each one can end the conversion; stopping with "not worth it" or "disqualified" is a correct outcome, and is the outcome for most candidates.
**Step 1 needs a real vendor account**, which usually means asking a human and waiting — plan for it at the start rather than discovering it mid-conversion.

## Step 0 — measure whether it pays

The saving is one thing only: the parent listing's requests, which the child no longer issues.
Everything else about the run is unchanged.
So the decision is arithmetic, in requests rather than rows.

**Parent listing requests** = `ceil(parent_row_count / page_size)`.

- `parent_row_count` is the **full table size**, from `postgres_posthog_datawarehousetable.row_count`. Do not use the parent's `rows_synced` from a job row: on an incremental parent that is the changed-rows delta for that run, while the fan-out re-fetches the whole listing every time. The two differ by orders of magnitude on exactly the parents worth converting.
- `page_size` is per endpoint, from the source's endpoint config, not a global default. Some endpoints set `page_size_param=None` and return the collection unpaginated, which is one request regardless of size.

**Child requests per run** ≈ one per parent row for the common shape (a child endpoint keyed by parent id), so the listing's share of the run is roughly `1 / page_size`.
That ratio, not the parent's absolute size, decides the conversion.

Worked example, a source with 134 forms and a 200-row page size: the listing is 1 request, the child spends ~134, so conversion removes under 1% of the run's requests. No run frequency makes that worth new machinery — 587 runs a week of a 2% saving is still a 2% saving.

**The corollary is the important part: an unfiltered conversion of a one-request-per-parent-row child can never pay.**
Where conversion has paid, the win came from a `parent_row_filter` shrinking the parent set the child iterates — fewer child requests, not a skipped listing.
So treat filtering as the source of savings and ask what bound step 1 could apply, rather than ranking candidates by parent size.

Also gather, per candidate child:

- child runs per week across the fleet — how often the cost is paid, and whether a rollout will produce enough runs to validate against
- how many teams have the child enabled — the blast radius of a bad conversion

Do not try to estimate the listing's share of run time from job durations.
Parent and child durations are both dominated by queue time at small sizes, and no pre-conversion measurement separates them; the paired zero-row comparison in step 4 is the only reliable read, and it exists only after converting.

`references/measuring-payoff.md` has the queries, the access path, and the HogQL traps.

**When the arithmetic says stop, stop.**
The one-page rule is a rule, not a nudge: a listing that fits in one or two requests is not convertible, whatever a plan document or a candidate list says.
The only evidence that overrides it is a filter that removes child requests — if step 1 can bound the parent set, re-run the arithmetic with the bounded row count and decide again.

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
3. Take items older than any suspected bound (seed backdated data if the account is too small or too fresh to have any, and check the vendor accepts backdated writes — many silently drop or clamp them) and call the child endpoints for them directly. Items absent from the listing whose child endpoints still serve normally are the signature of a silent clamp: the snapshot will fan out over rows the API path never would.
4. If the source already windows its parent walk in code (a watermark early-stop, an explicit date filter), the listing's effective set is that window — the warehouse read must be filtered to the same window, never widened to the full table.

Drive the walk through the source's own client and paginator rather than raw HTTP, so the probe exercises the same param handling and pagination the sync uses.

Verdicts:

- Full collection confirmed → convert with no filter.
- Bound confirmed and expressible from our side (a fixed window, or the child's own watermark) → convert with `parent_row_filter`, then return to step 0 and re-run the arithmetic with the bounded row count.
- Bound depends on state we cannot know (plan tier, retention, archiving policy) → **disqualified**; leave `parent_source="api"`.
- **No account to probe with → treat as disqualified.** An unverifiable parent fails closed; "the docs say it returns everything" is not a classification.

## Recording a "no"

Most candidates end at step 0 or step 1, and an unrecorded "no" gets re-attempted by the next person with the same candidate list.
Record it where the next person will be standing: on the child's config, as an explicit `parent_source="api"` plus a one-line comment naming the reason.
`sources/sentry/settings.py` has the pattern (`# Not "warehouse": …`).
Keep it to the durable reason — the shape of the bound, or the request arithmetic — not the investigation.

## Step 2 — convert

The config flip is the visible part, and on its own it does nothing:

- Set `parent_source="warehouse"` on the child's `DependentEndpointConfig` in the source's `settings.py`.
- For a bounded parent, set `parent_row_filter=ParentRowFilter(field=..., not_older_than=...)` beside it. Config-level filters are static; a per-run watermark bound (`not_before`) requires custom source code that builds the filter at resolve time — see Sentry's tag-values iterator.
- Wire `get_required_parent_schemas` on the source to `required_parents_from_endpoint_configs(<CONFIG_MAPPING>, schema_name)`. Pass the **mapping of name → endpoint config** (e.g. `TYPEFORM_ENDPOINTS`), not the source's `ENDPOINTS`, which in most sources is `tuple(X_ENDPOINTS)` — a tuple of names the helper cannot look up. Add explicit entries only for custom-iterator children carrying no `DependentEndpointConfig`.
- **Thread the flag and source id into `build_dependent_resource`**: `source_id=inputs.source_id` and `use_warehouse_parent=inputs.fanout_warehouse_reuse`, in the source's module function. `sources/sentry/source.py` is the reference. Both parameters default to off, so a conversion that skips this silently takes the API path forever.

> [!WARNING]
> Skipping the threading fails **silently and invisibly**. `import_data_sync` logs `data_imports.fanout_parent_source parent_source="warehouse"` based on the flag and the parent's usability — it never sees whether the source passed `use_warehouse_parent` down. So the adoption telemetry step 4 tells you to trust will report a warehouse rollout that is not happening. Prove the wiring with the test in step 3; do not infer it from that log.

Two more constraints before shipping:

- The parent must be a real, selectable schema of the same source producing its own Delta table. A synthetic fan-out parent (an endpoint config deliberately kept out of the schema list) has no table to read; either map the fan-out onto the real sibling schema covering the same endpoint — verifying row set and columns match what the fan-out resolves — or leave the child on the API path.
- Check every `include_from_parent` field against the physical-type caveat in `implementing-warehouse-sources`; ids are safe, timestamps and nested objects usually are not.

## Step 3 — test

The machinery invariants — fallback gates, 404-ignore injection, flag-off behavior, resume checkpointing, filter validation, version pinning — are owned by the shared suites (`sources/common/rest_source/tests/test_fanout.py`, `sources/common/rest_source/tests/test_warehouse_parent.py`, `workflow_activities/tests/test_import_data_sync.py`).
Do not re-test them per source; a conversion that copies those cases is testing the pipeline, not the conversion.

A config-driven conversion adds three things:

- **A required-parents contract test**: `get_required_parent_schemas` returns the parent for converted children and `[]` for everything else, parameterized over the source's schemas. It is a checked statement of which children opted in — the blast radius a reviewer reads — so it cannot be shared.
- **A wiring test**: with the flag on, the source's module function reaches `build_dependent_resource` with `use_warehouse_parent=True` and the source id set. This is the only thing standing between a silent no-op conversion and production, per the warning in step 2. `sources/sentry/tests/test_sentry.py` has the shape.
- **A parity assertion**: the child emits identical rows through the API path and through the warehouse reader, using the source's own config. This catches what generic-machinery tests structurally cannot — a `resolve_field` the config doesn't fetch, an `include_from_parent` field whose physical type differs between paths, a filter field the parent table stores unfilterably.

There is no shared parity harness yet.
The first config-driven conversion builds one in `sources/common/rest_source/tests/`, and it is the largest single item in that conversion: it has to fabricate parent rows from the child's fan-out config, write them to a temporary Delta table, run the child both ways, and diff.
Budget it as such, size the conversion PR accordingly, and build it as a shared harness the next source can call rather than a per-source copy.

Custom-iterator children (no `DependentEndpointConfig`) can't ride the harness; they keep bespoke tests for gating, filtering, and 404 handling — Sentry's suite is the reference.

## Step 4 — validate and roll out

Rollout rides the existing per-team `warehouse-fanout-parent-reuse` flag — a converted source needs no new flag, and flag-off is the rollback for every source at once.
Each run pins its flag decision at start, so a rollback drains: in-flight runs finish on the path they started with.

- First, one dogfood or internal team with the source configured: run the child flag-off then flag-on, and require identical row counts before reading anything else. (If flags don't evaluate in your dev environment, hardcode the gate locally rather than concluding the feature is broken.)
- Widen to real teams only after parity holds, and judge the result in this order:
  1. **Failures before speed.** Count failed runs and `data_imports.fanout_parent_rows_streamed` events with `outcome=failed` first; a duration comparison filtered to completed runs silently excludes exactly the teams a bug is hurting.
  2. **Rows flat.** Child `rows_synced` must match the pre-conversion baseline. A jump means the scan is not bounded the way step 1 concluded — pull the flag and re-classify.
  3. **Duration, paired.** Compare each team against its own pre-conversion runs, not team-vs-team. Zero-row runs isolate the fixed parent-fetch cost and are the cleanest signal; row-heavy runs are dominated by child work and queue time and will look noisy.
- `fanout_parent_rows_streamed` (warehouse path: rows, outcome, filtered) against `fanout_parent_rows_consumed` (either path: running total handed to the child) is the per-run fan-out size comparison — those two logs are how you verify the warehouse set matches the API set in production, per team, without guessing.
