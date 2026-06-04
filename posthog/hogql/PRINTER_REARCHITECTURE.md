# HogQL printer & property-lowering rearchitecture

**Status:** WIP design doc / RFC. Intended starting point for an agent that will produce a Graphite stack.
**Author context:** distilled from an investigation on `aspicer/feat/hogql/property-lowering` (see "What we learned", below).
**Supersedes the framing in:** `posthog/hogql/transforms/PROPERTY_LOWERING_PLAN.md` (that plan assumed the printer's property code could be deleted outright; this doc explains why that's false as scoped, and what to do instead).

---

## 0. Mandate (what the agent should produce)

A **Graphite stack** that migrates HogQL property handling to the architecture in §4, and shrinks the ClickHouse printer to mechanical leaf rendering, **with no behavioral regressions across any of the four SQL dialects** (`hogql`, `clickhouse`, `postgres`, `duckdb`).

Each PR in the stack must be independently shippable and gated by an explicit regression net (§9). Deletions of printer code must be gated by the **reachability oracle** (§9.3) — we delete only code we have *proven* unreachable, not code we *believe* is unreachable.

Do **not** attempt the deletion as a single change. The investigation that produced this doc tried that and it is not safe; the whole point of the stack is to make the deletion safe one provable step at a time.

---

## 1. TL;DR of the problem

Today, the decision "what physical SQL does `properties.X` become" is made **at print time, inside the ClickHouse printer**, and is **smeared** across:

- `BasePrinter.visit_property_type` (materialized-column lookup + JSON-extract fallback) — `posthog/hogql/printer/base.py`
- `BasePrinter._get_all_materialized_property_sources` / `_get_materialized_property_source_for_property_type` / `_get_materialized_column` / `_get_dmat_column` / `_yield_property_group_columns`
- `ClickHousePrinter`'s 8 skip-index comparison optimizers (`_get_optimized_*`) + `visit_compare_operation` dispatch — `posthog/hogql/printer/clickhouse.py`
- `ClickHousePrinter.visit_property_type` (struct columns, joined-subquery) + `_maybe_apply_json_drop_keys` (access control)
- `PropertySwapper` (the scalar cast) — `posthog/hogql/transforms/property_types.py`
- and now a partial, ClickHouse-only early pass — `posthog/hogql/transforms/property_lowering.py`

This makes every new requirement a special case bolted onto an overloaded method, and makes the logic **untestable except via SQL-string snapshots** (you can't assert a *decision*, only its rendered side effect). The arrival of the Postgres/DuckDB dialects exposed the deeper flaw: the property→column decision lives in code that is *shared across dialects*, even though much of it (materialized columns, skip indexes, property groups) is **ClickHouse-only**.

---

## 2. How it works today (orientation for the agent)

### 2.1 The print pipeline

`prepare_ast_for_printing` in `posthog/hogql/printer/utils.py` (ClickHouse branch), in order:

1. `resolve_types` — names, scopes, types. Produces `PropertyType` nodes for `properties.X` accesses.
2. `build_property_swapper` — resolves which event/person/group properties are typed/materialized into `context.property_swapper`.
3. First `PropertySwapper` pass — group properties only (must run before lazy tables; groups rely on lazy-table structure).
4. `resolve_lazy_tables` — materializes joins (person joins, etc.) into subqueries. **Sets `PropertyType.joined_subquery`** on outer references it repoints (see `lazy_tables.py`, search `joined_subquery =`).
5. `lower_properties` (the current early pass) — ClickHouse-only; lowers materializable `properties.X` to concrete column AST. **Today gated/partial.**
6. Second `PropertySwapper` pass — event/person scalar casts on the tail the pass didn't lower.
7. Print.

### 2.2 The four printers

`posthog/hogql/printer/{hogql,clickhouse,postgres,duckdb}.py`, all extending `BasePrinter` (`base.py`).

- `HogQLPrinter`, `DuckDBPrinter`: **do not override `visit_property_type`** → they use the base one (materialized lookup + JSON fallback).
- `PostgresPrinter`: overrides `visit_property_type` for struct columns + overrides `_unsafe_json_extract_trim_quotes` for `->`/`->>` syntax, then calls `super()` → base materialized lookup + JSON fallback.
- `ClickHousePrinter`: overrides `visit_property_type` (struct, joined-subquery), `_get_materialized_property_source_for_property_type` (adds the restricted check), `_get_table_name` (uses `to_printed_clickhouse`), and adds the 8 comparison optimizers + property-group helpers.

**Consequence:** the *base* materialized/JSON machinery is the live property→column implementation for `hogql`, `postgres`, and `duckdb`. The lowering pass is ClickHouse-only and emits ClickHouse-specific AST (`JSONExtractRaw`, `nullIf` scrubbing) that the other dialects cannot execute.

### 2.3 `within_non_hogql_query`

Three callers compile a *property predicate fragment* and splice it into a hand-written statement:
`posthog/models/event/query_event_list.py`, `posthog/models/filters/base_filter.py`, `posthog/models/data_deletion_request.py`.
The data-deletion case becomes a **lightweight DELETE mutation**, whose expression analyzer **rejects table-qualified column names** (`sharded_events.mat_$x`). So that path requires **unqualified** materialized columns. This path is high-volume (production query-log analysis put it at ~4.9M queries / 14 days across ~29k teams). See `FieldType.unqualified` (added on the WIP branch) for the mechanism the printer uses to drop the table prefix.

---

## 3. What we learned this session (the evidence — keep this; it's the load-bearing part)

### 3.1 The printer's property machinery is shared across all four dialects → it cannot simply be deleted

The lowering pass is ClickHouse-only. `base.visit_property_type` (materialized lookup + JSON fallback) is the live implementation for `hogql`/`postgres`/`duckdb`. Deleting it breaks three dialects.

### 3.2 Even for ClickHouse, the pass does **not** subsume the printer (proven, not assumed)

We planted an assertion at the printer's property entry points (`ClickHousePrinter._get_materialized_property_source_for_property_type` and `_get_property_group_source_for_field`) and ran the full HogQL suite (`posthog/hogql/printer/test/`, `transforms/test/`, `test/test_query.py`, `test/test_resolver.py`). The assertion **fired for dozens of properties on real `execute_hogql_query` paths** — 117 tests tripped. Properties observed reaching the printer: `tier`, `test_prop`, `campaign_source`, `device_type`, `$exception_fingerprint`, `$os`, `index`, `random_uuid`, `$session_id`, `$$$session_id`, `$some_prop`, `string`, … The categories:

- **is-set / `= NULL`** (e.g. "is not set" filters). **Deliberate** — a non-nullable materialized column stores `''` for *both* empty-string and missing, so it cannot answer "is it set"; the printer falls back to `JSONHas(properties, 'X')` on the raw blob. The pass intentionally leaves these.
- **`$session_id`** — a real-column skip optimization the pass leaves to the printer.
- **Properties inside CTEs** — e.g. `WITH recent AS (SELECT ... WHERE properties.$os = 'iOS') ...`. The pass's visitor did **not descend into the CTE body**, so the property arrived at the printer un-lowered. (This one is a *fixable* coverage gap, not a fundamental bail — but it shows the pass is incomplete and the printer is the universal backstop.)
- **struct columns** (data-warehouse Tuple columns) — `tupleElement(...)`, not JSON.
- **restricted properties**, **column-aliased tables** — handled by the printer's access-control / alias rendering.

**Takeaway:** the printer is the *complete* implementation; the pass is a *partial ClickHouse fast-path*. They are a fast-path + backstop, **not** two copies of one decision. This is why "delete the duplicate" is the wrong mental model.

### 3.3 A real correctness bug found + fixed (keep this fix)

The pass resolved the materialized-column registry key with `table_type.table.to_printed_hogql()` (→ `"raw_persons"` for `RawPersonsTable`), but the registry is keyed by the **ClickHouse** table name (`to_printed_clickhouse(context)` → `"person"`), which is what `ClickHousePrinter._get_table_name` uses. Result: **person properties read via a join silently fell back to JSON** instead of their materialized column, so an empty-string person property returned `''` instead of `None` (broke "is not set").

- Repro: `test_printer.py::TestMaterializedColumnOptimization::test_person_property_is_not_set_behavior_0_materialized_joined` — fails on the branch, passes on `master`.
- Fix: `resolve_materialized_property_source` now uses `to_printed_clickhouse(context)`.
- This is a general footgun (see §8.1).

### 3.4 The lowering already removes real duplication where it *can*

The ported skip-index comparison optimizers in `property_lowering.py` (`LowerProperties.visit_compare_operation` / `visit_call`) faithfully reproduce the printer's 8 `_get_optimized_*` forms as **result-equivalent AST** (not byte-identical — the printer string-builds a `? :` ternary and literal constants that no AST node reproduces). This is the seed of the "physical optimization pass" in the target design. The equivalence bar is **result-equivalence**, except on the `within_non_hogql_query` path where the DELETE-mutation analyzer constrains the *form* (must be unqualified, must use mutation-safe functions).

---

## 4. Target architecture

### 4.1 Two axes, never mixed

The original sin is conflating two independent axes:

- **Schema axis** — *what kind of column is `properties`* (JSON blob vs Struct vs Array). Drives **logical access**. Dialect-independent.
- **Backend axis** — *does this engine have materialized columns / skip indexes / property groups* (ClickHouse: yes; warehouse engines: no). Drives **physical optimization**. Backend-gated.

Keep them on separate seams. "ClickHouse materialization" must never live in code shared with non-ClickHouse dialects.

### 4.2 Guiding principles

1. **The printer renders; it never decides.** A printer is a pure `(physical AST) → string`, dialect-specific *syntax only*. Any schema lookup, materialized-column choice, or optimization inside the printer is a bug. Every physical choice is an AST→AST pass *before* printing.
2. **Schema drives logical access; backend drives physical optimization.** Don't mix. Logical lowering runs for all dialects; physical optimization passes are an explicit, backend-gated list.
3. **Lower early, to ordinary typed nodes.** After logical lowering there are **zero `PropertyType` nodes** — only typed expressions over real columns. That uniform vocabulary is the contract that lets downstream transforms (predicate pushdown, etc.) compose without predicting each other.
4. **Semantics live in the logical form; optimizations only fire when sound.** `properties.X IS NULL` lowers to a truthful key-existence check; the materialized-column optimization *declines* on it. It is never the printer's job to "remember" to fall back. An optimization that can't preserve meaning simply doesn't match.
5. **Resolver = meaning. Passes = decisions. Printer = syntax.**

### 4.3 The pipeline

```
parse
─ resolve types ─────────────── meaning: scopes, names, types, PropertyType      [dialect- & backend-agnostic]
─ resolve lazy tables / joins ─ joins exist before anything reads through them
─ LOGICAL LOWERING ★ ────────── PropertyType → typed JSON/struct/array access      [schema-driven, dialect-agnostic]
                                + is-set as key-existence, + scalar cast,
                                + access-control key-drop (restricted)
                                ⇒ no PropertyType nodes remain
─ optimization passes (composable; each gated by backend capability):
     · predicate pushdown (Robbie)        — operates on plain typed columns
     · materialized-column substitution    — ClickHouse only
     · skip-index comparison rewrites      — ClickHouse only
     · property-group substitution         — ClickHouse only
─ print ─────────────────────── mechanical; per-dialect leaf syntax only
```

★ is the single home for "what does a property access mean physically." It replaces: the printer's `visit_property_type` lookup, the `PropertySwapper` cast, and the partial pass.

### 4.4 The logical-lowering contract

After logical lowering, the AST contains **no `PropertyType`**. A `properties.X` read becomes a **dialect-neutral logical leaf** that each printer renders in its own JSON syntax, plus ordinary typed `Call`s for casts. Two viable representations (decide in PR-time):

- **(A) A new logical node**, e.g. `ast.JSONFieldAccess(source: Expr, keys: list[str|int], value_type: ConstantType)`. Explicit, easy to match in optimization passes, each printer has one `visit_json_field_access`. Cost: a new node type touches the visitors.
- **(B) Keep `PropertyType` as the logical leaf** but strip *all decision logic* from the printer's `visit_property_type` so it only renders the JSON extract for its dialect (no materialized lookup). Materialized substitution becomes a pass that rewrites `PropertyType → Field(mat_col)` *before* printing (ClickHouse only). Smaller diff; risk is that `PropertyType` keeps carrying ambient meaning.

**Recommendation:** (B) for the migration (smaller, strangler-friendly), with a clearly documented invariant: "by print time, a surviving `PropertyType` means *only* 'extract these keys from this JSON/struct source' — no physical choice remains." Re-evaluate (A) once the printer is mechanical.

Logical lowering owns, as **schema/semantic rules** (not backend logic):

- JSON blob (`StringJSONDatabaseField`) → JSON extract with null/quote scrubbing + scalar cast.
- Struct column (`StructDatabaseField`) → chained struct/tuple access (no JSON).
- Array column (`StringArrayDatabaseField`) → array access.
- is-set (`= NULL` / `IS NULL` / `is_not_set`) → key-existence on the blob (`JSONHas`-equivalent), *expressed once*, never as a printer special case.
- deep chains (`a.b.c`).
- access control (restricted keys) → wrap the blob source in a key-drop (`JSONDropKeys`-equivalent). Dialect-agnostic; uses the shared `restricted_property_keys_for_table_type` (already factored on the WIP branch). **Security-critical** (§8.5).

### 4.5 The physical-optimization passes (ClickHouse-gated)

Operate on the logical form. Each is a self-contained, unit-testable AST→AST transform, only added to the ClickHouse backend's pass list:

- **Materialized-column substitution** — rewrite a logical blob-extract of `events.properties.X` to `Field(events.mat_X)` *when the column exists and is semantically sufficient*. Declines on is-set (principle 4). dmat handled here.
- **Skip-index comparison rewrites** — the 8 `_get_optimized_*` forms, already ported as AST in `property_lowering.py`. Move them here.
- **Property-group substitution** — the `Map` column access + `has(...)` forms.
- **`$session_id` / `$ai_*`** — isolated, named rules within these passes (they are real-column / bloom-filter special cases, not generic property reads — keep them explicit, not smeared).

`_get_optimized_session_id_compare_operation` operates on a *real column* (`$session_id`), not a property — it is not part of property lowering and should be evaluated separately for whether it even belongs in this stack.

### 4.6 The resolver ↔ printer line

- **Resolver**: text/AST → typed semantic AST. Scope, names, value types, "this is a property access." **No** physical columns, materialization, or dialect knowledge. Output is backend- and dialect-agnostic.
- **Transform zone** (today anemic; should be the center of gravity): logical lowering + optimization passes. **Every decision lives here.**
- **Printer**: typed physical AST → string. No lookups, no schema, no decisions. A `visit_json_field_access` that knows the dialect's extract syntax; a `visit_field` that quotes an identifier. That's the whole property surface.

The line is blurry **today** because the printer reaches back across it and does resolver-grade work (schema lookups) at render time. The migration moves that work left, into the transform zone.

### 4.7 When dialects diverge — exactly two points, two *kinds*

1. **Capability divergence → which passes run.** ClickHouse gets mat-column / skip-index / property-group passes; warehouse backends don't. Expressed as an explicit **per-backend pass list**, never as `if dialect == ...` inside shared functions.
2. **Syntax divergence → how leaves render.** JSON-extract operator (`JSONExtractRaw(x,'k')` vs `x ->> 'k'`), identifier quoting, function spellings. A handful of per-dialect leaf renderers.

Everything else — resolution, types, logical access, pushdown, access control — is shared and identical. **If you write `if dialect == ...` anywhere except a pass list or a leaf renderer, the principle is being violated.**

### 4.8 Why this makes Robbie's optimization (and future transforms) easy

After logical lowering, a property read **is an ordinary typed column expression**. Predicate pushdown becomes a *generic* "project this column into the subquery, repoint outer references" pass — it doesn't know the column came from a property. Today the pushdown carries ~150 lines re-predicting what the printer will choose, because the property decision hasn't happened yet at transform time. Move lowering before the optimization zone and that prediction code evaporates. Any new transform (alternative index strategy, rewrite, cache key) inherits the same clean input.

---

## 5. Mapping every current special case

| Today (mostly printer) | Target |
|---|---|
| materialized-column lookup (`_get_all_materialized_property_sources`) | physical pass, ClickHouse-gated |
| 8 skip-index comparison rewrites (`_get_optimized_*`) | physical pass, ClickHouse-gated (AST already ported) |
| property groups, dmat, nullable/non-nullable mat | internals of the physical pass |
| `$session_id`, `$ai_*` | named rules inside the physical pass; isolated, explicit |
| is-set / `= NULL` | **logical** rule (key-existence on blob); mat pass declines |
| restricted properties (`_maybe_apply_json_drop_keys`) | **logical** access-control pass (key-drop on blob); dialect-agnostic |
| struct / array columns | **logical** branch keyed on column type |
| column-aliased tables | falls out — lowering keys on the *resolved* column, not the alias |
| joined-subquery read | not a property — a plain column read of the subquery alias |

Nothing lands in the printer.

---

## 6. The starting point: this branch — keep vs scaffolding

The WIP branch carries the investigation's code. Treat it as follows:

**Keep (correct, independently valuable):**
- The `to_printed_clickhouse` fix in `resolve_materialized_property_source` (§3.3). This is a real bug fix; consider landing it on its own early in the stack (or even before, straight to master).
- `posthog/hogql/restricted_properties.py` — `restricted_property_keys_for_table_type`, the shared restriction check (single source of truth between printer and pass). This is exactly the §4.4 access-control primitive.
- `FieldType.unqualified` + the printer honoring it — the mechanism for the `within_non_hogql_query` unqualified-column requirement (§2.3). The target design needs this regardless.
- `Constant.inline` — inline sentinel rendering (`''`/`'null'`/trim regex) so lowered SQL matches the printer's hand-built constants where it matters.

**Scaffolding / reference (reshape, don't preserve as-is):**
- `posthog/hogql/transforms/property_lowering.py` — the partial pass. It is the **seed of logical lowering + the ClickHouse physical pass, fused together**. The migration *splits* it: schema-driven logical lowering (all dialects) vs ClickHouse physical optimization (gated). The ported `_get_optimized_*` AST is good raw material for the physical pass.
- The non-`within_non_hogql_query` un-gating, the restricted force-blob routing, and the column-aliased gate removal: exploratory; they make the pass cover *more* but were in service of the now-abandoned single-step deletion. Re-derive them as proper logical rules with the regression net in place.

**Recommendation on "use this branch or not":** **start the WIP branch from this branch's state** (so the bug fix, shared helpers, `unqualified`, and the ported-optimizer reference are all present), but the **first PR of the Graphite stack is characterization (§7.1), not more feature code.** The agent should build the new structure alongside, prove equivalence, then delete — using the existing pass as reference material, not as a foundation to extend blindly.

---

## 7. Migration plan — the Graphite stack

Strangler-fig: introduce the new structure in parallel, prove equivalence against a golden corpus + reachability oracle, flip, then delete. Bottom of the stack merges first. Each PR states its **regression gate**.

> **PR 0 — Characterization harness + reachability oracle (no behavior change).**
> - A structural+golden test harness that compiles a **broad corpus** (see §9.1) across **all four dialects** and captures exact SQL output as golden files *owned by the harness* (not the CI-managed `.ambr`; see §8.9).
> - Land the **reachability oracle** (§9.3) as a reusable test utility (the DEADCHECK instrumentation, switchable on).
> - **Gate:** harness green; oracle runs across the whole existing suite and the corpus and reports the current set of printer-reached properties as the baseline.

> **PR 1 — Person-property table-name fix (correctness; can land first / independently).**
> - The `to_printed_clickhouse` fix. **Gate:** `test_person_property_is_not_set_behavior_*` green; golden delta is exactly the person-joined queries now using the mat column.

> **PR 2 — One decision function shared by printer and pass (dedup, no behavior change).**
> - Factor the materialized-source decision so `ClickHousePrinter` and the pass call **one** function (`resolve_materialized_property_source`); printer's `_get_all_materialized_property_sources` delegates to it. Confirm the restricted-keys helper is the single shared one. **Gate:** golden unchanged.

> **PR 3 — Logical lowering: is-set as a schema rule.**
> - Lower `= NULL` / `IS NULL` / `is_not_set` to a key-existence form in the pass (so it no longer reaches the printer for ClickHouse), expressed dialect-neutrally. **Gate:** golden unchanged; oracle no longer reports is-set properties for ClickHouse.

> **PR 4 — Logical lowering: visitor coverage (CTEs, and any other un-traversed positions).**
> - Make the lowering visitor descend into **every** position: CTE bodies, subqueries, lambdas, window exprs, array/higher-order functions, join constraints, `ORDER/GROUP/HAVING`. Use the oracle to enumerate remaining reached positions and close them. **Gate:** oracle clean for these positions; golden unchanged.

> **PR 5 — Logical lowering: struct / array columns + restricted.**
> - Move struct/array access and the access-control key-drop into the logical pass as schema rules (using `restricted_property_keys_for_table_type`). **Gate:** `test_property_access_control` green; struct/warehouse golden unchanged; oracle clean for these.

> **PR 6 — ClickHouse reachability = 0.**
> - With PRs 3–5 in, the oracle should show **no `PropertyType` reaching the ClickHouse printer's decision logic** (except deliberate, documented exceptions — re-evaluate `$session_id`). Close any stragglers. **Gate:** oracle clean for ClickHouse across the *entire* test suite (not just the corpus).

> **PR 7 — Extract ClickHouse physical optimizations into explicit gated passes.**
> - Pull the materialized-column substitution, skip-index rewrites, and property-group substitution out of the printer and into named passes added only to the ClickHouse backend's pass list (seeded from the ported AST in `property_lowering.py`). Printer's `visit_compare_operation` loses the optimizer dispatch (keep `session_id` pending its own decision). **Gate:** golden unchanged (result-equivalent; expect SQL-text churn — verify via execution + skip-index assertions, see §8.7); oracle clean.

> **PR 8 — Bring the other dialects onto logical lowering.**
> - Run logical lowering for `hogql`/`postgres`/`duckdb`, emitting the dialect-neutral logical leaf; give each printer a leaf renderer (`postgres` already has `->`/`->>`). Now the printer's decision machinery is unreachable for **all** dialects. **Gate:** oracle clean across all dialects; postgres/duckdb/hogql golden unchanged.

> **PR 9 — Starve the printer (the deletion).**
> - Delete `base._get_all_materialized_property_sources`, `_get_materialized_property_source_for_property_type`, `_get_materialized_column`, `_get_dmat_column`, `_yield_property_group_columns`, the `Printable*` classes, the `ClickHousePrinter._get_optimized_*` methods + dispatch, and reduce `visit_property_type` to leaf rendering. **Gate:** the reachability oracle guarantees safety; full suite green; mypy/ruff clean.

> **PR 10 — Pushdown payoff + cleanup.**
> - Simplify Robbie's predicate pushdown to the uniform column vocabulary; delete the materialized-column prediction code (`_materialized_column_for_property`, `_inner_table_type_with_materialized_columns`, etc.). **Gate:** pushdown tests green; golden unchanged.

PRs 3–5 and 7–8 may each split further if a single PR gets too large. The ordering invariant: **never delete printer property code (PR 9) until the oracle proves it unreachable for every dialect (PRs 6 + 8).**

---

## 8. Footguns (each cost real time — read before touching the relevant area)

### 8.1 Materialized-column registry is keyed by the *ClickHouse* table name
`get_materialized_column_for_property(table, column, prop)` expects the **ClickHouse** table name (`to_printed_clickhouse(context)`), not the HogQL name (`to_printed_hogql()`). `RawPersonsTable`: `raw_persons` (hogql) vs `person` (clickhouse). `EventsTable`: `events` in both (which is why event properties "worked" and masked the bug). The printer's `ClickHousePrinter._get_table_name` already uses `to_printed_clickhouse`; any new resolution code must too. (This was §3.3.)

### 8.2 is-set semantics: a non-nullable mat column cannot answer "is it set"
It stores `''` for both empty-string and missing. The materialized-column optimization must **decline** on is-set; the logical form must be a key-existence check on the blob. Getting this wrong returns `''` where `None` is correct (silent data error, only caught by execution tests, not snapshots).

### 8.3 The reachability oracle must run across the *entire* suite, not just the corpus
The CTE gap (§3.2) was only found because the oracle ran over `test_query.py`, not a hand-picked corpus. A position absent from the corpus can still ship a regression. Run the oracle over everything before any deletion.

### 8.4 `within_non_hogql_query` requires *unqualified* columns
Lightweight DELETE mutations reject table-qualified names; the fragment callers splice into a fixed table scope. Use `FieldType.unqualified`. Also: the lowered forms on this path must be **mutation-analyzer-safe** (standard scalar functions only) — this is the one path where the constraint is on the *form*, not just the result. No automated test executes the DELETE mutation today; add one, or at minimum assert unqualified + mutation-safe-function output. ~4.9M queries/14d — do not break it.

### 8.5 Restricted properties are a security boundary
Under-detecting a restricted property → its value is read from the materialized column → **PII leak**. Over-detecting (routing a non-restricted property to the JSON-drop blob path) is *safe* (only costs a mat-column optimization). Always use the shared `restricted_property_keys_for_table_type`; never reimplement the table→property-type mapping. The blob source must be `JSONDropKeys`-wrapped so the extracted value collapses to `''`.

### 8.6 `CloningVisitor(clear_types=...)`
The lowering visitor must `super().__init__(clear_types=False)`. The default `True` strips every node's resolved type and printing then fails with "FROM clause ... before type resolution". When introducing a logical node, ensure `CloningVisitor`/`TraversingVisitor` handle it and preserve types/flags (see §8.8).

### 8.7 Equivalence bar is result-equivalence, not byte-identical
The printer string-builds a `? :` ternary and literal (non-parameterized) constants that no AST node reproduces; the lowered AST prints differently but evaluates identically. **Do not** chase byte-identical snapshots, and **do not** add new printer primitives just to match strings. Verify via execution + skip-index `EXPLAIN` assertions (see `TestMaterializedColumnOptimization`, which asserts both results and index usage). Exception: the `within_non_hogql_query` form constraint (§8.4).

### 8.8 New AST nodes/fields must be wired into the visitors
`posthog/hogql/visitor.py` `CloningVisitor`/`TraversingVisitor` reconstruct nodes field-by-field. A new logical node or a new field (like `FieldType.unqualified`, `Constant.inline`) must be carried through cloning (`type=None if clear_types else node.type`, and explicit field passthrough). See the note at the top of `ast.py`.

### 8.9 Snapshots are CI-owned; build a *separate* golden corpus
Do **not** commit regenerated `.ambr` files — CI regenerates and owns them. The migration's regression net (PR 0) must be a **separate**, harness-owned golden artifact so the agent controls it deterministically and isn't fighting the CI snapshot job. Cosmetic SQL-text churn in `.ambr` from result-equivalent forms is expected and is *not* a regression signal — the golden corpus + execution assertions are.

### 8.10 Pass order vs the two `PropertySwapper` passes
Lowering runs between the group swapper and the event/person cast swapper. As logical lowering absorbs the scalar cast, ensure the second swapper no-ops on lowered nodes (they're no longer `PropertyType`) — otherwise double-cast or missing-cast. The cast the pass applies mirrors `PropertySwapper._field_type_to_property_call`.

### 8.11 `joined_subquery` outer references are not property reads
`lazy_tables.py` repoints outer person/group property refs into a subquery alias and sets `PropertyType.joined_subquery`. The pass must **not** lower those (they print as `alias.field`); the *inner* property inside the subquery is the real read and is lowered normally (the pass runs after lazy tables, over the whole tree). Don't "fix" the outer ref.

### 8.12 Don't let a ClickHouse pass touch other dialects
Anything emitting `JSONExtractRaw`, `nullIf`-scrubbing, `mat_*`, `Map`-access, or skip-index forms is ClickHouse-only. It must live in a backend-gated pass, never in shared logical lowering or the base printer. Postgres/DuckDB will choke on ClickHouse functions.

---

## 9. Testing strategy

### 9.1 Characterization corpus (PR 0)
Representative queries × 4 dialects, covering at minimum: simple value read; deep chain (`a.b.c`); is-set / `= NULL` / `is_not_set`; `=` / `!=` / `IN` / `NOT IN` / `<` `>` range / `ILIKE` / `LIKE`; `$session_id`; `$ai_trace_id`/`$ai_session_id`/`$ai_is_error`; restricted properties (event + person); struct/warehouse columns; column-aliased tables (`FROM events AS e(...)`); property groups (`ENABLED` + `OPTIMIZED`); dmat; nullable vs non-nullable mat (`AUTO` / `LEGACY_NULL_AS_STRING`); person properties in **both** PoE-on-events and PoE-joined modes; CTEs; nested subqueries; joined subqueries; `within_non_hogql_query` (data deletion + base_filter + query_event_list). Capture exact SQL as golden.

### 9.2 Structural (decision) tests
The payoff of the rearchitecture: assert on AST structure, not SQL strings. e.g. "`PropertyType(events.properties.X)` lowers to a JSON-access of type `String`"; "the mat-substitution pass rewrites a JSON-access of `events.properties.X` to `Field(mat_X)` with null-scrubbing"; "the mat pass leaves an is-set comparison untouched"; "no `PropertyType` survives logical lowering." These are fast, deterministic, and don't depend on a live ClickHouse.

### 9.3 Reachability oracle
A switchable instrumentation that makes the printer's property-decision entry points **raise** (or record) when reached. Run it across the **entire** test suite per dialect. It is the gate for every deletion: code is deleted only when the oracle proves it unreachable. Implementation reference: this session asserted in `ClickHousePrinter._get_materialized_property_source_for_property_type` and `_get_property_group_source_for_field`; note that `_get_materialized_string_property_source` (comparison optimizers) routes through `_get_materialized_property_source_for_property_type`, so that one chokepoint covers value reads + comparison optimizers; the property-group/JSONHas path needs its own.

### 9.4 Execution + index assertions
For ClickHouse physical optimizations, assert **results** and **skip-index usage** (`EXPLAIN`), not SQL text — see `TestMaterializedColumnOptimization::test_materialized_column_optimization_returns_correct_results` (asserts rows + `get_index_from_explain`). This catches both correctness and the performance regressions that motivated the optimizers.

---

## 10. Code inventory (where things live)

- Pipeline: `posthog/hogql/printer/utils.py` (`prepare_ast_for_printing`).
- Printers: `posthog/hogql/printer/{base,clickhouse,postgres,duckdb,hogql}.py`.
  - Property decision (to move out): `base.visit_property_type`, `base._get_all_materialized_property_sources`, `_get_materialized_property_source_for_property_type`, `_get_materialized_column`, `_get_dmat_column`, `_yield_property_group_columns`, `printer/types.py::Printable*`.
  - ClickHouse-specific (to extract into passes): `clickhouse._get_optimized_*` (8), `_get_materialized_string_property_source`, `_get_property_group_source_for_field`, the `visit_compare_operation` dispatch, `visit_property_type` (struct/joined), `_maybe_apply_json_drop_keys`, `_get_restricted_keys_for_table_type` (now delegating to the shared helper).
- The pass (seed of logical lowering + CH physical pass): `posthog/hogql/transforms/property_lowering.py`.
- The cast: `posthog/hogql/transforms/property_types.py` (`PropertySwapper`, `_field_type_to_property_call`).
- Shared access-control primitive: `posthog/hogql/restricted_properties.py`.
- Lazy joins / `joined_subquery`: `posthog/hogql/transforms/lazy_tables.py`.
- `within_non_hogql_query` callers: `posthog/models/event/query_event_list.py`, `posthog/models/filters/base_filter.py`, `posthog/models/data_deletion_request.py`.
- AST + visitors: `posthog/hogql/ast.py`, `posthog/hogql/visitor.py`.
- Materialized-column registry: `posthog/clickhouse/materialized_columns.py`, `posthog/clickhouse/property_groups.py`.

---

## 11. Open decisions for the agent

1. **Logical node (A) vs `PropertyType`-as-logical (B)** — §4.4. Recommendation (B) to start.
2. **Does `$session_id` belong in this stack?** It optimizes a real column, not a property. Possibly leave entirely in the printer or move in a separate, clearly-scoped change.
3. **Land the `to_printed_clickhouse` fix to master independently** of the stack? It's a real bug with a failing test; landing early de-risks and helps users now.
4. **How far to push the other-dialect lowering (PR 8)** — full parity, or just enough to make the printer's decision logic unreachable? Parity is cleaner but larger.
5. **Robbie's pushdown timing** — coordinate so PR 10 lands against the predicate-pushdown work rather than racing it.
