# HogQL Type System Reviewers Guide

This guide is for reviewers of the HogQL type-system PR on branch `the-real-type-system`.
It explains what changed, why the changes are in scope, what the branch enables, and where review attention is most valuable.

Read this alongside:

- `docs/internal/hogql-type-system-now-possible.md`
- `docs/internal/hogql-type-system-todo.md`

## Review Goal

The main thing to verify is that this PR improves HogQL type metadata and selected optimizer inputs without making HogQL a strict validator by default.

Existing queries should keep compiling.
Unknown or partially typed expressions should remain printable.
Behavior-changing rewrites should be narrow, tested, and either behind an explicit opt-in flag or guarded by property/materialized-column facts.

## Why This Is In Scope

The PR is intentionally centered on HogQL expression typing and the optimizations that directly depend on that typing.
The relevant product problem is that HogQL frequently loses type facts at function, property, cast, array, tuple, map, aggregate, and materialized-column boundaries.
Once an expression becomes `UnknownType`, printers add defensive wrappers or optimizers skip otherwise valid rewrites.

The changes are in scope because they all support one of these outcomes:

- Preserve more accurate expression types through the resolver.
- Make optimizer blockers measurable instead of implicit.
- Allow safe SQL simplifications only when type facts prove they are redundant.
- Allow materialized-property range comparisons to use minmax indexes when the physical column type actually matches the semantic property type.
- Keep compatibility by treating unknowns as barriers, not errors.

## What Changed

### Structured Runtime Type Model

`posthog/hogql/type_system.py` adds a structured `RuntimeType` model and conversion helpers between runtime types, existing `ast.ConstantType` objects, database fields, and SQL type strings.

It can represent integer signedness and width, float width, decimal precision and scale, nullable wrappers, low-cardinality wrappers, strings, fixed strings, UUIDs, booleans, dates, datetimes with precision/timezone, intervals, arrays, tuples with optional field names, maps, JSON, enums, and aggregate states.

The existing resolver-facing `ConstantType` API remains the compatibility layer.
This PR extends that layer with `MapType`, `AggregateStateType`, tuple field names, and typed lambda arguments, but it does not replace the old type objects everywhere.

Important adjacent changes:

- `FloatArrayDatabaseField.get_constant_type()` now returns `ArrayType(FloatType)` instead of `FloatType`.
- `StructDatabaseField` now preserves tuple field names.
- `SelectSetQueryType` can carry unified output-column types for set queries.

### Type Algebra And Function Inference

The new type-system module adds least-common-supertype and comparison-compatibility APIs.
These are used to unify array/set-query/conditional outputs and to decide whether a comparison is definitely compatible, a cheap cast, an expensive cast, incompatible, or unknown.

The resolver now asks `infer_function_return_type(...)` before falling back to legacy function signatures.
This adds generic inference for common function families that the old signature table could not express, including:

- comparisons, boolean logic, conditionals, and nullability helpers
- casts, conversions, `accurateCast`, `accurateCastOrNull`, and `reinterpretAs*`
- string, URL, date/time, JSON, bitmap, vector, tuple, map, array, and aggregate helpers
- common aggregate states and merge functions
- common window functions

The legacy function signature catalog still works.
If neither generic inference nor legacy signatures provide a useful result, the expression remains `UnknownType`.

### Resolver Coverage

`posthog/hogql/resolver.py` now assigns better output types to:

- `TypeCast` and `TryCast`
- array literals, array access, and array slices
- tuple literals and tuple access, including named tuple access when metadata exists
- map literals, map access, map transforms, and key/value helpers
- higher-order array and map lambda arguments
- lambda-first array helpers such as `arraySort`, `arrayFill`, `arraySplit`, and `arrayFold`
- set-query output columns
- window functions

Reviewers should check that these assignments preserve existing permissive behavior.
The important failure mode is not "a function remains unknown"; that is allowed.
The important failure mode is a confidently wrong type that causes the printer or optimizer to remove a wrapper or choose a physical comparison incorrectly.

### Type Diagnostics

`posthog/hogql/type_diagnostics.py` adds tools to resolve a query and report:

- unknown type occurrences
- optimizer blockers grouped by source/detail
- top-level select-expression inferred types
- a companion `toTypeName(...)` query for comparing inferred types with ClickHouse result metadata
- a function-catalog inventory that separates missing legacy signatures from missing generic inference

This is diagnostic infrastructure, not a user-facing strict mode.
It is useful for future corpus checks and for reviewers who want to inspect a specific query's type flow.

### Opt-In Type-Aware Simplification

`posthog/hogql/transforms/type_aware_simplification.py` adds an internal simplifier for conservative rewrites.
It is disabled by default and only runs when `HogQLContext.enable_type_aware_cast_simplification` is true.

It can remove redundant casts and nullability wrappers, fold safe constant conversions, fold finite numeric literal arithmetic, simplify literal `NULL` fallbacks in `ifNull(...)`/`coalesce(...)`, fold exact-present literal JSON path reads, and fold day/week interval arithmetic for literal dates.

Reviewers should verify that unsafe cases remain unchanged:

- divide-by-zero and non-finite arithmetic
- month/year calendar arithmetic
- casts that change numeric family, DateTime precision, timezone, or nullability in a meaningful way
- non-literal JSON paths
- expressions with unknown or nullable input where the wrapper is still semantically relevant

### Property Comparison Planning

`posthog/hogql/property_planner.py` centralizes property access and comparison planning.
It combines:

- semantic property type from property-definition metadata
- physical source kind: JSON, materialized column, dynamic materialized column, or property group
- physical materialized-column type from ClickHouse metadata
- index availability
- restricted-property rules
- comparison compatibility between semantic type, physical source type, and compared value type

The planner is now used by materialized-property range optimizations and property debug notices.
This is the main guardrail for typed materialized-property work.

The planner should block minmax use when:

- no minmax index exists
- the materialized source type does not match the semantic property type
- the compared value cannot be safely compared to the physical source
- the property is restricted and must fall back to JSON

It should allow minmax use when:

- a string-backed materialized property is compared as a string
- a typed numeric materialized property is physically numeric and compared to a compatible numeric value
- a typed datetime materialized property is physically DateTime-like and a string literal can be moved to the value side as `toDateTime64(...)`

### Materialized Columns And Printer Rewrites

Materialized-column introspection now carries the ClickHouse physical column type from `system.columns`.
The cache key changed from `materialized_columns:v2` to `materialized_columns:v3` so cached entries include the new type data.

`materialize(..., column_type=...)` can create typed physical columns for tests and future rollout work, while default materialization remains string-backed.

The ClickHouse printer now uses the property planner for materialized range comparisons.
It keeps the existing string sentinel handling for string-backed columns and only emits bare typed physical comparisons when the planner says the physical column is semantically safe.

`PropertySwapper` also got stricter JSONExtract rewrites:

- `JSONExtractString(properties, 'key')` can still rewrite to a matching materialized column.
- `JSONExtract(properties, 'key', 'Type')` rewrites only when the requested type exactly matches the physical materialized-column type.
- Other JSON helper families such as `JSONExtractInt(...)` are intentionally not rewritten through a typed materialized column because missing-key and type-mismatch semantics differ.

### SQL Output Changes

Some emitted ClickHouse SQL no longer has defensive `ifNull(...)` wrappers when the resolver now knows an expression is non-nullable.
Examples include typed string/URL functions and selected person-join aggregate/tuple expressions.

These changes are expected when the inferred type is precise.
They need careful review because nullability mistakes are the easiest way for type metadata to become behavior-changing.

### Snapshot Audit Findings

A snapshot audit against the PR merge base `24b9e6892057c7a74a663f7d874ec2be20476d09` and head `7ef2aa4a8fc` found the expected type-system churn:

- Many `ifNull(..., 0)` wrappers disappear from `HAVING`, aggregate comparisons, person/override joins, and error-tracking queries where operands are now inferred as non-nullable.
- Resolver snapshots move many expressions from `UnknownType` to concrete string, boolean, UUID, array, tuple, map, DateTime, and aggregate-state types.
- Typed materialized-property snapshots now show physical column comparisons guarded by `IS NOT NULL` when the source column type matches the semantic property type.
- String-backed and restricted properties continue to use conversion or JSON paths rather than direct numeric or datetime materialized-column comparisons.
- Typed `JSONExtract(properties, 'key', 'Type')` materialized-column rewrites only appear when the requested type exactly matches the physical column type.

The broad non-revenue snapshot pattern is sane: it mostly reflects better type facts rather than changed query shape.
For example, excluding revenue snapshots, the audit saw thousands of removed `ifNull(` wrappers and far fewer added wrappers, while comparison operators stayed roughly balanced.

There is one branch-hygiene issue that is not safe to treat as type-system churn.
Several revenue analytics `.ambr` files lost many live snapshot entries while the corresponding Python tests still exist.
Those files should be regenerated from the full revenue analytics test classes before merge.

Current revenue snapshot count drops to recheck:

- `products/revenue_analytics/backend/hogql_queries/test/__snapshots__/test_revenue_analytics_gross_revenue_query_runner.ambr`: 16 entries to 2 entries.
- `products/revenue_analytics/backend/hogql_queries/test/__snapshots__/test_revenue_analytics_metrics_query_runner.ambr`: 15 entries to 1 entry.
- `products/revenue_analytics/backend/hogql_queries/test/__snapshots__/test_revenue_analytics_overview_query_runner.ambr`: 12 entries to 1 entry.
- `products/revenue_analytics/backend/hogql_queries/test/__snapshots__/test_revenue_analytics_top_customers_query_runner.ambr`: 10 entries to 1 entry.
- `products/revenue_analytics/backend/views/test/__snapshots__/test_mrr_views.ambr`: 4 entries to 3 entries, with a live E2E test no longer represented.

### Tests And Docs

The branch adds `posthog/hogql/test/test_type_system.py` and expands coverage in:

- `posthog/hogql/transforms/test/test_property_types.py`
- `posthog/hogql/printer/test/test_printer.py`
- `posthog/hogql/test/test_property_skip_indexes.py`
- `ee/clickhouse/materialized_columns/test/test_columns.py`

It also updates snapshots for resolver, printer, query, property type, and skip-index behavior.
Snapshot churn is expected, but reviewers should treat every removed `ifNull(...)`, changed cast, or direct materialized-column comparison as a semantic claim that needs supporting test coverage.

## What We Can Do After This PR

This branch makes these follow-up tasks practical:

- Build query-corpus diagnostics for unknown type boundaries and optimizer blockers.
- Compare inferred select-expression types against ClickHouse `toTypeName(...)` results.
- Expand typed function inference incrementally without changing the resolver's public API.
- Introduce typed materialized-property rollout policy later, because the printer can already reason about physical source types.
- Use typed numeric and datetime materialized columns for minmax-friendly range comparisons when the column storage policy allows them.
- Enable the type-aware simplifier for selected internal query paths after broader compatibility checks.

It does not yet enable strict HogQL typing by default.
It does not roll out typed materialized columns broadly.
It does not claim full ClickHouse function parity.

## Review Strategy

Start with the tests and docs, then review from the compatibility boundary inward.

1. Read `posthog/hogql/test/test_type_system.py` to understand the intended type behavior.
2. Read `posthog/hogql/property_planner.py` and the property-planner tests before reviewing printer range rewrites.
3. Review `posthog/hogql/type_system.py` for algebra, parser, and generic inference correctness.
4. Review `posthog/hogql/resolver.py` for where inferred types are attached to AST nodes.
5. Review `posthog/hogql/printer/clickhouse.py` for behavior-changing SQL output.
6. Review materialized-column type introspection and cache-version changes in `ee/clickhouse/materialized_columns/columns.py`.
7. Review snapshot changes last, checking that every SQL change follows from a type fact introduced in code and covered by a focused test.
8. Re-run or regenerate the revenue analytics snapshots from the full test classes before accepting the current revenue `.ambr` deletions.

## High-Risk Review Areas

### Nullability

Check any path that removes `ifNull(...)`, `assumeNotNull(...)`, or `toNullable(...)`.
The resolver often treats literal and function results as non-nullable, but property and materialized-column paths are frequently nullable.

Wrong nullability can change filtering semantics, especially in `WHERE`, `HAVING`, joins, and `NOT` comparisons.

### Query-Level Settings Coupling

Some type-driven decisions are only correct under the ClickHouse settings PostHog pins for every HogQL query via `HogQLGlobalSettings` (`posthog/hogql/constants.py`), most notably `transform_null_in=1`.
The nullable-comparison rewrites, the planner's IN/has handling, and the skip-index expectations all assume those defaults, and the skip-index tests deliberately run `EXPLAIN` under the same settings.
Today this coupling is consistent because the settings are applied unconditionally; if a setting like `transform_null_in` ever becomes configurable per-query, the rewrites that assume it must be re-audited.

### DateTime And Timezones

Review DateTime parsing, DateTime64 precision, timezone display, and typed property range comparisons.
The datetime materialized-column range rewrite converts string literals to `toDateTime64(..., 6, timezone)`.
That is only safe for literal comparisons where the physical source is DateTime-like and the planner has approved the comparison.

### Materialized Property Semantics

Check that numeric and datetime property comparisons do not use bare string materialized columns.
A string-backed numeric property must still go through numeric conversion, because lexicographic ordering is different from numeric ordering.

Check restricted properties too.
Restricted properties should not route through materialized sources.

### JSONExtract Rewrites

Typed `JSONExtract(...)` rewrites should require semantic type equality between the requested type literal and the physical materialized-column type: spelling differences (whitespace, quoting, `LowCardinality` wrapping) are normalized away, but nullability, width, precision, and timezone differences still block the rewrite.
Do not relax this to "lossless" widenings such as `String` vs `Nullable(String)` — JSON helper missing-key and out-of-range semantics differ from bare column reads, so those rewrites change results.
Do not generalize this to helper families without proving missing-key and bad-type semantics match.

### Higher-Order Lambdas

The resolver now binds common lambda argument types for array and map helpers.
It does not implement strict arity validation for every ClickHouse variant.
Unknowns should remain possible when the surrounding array/map type is unknown or the helper shape is unsupported.

### Function Catalog Inference

Adding generic inference is safer than changing every catalog entry, but it still centralizes a lot of assumptions.
Review function families for incorrect nullability, wrong aggregate return families, and over-broad prefix matching.

Missing inference is acceptable.
Wrong inference is not.

### Cross-Dialect Behavior

The runtime type parser has ClickHouse, Postgres, and DuckDB adapters, but ClickHouse is the main optimization target.
Review cast and try-cast behavior carefully for Postgres-family targets.
ClickHouse-only printer behavior should not leak into Postgres or DuckDB printing.

### Opt-In Simplification

The simplifier is intentionally behind `HogQLContext.enable_type_aware_cast_simplification`.
Reviewers should reject changes that make those rewrites run globally without a separate rollout decision and stronger corpus coverage.

### Revenue Snapshot Coverage

The current revenue analytics snapshot deletions look like a partial snapshot update rather than a semantic change.
Do not use those deletions as evidence that the type-system changes are safe.
They should be restored or regenerated by running the full revenue analytics snapshot-bearing tests and reviewing the resulting SQL changes separately.

## Suggested Test Commands

Run the focused type-system tests:

```bash
hogli test posthog/hogql/test/test_type_system.py
```

Run property planning and JSONExtract rewrite coverage:

```bash
hogli test posthog/hogql/transforms/test/test_property_types.py
```

Run printer coverage for nullability and materialized-column SQL:

```bash
hogli test posthog/hogql/printer/test/test_printer.py
```

Run ClickHouse skip-index integration tests when ClickHouse is available:

```bash
hogli test posthog/hogql/test/test_property_skip_indexes.py
```

Run materialized-column DDL/type coverage:

```bash
hogli test ee/clickhouse/materialized_columns/test/test_columns.py
```

Regenerate or verify the revenue analytics snapshots before merge:

```bash
hogli test products/revenue_analytics/backend/hogql_queries/test/test_revenue_analytics_gross_revenue_query_runner.py
hogli test products/revenue_analytics/backend/hogql_queries/test/test_revenue_analytics_metrics_query_runner.py
hogli test products/revenue_analytics/backend/hogql_queries/test/test_revenue_analytics_overview_query_runner.py
hogli test products/revenue_analytics/backend/hogql_queries/test/test_revenue_analytics_top_customers_query_runner.py
hogli test products/revenue_analytics/backend/views/test/test_mrr_views.py
```

For a narrower pass, prioritize:

```bash
hogli test posthog/hogql/test/test_type_system.py::TestHogQLTypeSystem::test_type_aware_simplification_is_opt_in
hogli test posthog/hogql/test/test_type_system.py::TestHogQLTypeSystem::test_type_aware_simplification_keeps_unsafe_casts
hogli test posthog/hogql/transforms/test/test_property_types.py::TestPropertyTypes::test_property_comparison_planner_blocks_numeric_minmax_until_source_type_matches
hogli test posthog/hogql/transforms/test/test_property_types.py::TestPropertyTypes::test_property_comparison_planner_allows_numeric_minmax_when_source_type_matches
hogli test posthog/hogql/test/test_property_skip_indexes.py::TestEventPropertySkipIndexes::test_typed_numeric_mat_col_uses_minmax_index
hogli test posthog/hogql/test/test_property_skip_indexes.py::TestEventPropertySkipIndexes::test_typed_datetime_mat_col_uses_minmax_index
```

## Good Reviewer Questions

- Does this inferred type match what ClickHouse actually returns for representative non-literal inputs?
- If this type is wrong, can it remove a wrapper, change a comparison, or route a property through the wrong physical source?
- Does this change preserve the default permissive behavior for unsupported functions and unknown expressions?
- Is an optimization guarded by semantic type, physical type, index availability, and restricted-property state?
- Is a snapshot change backed by a focused test that explains why the emitted SQL is now safe?
- Is this a metadata improvement, an opt-in simplification, or a behavior-changing rewrite?
- If it is behavior-changing, is the blast radius narrow and covered by tests?

## Out Of Scope For This PR

Do not ask this PR to finish every related project.
These are intentionally left for follow-up work:

- strict HogQL validation
- full ClickHouse function-signature parity
- strict lambda arity and return validation for every higher-order helper
- production policy for creating typed materialized columns
- global rollout of the type-aware simplifier
- complete aggregate combinator and aggregate-state coverage
- broad query-corpus validation against ClickHouse `toTypeName(...)`
