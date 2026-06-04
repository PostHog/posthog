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

2. **Lower-to-AST — NEXT.**
   `lower_property_type(pt, context) -> ast.Expr`, built from the stage-1 source:
   - `materialized_column` (non-nullable, non-`$ai_*`): `nullIf(nullIf(Field(col),''),'null')`
     (single `nullIf` under `LEGACY_NULL_AS_STRING`); nullable / `$ai_*` / `dmat`: bare `Field(col)`.
   - `property_group`: `if(has(Field(g), key), ArrayAccess(Field(g), key), null)`.
   - `None`: `JSONExtract`-trim-quotes over the raw `properties` Field (mirror `_unsafe_json_extract_trim_quotes`).
   - deep chain (`a.b`): wrap the head result in the JSONExtract form for `chain[1:]`.
   Verify by **execution result-equivalence** (lowered vs. un-lowered query return identical rows) across
   every materialization mode, using the `materialized()` / property-group / dmat test fixtures.

3. **Re-home optimizations + integrate — AFTER 2.**
   - Move `_get_optimized_property_group_call` and the skip-index comparison rewrites (`clickhouse.py:536-901`)
     into the lowering (they emit the optimized concrete form directly), reading the index flags off the
     stage-1 source.
   - Slot the pass into `prepare_ast_for_printing`. **Hard part — ordering:** the second `swap_properties`
     (event/person type *coercion*: `toFloat`/`toDateTime`) runs *after* pushdown (`printer/utils.py:160`),
     but lowering must run *before* pushdown. Either move coercion ahead of lowering, or teach coercion to
     wrap the lowered expression.
   - Delete the printer's property lowering (`visit_property_type` shrinks to the joined-subquery case),
     delete the pushdown machinery (`_materialized_column_for_property`, `_optimized_json_has_group_column`,
     `_collect_materialized_column`, `_inner_table_type_with_materialized_columns`), and re-apply the
     pushdown "project columns + repoint" rewrite — now trivial because there are no `PropertyType`s left.

## Related / context

- Nullable materialized columns (`is_nullable`) already exist as an opt-in. They are **orthogonal** to this
  refactor: the lowering pass *carries* the `nullIf` wrapping (because legacy columns are non-nullable);
  only the *final deletion* of that wrapping + the comparison-undo optimizers is bounded on a legacy-column
  backfill. Do not block the lowering pass on nullable.
- Dialect-gate the lowering to ClickHouse — the same AST is also printed back to HogQL / Postgres / DuckDB.
