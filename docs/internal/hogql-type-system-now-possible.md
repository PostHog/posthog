# HogQL Type System: What Is Now Possible

This document describes the HogQL type-system capabilities added by the first real implementation slice of the HogQL type-system project.
It is a companion to `docs/internal/hogql-type-system-todo.md`.

The short version: HogQL now has a structured runtime type model, a type algebra, a generic function return inference path, cast/accessor typing, set-query type unification, and diagnostics that can explain where type information is still missing.
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
- strings, fixed strings, UUIDs, booleans, dates, datetimes, intervals, JSON-ish values, and enums
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
The old `TupleType` compatibility object remains positional, but the runtime adapter can carry names for callers that need them.

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
- conversion functions: `toInt`, `toFloat`, `toDecimal`, `toDate`, `toDateTime`, `toDateTime64`, `toUUID`, `toBool`, `toString`, `toTypeName`
- array functions: `array`, `arrayConcat`, `arraySlice`, `arrayElement`, `arrayJoin`, `arrayFirst`, `arrayLast`, `arrayEnumerate`, `arrayMap`, `arrayFilter`, `arrayExists`, `arrayAll`, `arraySum`, `arrayAvg`, `arrayMin`, `arrayMax`
- tuple functions: `tuple`, `tupleElement`
- common aggregates: `count`, `countIf`, `countDistinct`, `uniq*`, `sum`, `avg`, `min`, `max`, `any`, `groupArray`, `array_agg`

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

Array slices preserve array element type.
Array access resolves to the array element type.
`StringArrayType` remains supported as a compatibility alias, but structured runtime adapters can represent it as `Array(String)`.

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

`posthog/hogql/type_diagnostics.py` adds two entry points.

`resolve_with_type_diagnostics(...)` returns a resolved AST plus a `TypeDiagnosticReport`.
The report records unknown-type occurrences and groups them by source.

Example:

```python
diagnostics = resolve_with_type_diagnostics(parse_select("SELECT base64Encode('test')"), context)
diagnostics.report.unknowns_by_source()
# {"missing_function_signature": 1}
```

`function_catalog_inventory()` summarizes runtime function-catalog coverage:

- total function metadata entries
- entries by dialect
- entries with legacy signatures
- entries with precise signatures
- entries with wildcard signatures
- entries with unknown return signatures
- aggregate entries
- aggregate entries without return types
- functions without signatures
- aggregate functions without return types

This is the Phase 0 measurement hook from the TODO.
It gives developers a way to track whether type coverage is improving without requiring strict mode.

## Optimizer Hooks Now Available

The following optimizer work can now be built on explicit type APIs instead of ad hoc class checks.

Redundant cast detection:

- `toString(String)` can be proven redundant.
- `toDate(Date)` can be proven redundant.
- `toDateTime(DateTime)` can be proven redundant when precision and timezone do not change.
- `assumeNotNull(non_nullable_expr)` can be proven redundant.
- Casts that change nullability, timezone, precision, parsing semantics, or type family can stay in place.

Literal-side conversion:

- numeric column vs numeric literal can be classified as definitely compatible or cheap-cast
- string column vs datetime literal can be classified as expensive parse/cast
- datetime/date promotion can be handled explicitly
- unknown function outputs can block rewrites

Nullability simplification:

- comparisons between definitely non-nullable expressions can avoid defensive `ifNull(...)`
- known nullable expressions can preserve current wrapper behavior
- unknown expressions remain barriers

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

Higher-order array functions do not yet bind lambda argument types from surrounding array element types.
`arrayMap` and `arrayFilter` have useful array-shape inference, but not full lambda return inference.

Property-definition metadata is not yet part of planning.
The type system can represent physical and semantic type facts, but the property materialization planner still needs a separate pass that combines property definitions, materialized column metadata, restricted-property access control, and printer behavior.

Aggregate states are represented structurally, but the common state/merge pairs still need deeper catalog coverage before preaggregation transformations can rely on final and intermediate state types.

Strict mode is not enabled.
Unknowns remain printable.
That is intentional until catalog coverage and compatibility baselines are stronger.

No optimizer rewrite is enabled by this slice.
The APIs needed for safe rewrites now exist, but removing casts, moving conversions, or simplifying null wrappers should be done in separate guarded changes with emitted-SQL tests and ClickHouse integration tests where planner behavior matters.

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

## Suggested Next Work

The next practical implementation slice should be a guarded cast simplifier.
It can use the new cast typing and comparison compatibility APIs without touching property planning yet.

Good first targets:

- remove `toString(...)` around expressions already known to be strings
- remove `toDate(...)` around expressions already known to be dates
- remove `toDateTime(...)` around expressions already known to be datetimes when timezone and precision do not change
- remove `assumeNotNull(...)` around non-nullable expressions
- keep unknowns and expensive casts unchanged

After that, the property-comparison optimizer can use the same APIs with materialized-property metadata.
That second step is where skip-index wins become realistic, but it should be separate because it needs ClickHouse planner tests and access-control checks.
