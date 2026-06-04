# HogQL property/materialization lowering: consolidation design

## Status

Design note + one safe dedup slice landed. Full consolidation is **blocked** on the
non-nullable materialized-column encoding (see "Why it's blocked").

## What "property lowering" means here

A HogQL `properties.$foo` access (`ast.PropertyType`) must become a concrete ClickHouse
expression. Two decisions drive that:

1. **Physical source** — which stored column actually holds the value: a statically
   materialized column (`mat_$foo`), a dynamic materialized slot (`dmat_string_3`), a
   property-group `Map` column (`properties_group_custom['$foo']`), or, if none exist, a
   `JSONExtract` over the raw `properties` JSON string.
2. **Semantic coercion** — whether the value is wrapped in `toFloat` / `toDateTime` /
   `toBool` / kept as `String`, based on the property's taxonomy type, plus the
   `nullIf(nullIf(col, ''), 'null')` unwrapping that compensates for non-nullable column
   storage.

Today these decisions are **smeared** across several stages instead of being computed once.

## Current pipeline (verified)

`posthog/hogql/printer/utils.py` (the `clickhouse` branch) runs, in order:

1. `resolve_types`
2. `build_property_swapper` — collects per-property taxonomy info into
   `context.property_swapper` (`event_properties`, `person_properties`, `group_properties`,
   including any `dmat` slot)
3. `PropertySwapper` pass #1 — **groups only** (must run before lazy tables: the group
   join and S3 join rely on lazy-table nodes still being present)
4. `resolve_lazy_tables`
5. `PropertySwapper` pass #2 — **event/person** (must run *after* where-clause
   optimizations / predicate pushdown, which need the un-swapped property nodes)
6. printer (`BasePrinter` / `ClickHousePrinter`)

A feature branch inserts `events_predicate_pushdown` between steps 4 and 5 (gated, off by
default in prod). It is **not** present on this branch (`utils.py` goes straight from
`resolve_lazy_tables` to `swap_properties`). It matters here because it adds a *third* copy
of the physical-source derivation (see below) — that third copy is the main motivation for
consolidating toward a single resolver.

`PropertySwapper` (`posthog/hogql/transforms/property_types.py`) conflates two concerns:
it wraps properties in type-coercion casts **and** carries property-handling metadata. The
two-pass split exists purely because of ordering constraints (3) and (6) above — not
because the logic naturally wants to run twice.

The **physical-source decision** is made at print time, and as of master is implemented
in two places that must agree byte-for-byte:

- `posthog/hogql/printer/base.py` — `_get_all_materialized_property_sources`
  (`visit_property_type` → `_get_materialized_property_source_for_property_type` →
  this generator). The authoritative priority chain: static mat column → dmat slot →
  property-group column.
- `posthog/hogql/printer/clickhouse.py` — `_get_property_group_source_for_field`, the
  `JSONHas` existence-check path (`_get_optimized_property_group_call`). It re-derives the
  property-group source on its own because `JSONHas` deliberately wants the property-group
  `Map` column even when a `mat_` column would otherwise win (a non-nullable `mat_` column
  can't answer "is this key set?").

On the feature branch there is a **third** copy in
`posthog/hogql/transforms/events_predicate_pushdown.py`
(`_materialized_column_for_property`), which re-derives the same physical column so the
pushed-down subquery exposes exactly the column the outer reference will read. Its
docstring explicitly says it "mirrors `BasePrinter._get_all_materialized_property_sources`'
priority". That mirroring is the smell this design targets.

## The target: single-stage lowering

A single authoritative resolver, called everywhere a physical source is needed:

```text
resolve_physical_source(property_type) -> ResolvedPropertySource
    kind:        MAT | DMAT | GROUP | JSON
    column/expr: the printable column or the raw-JSON fallback
    is_nullable: bool        # drives nullIf-unwrapping
    semantic:    Float | DateTime | Boolean | String   # drives coercion
```

With that in place:

- `base.py`'s `visit_property_type`, `clickhouse.py`'s `JSONHas` path, and the pushdown
  transform all call one function — no mirrored priority logic.
- Coercion becomes a property of the resolved node (`semantic`) rather than logic spread
  between `PropertySwapper` and the printer.
- Ideally the resolution runs **once**, early, attaching `ResolvedPropertySource` to the
  `PropertyType`, so the printer is a pure formatter.

## Why it's blocked (out of scope here)

The single biggest reason the printer can't be a pure formatter today is the
**non-nullable column encoding**. Materialized columns are `String` (not `Nullable`),
so an unset property and an explicit empty string are indistinguishable, and a JSON
`null` is stored as the literal string `'null'`. The printer compensates at emit time:

```python
# base.py visit_property_type
nullIf(nullIf(events.`mat_$foo`, ''), 'null')
```

Consequences that block consolidation:

- **The physical-source choice is entangled with existence semantics.** `JSONHas` can't
  use a `mat_` column at all (it can't represent "absent"), which is exactly why the
  `clickhouse.py` path *must* diverge from the main priority chain. You cannot collapse the
  two source resolvers into "always pick the best column" until columns can represent
  absence — i.e. until they're `Nullable`.
- **Coercion can't be fully hoisted to resolution.** The `nullIf(nullIf(...))` unwrap, the
  `MaterializationMode.LEGACY_NULL_AS_STRING` vs `..._AS_NULL` split, and the
  `$ai_trace_id` / `$ai_session_id` / `$ai_is_error` index-friendly exceptions all live in
  `visit_property_type` because they depend on the non-nullable encoding. Moving them into a
  resolved node would require the encoding to be uniform first.
- **The two `PropertySwapper` passes** are an ordering constraint (groups before lazy
  tables; event/person after where-clause optimizations), not a nullable-encoding problem —
  but collapsing them risks the where-clause optimizations that read un-swapped property
  nodes, so it's explicitly out of scope here.

Removing the `nullIf(nullIf(...))` wrapping requires **rematerializing all columns as
`Nullable`** (the `# TODO: rematerialize all columns ...` note in `visit_property_type`).
That's a large, separate data-migration effort. Until then, the printer must stay the place
where nullable-compensation happens, and full single-stage lowering can't be completed.

## What landed in this PR (the safe slice)

Deduplicated the property-group source **construction**. `clickhouse.py`'s
`_get_property_group_source_for_field` (the `JSONHas` path) now delegates the
`PrintableMaterializedPropertyGroupItem(...)` construction to the existing
`_yield_property_group_columns`, the same helper `_get_all_materialized_property_sources`
already uses. One source of truth for "given an events field + key, build the property-group
accessor".

Deliberately **not** changed, to keep output byte-identical:

- The resolution preamble (`resolve_database_field`, alias stripping, table-name and
  field-name resolution) stays duplicated between the two methods. They already agree on the
  table-name source — the main path calls `self._get_table_name(table)`, which
  `ClickHousePrinter` overrides to `to_printed_clickhouse(self.context)` (`base.py` default →
  `clickhouse.py` override), the same call the `JSONHas` path makes inline — so the table
  name is *not* a divergence. What they do not share is error handling:
  `_get_all_materialized_property_sources` **raises** `QueryError` on an unresolvable field,
  while `_get_property_group_source_for_field` **returns `None`** to mean "no optimization,
  fall back to `JSONHas(properties, …)`". Merging the preambles has to reconcile
  raise-vs-return, so it is a follow-up, not a no-op.
- The `JSONHas` path still intentionally bypasses the `mat_`/`dmat` priority — that
  divergence is correct and stays until `Nullable` columns exist (see above).

Verification: this is a pure refactor and must emit byte-identical SQL. Run with **no**
`--snapshot-update`:

- `hogli test posthog/hogql/printer` — 716 passed, 23 skipped, 1 xfailed; **186 snapshots
  unchanged**.
- `hogli test posthog/hogql/transforms` — **160 snapshots unchanged**. Four group/cohort
  tests fail (`test_group_property_types`, `test_group_boolean_property_types`,
  `test_group_types_are_the_same_in_persons_inlined_subselect`,
  `test_inline_static_always_uses_cohortpeople`), but they fail identically on the branch's
  base commit with this change reverted. They are environment fixture errors (personhog
  gRPC group creation hits `duplicate key … unique_team_group_key_group_type`, after which
  group-type resolution can't find the group), not a behavior change from this slice.
