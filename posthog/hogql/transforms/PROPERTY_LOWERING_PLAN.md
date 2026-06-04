# Property-lowering pass — plan & status

## Goal

Move the `events.properties.$x` (and persons/groups) **property → physical-column** decision **out of the
ClickHouse printer** and into an explicit AST transform that runs **early** (before the events-predicate
pushdown). After that pass there are no `PropertyType` nodes left on the ClickHouse print path — the AST
already contains the concrete column expression (`mat_x`, a `dmat_string_n`, a property-group map access, or
a `JSONExtract` fallback). The printer shrinks to "just print the AST."

## Why (what this unblocks)

The events-predicate-pushdown transform wants to rewrite `FROM events JOIN … WHERE <events preds>` into a
pre-filtering subquery. The clean way is to project the needed columns into the subquery and repoint the
outer references to plain alias columns. That **breaks today** because the printer's property optimizations
(`_get_optimized_property_group_call` for `isNull`/`isNotNull`/`JSONHas`, and the skip-index comparison
rewrites in `clickhouse.py:536-901`) do `resolve_field_type(field)` and, finding a `PropertyType`, emit a
physical-column reference (e.g. `has(events.properties_group_custom, 'k')`) assuming that column is in scope.
When pushdown repoints the outer reference, the printer chases it back to the `PropertyType` and emits a
group/mat column the subquery never exposed → `Unknown identifier`.

The ~150 lines of materialized-column "prediction" machinery in `events_predicate_pushdown.py` exist purely
to keep those physical columns exposed so the chase succeeds. **If properties are already lowered to concrete
columns before pushdown runs, there is no `PropertyType` to chase** — pushdown projects/repoints ordinary
columns, the machinery deletes itself, and it generalizes to any table.

## Invariant: result-equivalence, NOT byte-identical

The printer builds the property-group and JSONExtract lowering as **raw strings**, not AST:
`printer/types.py:39` emits `f"{has_expr} ? {value_expr} : null"` — a `? :` ternary that **no HogQL AST node
reproduces**. So the lowering pass emits a **result-equivalent** form (`if(has(g,k), g[k], null)` via
`ast.ArrayAccess`; ClickHouse's `?:` *is* `if()`), which prints differently but returns identical results.

Therefore the verification bar for this refactor is **result-equivalence** (the execution/equivalence tests +
regenerated `.ambr` snapshots), **not** byte-identical snapshots. Do not try to make the lowered SQL match the
printer string-for-string — it can't, and shouldn't.

## Stages (each independently verifiable)

1. **Structured resolver — DONE, tested.**
   `posthog/hogql/transforms/property_lowering.py` :: `resolve_materialized_property_source(field_type,
   property_name, context) -> MaterializedPropertySource | None`. Mirrors the printer's priority
   (`base.py:1273-1334`): static `mat_*` → `dmat` slot → first property-group column, else `None` (JSON
   fallback). Carries `is_nullable` + the four skip-index flags for stage 3.
   Tests: `posthog/hogql/transforms/test/test_property_lowering.py` (4 passing).
   This is the single source of truth the printer, the lowering pass, and the pushdown collector will share.

2. **Lower-to-AST — DONE, tested.**
   `property_lowering.py` :: `lower_property_type(pt, context) -> ast.Expr | None`, built from the stage-1
   source, plus the `LowerProperties` CloningVisitor and `lower_properties(node, context)` entry point:
   - `materialized_column` (non-nullable, non-`$ai_*`): `nullIf(nullIf(Field(col),''),'null')`
     (single `nullIf` under `LEGACY_NULL_AS_STRING`); nullable / `$ai_*` single-key / `dmat`: bare `Field(col)`.
   - `property_group`: `if(has(Field(g), key), ArrayAccess(Field(g), key), null)`.
   - `None` (fallback): `JSONExtract`-trim-quotes over the raw `properties` Field — built from `JSONExtractRaw`
     / `nullIf` / `replaceRegexpAll`, all of which ARE registered HogQL functions (verified), so the AST
     prints. The printer reaches these via raw strings, but as `ast.Call` they print equivalently.
   - deep chain (`a.b`): wrap the head result in the JSONExtract form for `chain[1:]`.
   - Physical mat/dmat/group columns aren't HogQL schema fields, so `_synthetic_column_field` augments a copy
     of the table with a `DatabaseField` and points a fresh `FieldType` at it (same trick as the pushdown's
     `_inner_table_type_with_materialized_columns`), preserving any alias so the printed prefix is unchanged.
   - Returns `None` (printer keeps handling it) for: already-repointed `joined_subquery`, any
     `restricted_properties` on the team, empty chain, or a non-`TableType`/`TableAliasType` wrapper
     (VirtualTableType PoE, ColumnAliasedTableType, subquery types) — these are stage-3 coverage expansions.
   Verified by **execution result-equivalence** in `test_property_lowering.py`
   (`TestLowerPropertyTypeResultEquivalence`, 10 cases): printer's `visit_property_type` vs. lowered AST,
   executed against ClickHouse, identical rows — across JSON fallback, ENABLED/OPTIMIZED groups,
   AUTO/LEGACY_NULL_AS_STRING mat columns, deep chains, and a full SELECT+WHERE transform that also asserts
   **zero `PropertyType` nodes remain** after the pass.
   Caveat — `clear_types`: `LowerProperties` must construct `CloningVisitor(clear_types=False)`; the default
   `True` wipes every node's resolved type and printing then fails ("FROM clause ... before type resolution").

3. **Integrate + scalar cast — DONE, tested.**
   This refactor is **general and independent of the events-predicate pushdown** — the pushdown was only the
   example that exposed the printer's `PropertyType`-chasing. Lowering now runs **globally** for every
   ClickHouse query.
   - **Cast folded in:** `lower_property_type` now also applies the scalar cast (`toFloat` / `toDateTime` /
     `toBool`) for single-key event/person properties, reading the type the swapper already resolves into
     `context.property_swapper.event_properties[name]["type"]` (`_property_cast_type` + `_apply_property_cast`,
     mirroring `PropertySwapper._field_type_to_property_call`). So the cast and column-selection are one pass.
   - **Ordering resolved by running lowering *before* the swapper** (`printer/utils.py`, new `lower_properties`
     step right after pushdown, before `swap_properties`). The conflict dissolves: lowered properties are no
     longer `PropertyType`, so the swapper no-ops on them and only coerces the tail it still owns (group props
     via lazy joins, PoE virtual-table person props). No double-cast.
   - Verified by `TestPropertyLoweringCast` (numeric `>` compares numerically not lexically; Float64 result
     type; boolean coercion) + the existing `test_property_types.py` / `test_query.py` execution assertions
     (only failures are cosmetic SQL-text churn in `.ambr` snapshots + inline hardcoded-SQL `.py` assertions,
     plus pre-existing group-test personhog flakiness — **zero behavioral regressions**; response column names
     are stable because they derive from the HogQL-dialect prepare, which the CH-only lowering never touches).

4. **Deletions + coverage expansion — NEXT (deferred, safe to do incrementally).**
   - Lowering currently *coexists* with the printer's `visit_property_type` lowering and the swapper's
     property-cast branch — it handles the common cases (events/persons direct, single + deep chains), they
     handle the tail it returns `None` for. Both can stay until lowering covers 100%.
   - Expand coverage to the `None` cases (group props via lazy joins, PoE VirtualTableType person props,
     ColumnAliasedTableType, `restricted_properties`). Once nothing falls through:
     delete the printer's `visit_property_type` lowering (shrinks to the joined-subquery case), delete the
     swapper's property-cast branch (keeps only real-column timezone / S3 duties), and move
     `_get_optimized_property_group_call` + the skip-index comparison rewrites (`clickhouse.py:536-901`) into
     the lowering (reading the index flags off the stage-1 source).
   - The events-predicate-pushdown's mat-column machinery (`_materialized_column_for_property`,
     `_optimized_json_has_group_column`, `_collect_materialized_column`,
     `_inner_table_type_with_materialized_columns`) becomes redundant once lowering runs before it and there
     are no `PropertyType`s to chase — delete then, and simplify pushdown to a plain "project + repoint".

## Related / context

- Nullable materialized columns (`is_nullable`) already exist as an opt-in. They are **orthogonal** to this
  refactor: the lowering pass *carries* the `nullIf` wrapping (because legacy columns are non-nullable);
  only the *final deletion* of that wrapping + the comparison-undo optimizers is bounded on a legacy-column
  backfill. Do not block the lowering pass on nullable.
- Dialect-gate the lowering to ClickHouse — the same AST is also printed back to HogQL / Postgres / DuckDB.
