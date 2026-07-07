# HogQL Type System: What Is Now Possible

This document describes the HogQL type-system capabilities that are now implemented on this branch.
It is a companion to `docs/internal/hogql-type-system-todo.md`.

The short version: HogQL now has a structured runtime type model, a type algebra, a generic function return inference path, cast/accessor typing, window-function typing, set-query type unification, diagnostics that can explain where type information is still missing and what each top-level select expression resolves to, typed property expressions, materialized-column physical-type facts, property comparison planning, typed materialized-property range rewrites for physically typed sources, safe typed `JSONExtract(...)` materialized-column rewrites, type-aware nullability wins in generated SQL, and an opt-in internal simplifier for conservative type-aware rewrites, constant conversions, literal JSON paths, and numeric literal arithmetic folding.
The old resolver-facing `ConstantType` classes still exist and remain the compatibility surface for the resolver, printers, and transforms.
The new model sits behind that surface so existing query compilation remains permissive while optimizers can start asking sharper questions.

## Compatibility Model

The default behavior remains permissive.
Queries that compile today should keep compiling unless a separate behavior-changing optimization is explicitly introduced and tested.

Unknown types are still allowed.
They are now more visible and more intentionally treated as optimizer barriers.
That means a function without a known return type can still print, but a future optimizer can decline to remove casts, move conversions, or simplify nullability wrappers around that expression.

This is important because HogQL is used in user-authored queries, generated product queries, internal query runners, and multiple SQL print targets.
The type-system work improves metadata first.
It does not turn HogQL into a strict SQL validator.

## Structured Runtime Types

The new runtime type model lives in `posthog/hogql/type_system.py`.

`RuntimeType` can represent the major SQL type constructors that the old `ConstantType` hierarchy flattened away:

- integer signedness and bit width
- float width
- decimal precision and scale
- strings, fixed strings, low-cardinality wrappers, UUIDs, booleans, dates, datetimes, intervals, JSON-ish values, and enums
- datetime precision and timezone
- nullable wrappers
- arrays with element types
- tuples with positional item types and optional field names
- maps with key and value types
- aggregate states with wrapped types
- unknown types with source metadata

The old resolver still assigns `ast.ConstantType` objects to expressions.
The new model adds conversion functions:

- `runtime_type_from_constant_type(...)`
- `constant_type_from_runtime_type(...)`
- `runtime_type_from_database_field(...)`
- `parse_sql_runtime_type(...)`
- `parse_clickhouse_type(...)`

This gives the codebase a bridge between the old AST metadata and a more precise SQL runtime model.
The bridge matters because existing printers and transforms already expect `IntegerType`, `DateTimeType`, `ArrayType`, `TupleType`, and `UnknownType`.
Changing that public shape all at once would be too risky.
`MapType` now joins that compatibility layer for map key/value metadata while the structured runtime model keeps the dialect-specific details.

## Structured ClickHouse Type Parsing

ClickHouse type strings can now be parsed structurally instead of being reduced to broad buckets.

Examples:

```python
parse_clickhouse_type("UInt64")
# RuntimeType(family="integer", signed=False, bits=64, nullable=False)

parse_clickhouse_type("Nullable(DateTime64(3, 'UTC'))")
# RuntimeType(family="datetime", precision=3, timezone="UTC", nullable=True)

parse_clickhouse_type("Array(Tuple(id UInt64, ts DateTime64(3, 'UTC')))")
# RuntimeType(
#     family="array",
#     item_type=RuntimeType(
#         family="tuple",
#         field_names=("id", "ts"),
#         item_types=(UInt64, DateTime64(3, "UTC")),
#     ),
# )
```

The parser understands `Nullable`, `LowCardinality`, `Array`, `Tuple`, `Map`, decimal variants, integer widths, float widths, `DateTime`, `DateTime64`, `FixedString`, `Enum`, `UUID`, `JSON`, `AggregateFunction`, and `SimpleAggregateFunction`.
`LowCardinality(...)` is preserved as an explicit runtime type fact instead of being erased while unwrapping the inner family.

This makes several follow-up tasks possible:

- comparing inferred HogQL expression types with ClickHouse result metadata
- carrying tuple field names from `DESCRIBE` or warehouse metadata
- detecting whether a cast changes timezone, precision, or nullability
- deciding whether a materialized column already has the physical type a property comparison needs

## Database Field Adapters

Database fields can now be converted to structured runtime types with `runtime_type_from_database_field(...)`.

This also fixed a concrete bug from the TODO:

`FloatArrayDatabaseField.get_constant_type()` now returns `ArrayType(item_type=FloatType())`.
Previously it returned `FloatType()`, which erased the array dimension before the resolver or printer could reason about it.

Struct fields also preserve field names in the structured runtime model.
The old `TupleType` compatibility object now also carries optional field names, so tuple names can survive the bridge back into resolver-facing types.

## Type Algebra

The new type algebra exposes:

- `least_common_supertype(...)`
- `least_common_runtime_type(...)`
- `comparison_compatibility(...)`

`least_common_supertype(...)` works over the existing `ConstantType` objects and returns a `ConstantType`, so resolver code can use it without changing its public type assignments.

Examples:

```python
least_common_supertype([IntegerType(nullable=False), FloatType(nullable=False)])
# FloatType(nullable=False)

least_common_supertype([
    ArrayType(nullable=False, item_type=IntegerType(nullable=False)),
    ArrayType(nullable=True, item_type=FloatType(nullable=False)),
])
# ArrayType(nullable=True, item_type=FloatType(nullable=False))

least_common_supertype([DateType(nullable=False), DateTimeType(nullable=True)])
# DateTimeType(nullable=True)
```

`comparison_compatibility(...)` gives optimizers a first classification API:

- `DEFINITELY_COMPATIBLE`
- `CHEAP_CAST`
- `EXPENSIVE_CAST`
- `INCOMPATIBLE`
- `UNKNOWN`

That distinction is the beginning of the cast and property-comparison optimizer work.
For example, comparing an integer to a float is a cheap numeric promotion, while comparing a string to a datetime requires parse semantics and should not be silently moved across expression boundaries without stronger proof.

## Generic Function Return Inference

The old signature format could only say: these concrete argument classes return this concrete result class.
That works for simple scalar functions but does not express relationships such as:

- `T -> T`
- `(T, U) -> least_common_supertype(T, U)`
- `Array[T] -> T`
- `Array[T] -> Array[T]`
- `Tuple[..., T_i, ...] -> T_i`

The resolver now calls `infer_function_return_type(...)`.
That function first tries generic inference for high-value functions, then falls back to legacy `HogQLFunctionMeta.signatures`.

The old signature catalog still works.
The new path adds behavior where the old catalog was structurally unable to help.

Newly inferred function groups include:

- comparisons: `equals`, `notEquals`, `less`, `greater`, `in`, `notIn`, and related boolean predicates
- logical functions: `and`, `or`, `xor`, `not`
- conditionals: `if`, `multiIf`, `coalesce`, `ifNull`, `nullIf`
- nullability helpers: `assumeNotNull`, `toNullable`
- conversion functions: `toInt`, `toFloat`, `toDecimal`, `toDate`, `toDateTime`, `toDateTime64`, `toUUID`, `toBool`, `toString`, `toTypeName`, `accurateCast`, `accurateCastOrNull`, and `reinterpretAs*`
- common string helpers: `base64Encode`, `base64Decode`, `hex`, `unhex`, `lower`, `upper`, `substring`, `replace*`, `extract`, `splitBy*`, and related string-array helpers
- common URL helpers: `protocol`, `domain`, `path`, `queryString`, `extractURLParameter`, `URLHierarchy`, `encodeURLComponent`, `cutQueryString`, `cutURLParameter`, and `port`
- date/time helpers: date-part extractors such as `toYear`, `toMonth`, and `dateDiff`, formatting/readability helpers such as `formatDateTime` and `formatReadableSize`, `fromUnixTimestamp`, `timeSlot`, `timeSlots`, and explicit `dateAdd`/`dateSub`/`addDays`/`subtractDays`-style families
- JSON extraction: `JSONExtract(..., 'Type')` parses the return-type literal, including `Array(...)`, tuple, numeric, date, datetime, boolean, UUID, and nullable wrappers supported by the runtime type parser
- JSON helpers: `JSONExtractInt`, `JSONExtractFloat`, `JSONExtractBool`, `JSONExtractString`, `JSONExtractRaw`, `JSONExtractKeys`, `JSONExtractArrayRaw`, `JSONExtractKeysAndValues`, `JSON_VALUE`, `JSONHas`, `JSONType`, and `JSONLength`
- array functions: `array`, `arrayConcat`, `arraySlice`, `arrayElement`, `arrayJoin`, `arrayFirst`, `arrayLast`, `arrayFirstIndex`, `arrayLastIndex`, `arrayCount`, `arrayEnumerate`, `arrayMap`, `arrayFilter`, `arrayExists`, `arrayAll`, `arrayZip`, `arrayFlatten`, `arrayDistinct`, `arraySort`, `arrayReverse`, `arrayReverseSort`, `arrayFill`, `arrayReverseFill`, `arraySplit`, `arrayReverseSplit`, `arrayFold`, `arrayReduce`, `arraySum`, `arrayAvg`, `arrayMin`, `arrayMax`
- tuple and map functions: `tuple`, positional and named `tupleElement`, `map`, `mapFromArrays`, `mapKeys`, `mapValues`, `mapFilter`, `mapApply`, `mapAdd`, `mapSubtract`, `mapUpdate`, `mapExtractKeyLike`, and `mapPopulateSeries`
- common aggregates: `count`, `countIf`, `countDistinct`, `uniq*`, `sum`, `avg`, `min`, `max`, `any`, `argMin`, `argMax`, `quantile*`, `median*`, `groupArray`, `array_agg`, and common aggregate state/merge pairs
- window functions: ranking helpers such as `row_number`, `rank`, and `dense_rank`, plus value helpers such as `lag`, `lead`, `first_value`, `last_value`, and `nth_value`
- bitmap and vector helpers: common bitmap cardinality/predicate/result helpers and vector distance/norm helpers now have optimizer-relevant result families instead of crossing the function boundary as unknowns

This is not full ClickHouse function parity.
It is enough to stop losing types at many common function boundaries and to make the remaining unknowns measurable.

## Cast Typing

`TypeCast` and `TryCast` now receive output types during resolution.

Examples:

```sql
SELECT CAST('2024-01-01 00:00:00' AS DateTime)
```

resolves to `DateTimeType`.

```sql
SELECT TRY_CAST('1' AS INTEGER)
```

in the Postgres-family dialect path resolves to nullable `IntegerType`.

Cast target parsing goes through the structured runtime type parser.
That means future optimizers can ask whether a cast changes family, precision, timezone, or nullability rather than relying only on the target type string.

## Array And Tuple Typing

Array and tuple expressions now preserve structural element information.

Examples:

```sql
SELECT [1, 2.0][1]
```

resolves to `FloatType`, because the array literal computes a least-common-supertype of `IntegerType` and `FloatType`.

Tuple literals resolve to `TupleType` with item types.
Tuple access can then recover the selected item type:

```python
TupleAccess(tuple=Tuple(exprs=[Constant(1), Constant("two")]), index=2)
# StringType(nullable=False)
```

Named tuple metadata now survives through the compatibility layer when the source has field names.
For example, `tupleElement(JSONExtract(json, 'Tuple(name String, score Float64)'), 'score')` resolves to `FloatType`.
Struct database fields also carry their field names into `TupleType`, which gives future projection and accessor optimizers a named lookup path instead of only positional metadata.

Array slices preserve array element type.
Array access resolves to the array element type.
`StringArrayType` remains supported as a compatibility alias, but structured runtime adapters can represent it as `Array(String)`.
`arrayZip(...)` now returns an array of tuples using the element type of each input array.
`arrayFlatten(...)` preserves the flattened item type across nested arrays.
Array-preserving transforms such as `arrayDistinct(...)`, `arraySort(...)`, `arrayReverseSort(...)`, `arrayFill(...)`, and `arrayReverse(...)` keep their input element type.
`arraySplit(...)` and `arrayReverseSplit(...)` return nested arrays using the input element type.
`arrayFold(...)` binds the accumulator argument from the explicit accumulator expression and returns the typed lambda body when available, falling back to the accumulator type.
`arraySum(...)`, `arrayAvg(...)`, `arrayMin(...)`, and `arrayMax(...)` resolve to scalar numeric element types.
`arrayReduce(...)` now reads supported aggregate names from the first constant argument and infers the result from the reduced array element types.

Common higher-order array functions now bind lambda arguments from surrounding array element types.
For example, `arrayMap(x -> x + 0.5, [1, 2])` resolves `x` as `Integer` and the call as `Array(Float)`.
`arrayFilter(x -> x > 1, [1, 2])` keeps the input array element type while typing the predicate body.
Multi-array lambdas bind arguments positionally from each array argument.
When the array comes from `JSONExtract(..., 'Array(String)')`, the parsed JSON return type flows into the lambda argument as well.

## Map Typing

Map expressions now preserve key/value information through the legacy compatibility layer.
`parse_clickhouse_type("Map(String, Nullable(Float64))")` produces a structured runtime map type, and `constant_type_from_runtime_type(...)` can bridge that into `MapType(key_type=StringType, value_type=FloatType(nullable=True))`.

Common map helpers now resolve without falling back to `UnknownType`:

```sql
SELECT map('a', 1, 'b', 2.0)
```

resolves to `MapType(StringType, FloatType)`.

`mapFromArrays(...)` takes key and value types from the input array element types.
`mapKeys(...)` and `mapValues(...)` return arrays of the corresponding key or value type.
Map bracket access resolves to the value type:

```sql
SELECT map('a', 1)['a']
```

resolves to `IntegerType`.

Higher-order map functions now bind lambda arguments from the input map key/value types.
`mapFilter(...)` preserves the input map type.
`mapApply(...)` can infer a new map type when the lambda returns a typed key/value tuple.
Strict lambda arity and return validation are still follow-up work.

## Set Query Output Typing

`SelectSetQueryType` now carries unified output columns.

Previously, set-query consumers effectively got types from the first branch.
Now the resolver computes output column types across all branches using `least_common_supertype(...)` while preserving branch types for lineage.

Example:

```sql
SELECT 1 AS value
UNION ALL
SELECT 2.0 AS value
```

now exports `value` as `FloatType`.

This gives projection pushdown, CTE consumers, and future strict validation a more accurate column contract.

## Diagnostics

`posthog/hogql/type_diagnostics.py` adds several developer-facing entry points.

`resolve_with_type_diagnostics(...)` returns a resolved AST plus a `TypeDiagnosticReport`.
The report records unknown-type occurrences and groups them by source.
It also exposes optimizer blockers, which are unknown expressions that typed rewrites must treat as hard boundaries.
The report now also includes `select_expressions`, one diagnostic per top-level selected expression.
Each entry records the select index, alias, printable expression text, resolver-facing `ConstantType`, structured runtime type, source span, and a `debug_dict()` representation for developer tooling.

Example:

```python
diagnostics = resolve_with_type_diagnostics(parse_select("SELECT throwIf(0, 'not reached')"), context)
diagnostics.report.unknowns_by_source()
# {"missing_function_signature": 1}
diagnostics.report.optimizer_blockers_by_source()
# {"missing_function_signature": 1}

diagnostics = resolve_with_type_diagnostics(parse_select("SELECT 1 AS one"), context)
diagnostics.report.select_expression_types_by_alias()["one"].runtime_type.display()
# "Int64"
```

`build_select_expression_type_name_query(...)` builds a companion query that selects `toTypeName(...)` for the chosen top-level expressions.
That gives tests and diagnostics a direct way to ask ClickHouse what runtime type it sees for the same expression shape.

`compare_select_expression_types_with_type_names(...)` compares the inferred select-expression runtime families and nullability with `toTypeName(...)` output.
The comparison is intentionally family/nullability based rather than exact-width based because the current resolver compatibility layer can infer `Integer` while ClickHouse reports a narrower literal type such as `UInt8`.

`function_catalog_inventory()` summarizes runtime function-catalog coverage:

- total function metadata entries
- entries by dialect
- entries with legacy signatures
- entries with generic inference rules
- entries with precise generic inference rules
- entries with precise signatures
- entries with wildcard signatures
- entries with unknown return signatures
- aggregate entries
- aggregate entries without return types
- functions without signatures
- functions without type inference
- aggregate functions without return types

This is the Phase 0 measurement hook from the TODO.
It gives developers a way to track whether type coverage is improving without requiring strict mode.
The distinction between `functions_without_signatures` and `functions_without_type_inference` matters: a function such as `base64Encode` may have no legacy catalog signature while still being safe for optimizer work because generic inference knows its return family and nullability.

## Optimizer Hooks Now Available

The following optimizer work can now be built on explicit type APIs instead of ad hoc class checks.

Redundant cast detection:

- `toString(String)` can be proven redundant.
- `toDate(Date)` can be proven redundant.
- `toDateTime(DateTime)` can be proven redundant when precision, timezone, nullability, and family facts match.
- `assumeNotNull(non_nullable_expr)` can be proven redundant.
- Casts that change nullability, timezone, precision, parsing semantics, or type family can stay in place.

Literal-side conversion:

- numeric column vs numeric literal can be classified as definitely compatible or cheap-cast
- string column vs datetime literal can be classified as expensive parse/cast
- datetime/date promotion can be handled explicitly
- unknown function outputs can block rewrites

Property and materialized-source planning:

- simple property paths can resolve through loaded property-definition metadata before falling back to their JSON field type
- generated `toFloat(...)`, `toDateTime(...)`, and `toBool(...)` property wrappers carry explicit return metadata, so aliases and outer function calls see the rewritten expression type
- materialized-column introspection now carries the physical ClickHouse type reported by `system.columns`
- string-backed materialized properties keep the existing direct-column minmax rewrite only for semantic string comparisons where lexical ordering is correct
- physically typed materialized numeric and datetime properties can use direct physical-column range comparisons when the planner proves the source type matches the semantic property type and the comparison value is source-compatible
- string datetime constants can move to the literal side as `toDateTime64(..., 6, timezone)`, avoiding `parseDateTime64BestEffortOrNull(materialized_column, ...)` around a typed DateTime materialized source
- ClickHouse integration tests now prove minmax skip-index use for typed numeric and datetime materialized property comparisons, not only emitted-SQL string shape
- the materialized-column helper can create typed physical test columns with `column_type=...`; the production default remains string-backed until rollout policy is decided
- property debug notices now derive materialized, dynamic materialized, property-group, restricted, and JSON source facts from the same access plan used by the optimizer

Nullability simplification:

- comparisons between definitely non-nullable expressions can avoid defensive `ifNull(...)`
- known nullable expressions can preserve current wrapper behavior
- unknown expressions remain barriers
- common non-null string and URL helper calls such as `base64Encode('test')` and `protocol('https://posthog.com')` now stay non-null through resolution, so emitted comparisons no longer need manual `assumeNotNull(...)` to avoid nullable boolean wrappers
- typed aggregate and tuple expressions in generated person joins can avoid defensive `ifNull(...)` wrappers when the resolver proves both comparison sides are non-nullable
- the opt-in simplifier can remove literal `NULL` fallbacks in `ifNull(...)` and `coalesce(...)` when the remaining expression is unchanged

Constant folding:

- finite integer/float literal arithmetic can fold inside the opt-in simplifier, for example `1 + 2 * 3` becomes `7`
- day/week arithmetic on literal `Date` expressions can fold inside the opt-in simplifier, for example `toDate('2024-01-01') + toIntervalDay(2)` becomes `toDate('2024-01-03')`
- safe constant conversions can fold inside the opt-in simplifier, for example `accurateCast('42', 'Int64')`, `toFloat(1)`, and `toBool('true')`
- exact-present literal JSON paths can fold inside the opt-in simplifier for `JSONExtract(...)`, `JSONExtractRaw(...)`, `JSONExtractString(...)`, `JSONHas(...)`, `JSONLength(...)`, and related literal-only helpers
- division and modulo by zero remain untouched
- month/year date interval constants and broad materialized JSON-path rewrites are still follow-up work

Set-query planning:

- set-query columns no longer depend only on the first branch's type
- CTE consumers can see unified column types
- strict mode can later validate branch count and compatibility on top of the same data

Function-catalog work:

- adding a legacy signature still works
- adding a generic inference rule can cover an entire family without enumerating primitive combinations
- missing signatures can be counted and prioritized

## Known Barriers

The foundation is real, but several TODOs remain intentionally incomplete.

Common lambda-first higher-order array functions now bind lambda argument types from surrounding array element types, including sorting, fill/split, and fold helpers.
`arrayReduce(...)` infers result types for supported aggregate names, and `arrayFold(...)` can type both accumulator and element lambda arguments.
Remaining higher-order gaps include broader aggregate-name coverage, aggregate combinator return typing, less-used ClickHouse variants, and strict validation of lambda arity and predicate return types.

Property-definition metadata is now part of property comparison planning.
`posthog/hogql/property_planner.py` combines semantic property-definition types, physical source metadata, materialized-column index metadata, restricted-property access control, and comparison compatibility.
The ClickHouse materialized range rewrite now consumes that plan before using direct physical-source comparisons.

Production-created individually materialized property columns are still generally physically strings today.
The materialization helper can now create typed physical columns with `column_type=...`, but that is a storage hook and proof path rather than a production rollout policy change.
For those columns, numeric and datetime direct range rewrites remain blocked because replacing `toFloat(col) < 5` or `parseDateTime64BestEffortOrNull(col) < ts` with a bare string comparison would change ordering semantics.
The planner treats that source/semantic mismatch as an optimizer barrier.

If ClickHouse introspection reports a typed physical materialized source, such as `Nullable(Float64)` or `Nullable(DateTime64(6, 'UTC'))`, the planner can now prove that the physical column preserves semantic ordering.
The printer then skips the column-side conversion and emits a direct range comparison against the materialized column.
For typed DateTime materialized sources compared with a string constant, the conversion moves to the literal side as `toDateTime64(..., 6, timezone)`.

Typed JSON extraction rewrites are now partially enabled.
`JSONExtract(properties, 'key', 'Type')` can use a materialized column when the parsed requested type exactly matches the physical materialized column type.
For example, a `Nullable(Float64)` extraction can read a `Nullable(Float64)` materialized column instead of decompressing the full JSON blob.

`JSONExtractInt`, `JSONExtractFloat`, and `JSONExtractBool` remain blocked.
Those helpers do not have the same missing-key, JSON null, empty-string, and type-mismatch behavior as the current property access and conversion path, so they still need separate equivalence tests before they can replace existing JSON/property expressions.

Aggregate states are represented structurally in both the runtime model and the resolver-facing compatibility layer.
Common state/merge pairs now preserve enough metadata for typed intermediate and final values:

- `countState(...)` and `countMerge(...)`
- `sumState(...)` and `sumMerge(...)` when the merge input is a typed state
- `avgState(...)` and `avgMerge(...)`
- `quantilesState(...)` and `quantilesMerge(...)`

Broader aggregate combinators, map/forEach variants, and validation that a merge consumes the matching state shape remain follow-up work before preaggregation transformations can depend on this broadly.

Strict mode is not enabled.
Unknowns remain printable.
That is intentional until catalog coverage and compatibility baselines are stronger.

No broad AST rewrite is enabled by default.
The APIs needed for safe rewrites now exist, and the first guarded simplifier is available behind `HogQLContext.enable_type_aware_cast_simplification`.
It remains disabled by default.
Practical printer payoffs are now live: when generic function inference proves a helper returns a non-null value, comparisons can avoid the nullable `ifNull(...)` wrapper that was previously needed only because the function boundary was unknown.
This now covers typed string/URL helpers and generated aggregate/tuple comparison shapes in person joins.
Moving conversions across comparisons or simplifying generated property wrappers should still be done in separate guarded changes with emitted-SQL tests and ClickHouse integration tests where planner behavior matters.

## How To Extend The New System

When adding a new database field, add or verify both:

- the old `get_constant_type()` compatibility result
- the structured `runtime_type_from_database_field(...)` mapping

When adding a ClickHouse function, choose the narrowest useful type behavior:

- use existing legacy `signatures` for simple concrete overloads
- add generic inference in `infer_function_return_type(...)` for relationships such as `T -> T`, `Array[T] -> T`, or least-common-supertype behavior
- leave the function unknown when return behavior is genuinely not modeled yet, and rely on diagnostics to make that visible

When adding an optimizer rule, ask type questions through the new APIs:

- use `least_common_supertype(...)` for branch or argument unification
- use `comparison_compatibility(...)` before moving casts or literals
- use structured runtime types when precision, timezone, tuple fields, maps, arrays, or aggregate states matter
- treat `UnknownType` as an optimizer barrier unless the rewrite is independently proven safe

## Opt-In Type-Aware Simplification

`posthog/hogql/transforms/type_aware_simplification.py` adds the first optimizer consumer.

It runs only when `HogQLContext.enable_type_aware_cast_simplification` is true.
The default query path does not change.

The simplifier currently removes conservative no-op operations:

- `CAST(String AS String)` and equivalent safe string aliases such as `text`, `varchar`, and `char`
- `toString(String)`
- `toDate(Date)`
- `toDateTime(DateTime)` when timezone and precision facts match
- `toBool(Boolean)`
- `assumeNotNull(non_nullable_expr)`
- `toNullable(already_nullable_expr)`
- `ifNull(non_nullable_expr, fallback)`
- `coalesce(non_nullable_expr, ...)`
- literal `NULL` fallbacks in `ifNull(...)` and `coalesce(...)`
- repeated compatible casts in those safe families
- finite numeric literal arithmetic for typed integer and float constants
- day/week interval arithmetic for literal date constants
- safe constant conversion calls
- exact-present literal JSON paths

It deliberately does not remove casts for families where the current compatibility type model lacks enough precision:

- datetime casts that change timezone or precision
- numeric `TypeCast` nodes, because signedness and width can matter
- decimal casts, because precision and scale can matter
- unknown expressions, which remain optimizer barriers

It also does not fold arithmetic when either side is nullable, non-literal, non-numeric, non-finite, or would require division/modulo by zero.
Literal JSON-path folding only applies to constant JSON documents and exact present paths.
Missing paths, dynamic paths, JSON null ambiguity, and materialized-column/property equivalence remain barriers.

This gives internal callers a safe way to compare emitted SQL before and after simplification without changing user-authored HogQL behavior.

## Suggested Next Work

`posthog/hogql/property_planner.py` now adds property-planning metadata for materialized property comparisons.
It separates semantic property-definition type facts from physical source type facts, reports selected materialized-column, dynamic materialized-column, property-group, restricted, or JSON sources, and classifies comparison compatibility for both the semantic property value and the physical source value.

The ClickHouse materialized range rewrite now uses that plan as its guard.
That means lexical string range comparisons can keep their minmax-friendly direct-column shape, typed numeric and datetime materialized sources can use bare physical-column comparisons, and numeric/datetime properties backed by string materialized columns keep their semantic conversion wrappers.
The integration tests now prove that `Nullable(Float64)` and `Nullable(DateTime64(6, 'UTC'))` materialized property comparisons are visible to ClickHouse's minmax skip indexes.

Good first targets:

- decide when property materialization should create typed physical columns instead of string-backed columns
- extend JSON/materialized extraction rewrites beyond exact-type `JSONExtract(...)` only where semantic-equivalence tests prove they are safe
- extend aggregate state typing to map/forEach variants and validate compatible state/merge pairs
- record a representative query-corpus unknown-type baseline before enabling strict resolver mode for internal tests
