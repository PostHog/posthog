# HogQL Type System TODO

This is a planning document for making HogQL's expression types strong enough to support optimizer work.
It is intentionally not an implementation proposal for one huge PR.
The goal is to document where we are, where type information is lost today, and what TODOs would let us safely optimize away redundant casts, wrappers, JSON extraction work, lazy joins, and other defensive query shapes.

This document is about HogQL expression and SQL runtime types.
It is not about the PostHog TypeScript/Python query schema type generation pipeline described in `docs/published/handbook/engineering/type-system.md`.

HogQL has multiple print targets.
ClickHouse is the highest-value optimization target today, but the type system should account for `clickhouse`, `postgres`, and `duckdb` output from the start.
Dialect differences should be explicit type-system facts, not accidental printer behavior.

## Implementation Status

This branch now contains several implementation slices described by this TODO.
The original document intentionally scoped a multi-phase project; this status section records the pieces that are now real in code and the pieces that remain optimizer, rollout-policy, or catalog-expansion work.

Completed in this branch:

- Added `posthog/hogql/type_system.py`, a structured runtime type model that keeps the existing resolver-facing `ConstantType` API while adding dialect-aware runtime metadata.
- Added adapters between current `ConstantType` objects, `DatabaseField` objects, and structured SQL runtime types.
- Added a structured ClickHouse type parser for wrappers and parametric types such as `Nullable`, `LowCardinality`, `Array`, `Tuple`, `Map`, `Decimal`, `DateTime64`, integer widths, float widths, and aggregate states.
- Added basic Postgres and DuckDB type-name adapters for cast and metadata paths.
- Fixed `FloatArrayDatabaseField.get_constant_type()` so float arrays resolve as `ArrayType(FloatType)` instead of losing the array dimension.
- Added type algebra for least-common-supertypes across common numeric, date/datetime, array, tuple, and string-ish families.
- Added comparison compatibility classification so optimizers can distinguish definitely-compatible comparisons, cheap casts, expensive parse/cast cases, incompatible comparisons, and unknowns.
- Added generic function return inference for high-value functions that the old tuple signature format could not express, including comparisons, logical functions, `if`, `multiIf`, `coalesce`, nullability helpers, casts/conversions, common string and URL helpers, array constructors/accessors, tuple constructors/accessors, and common aggregate functions.
- Kept existing legacy function signatures working as a fallback path.
- Added resolver typing for `TypeCast`, `TryCast`, array literals, tuple literals, array access, array slices, tuple access, common aggregate calls, and set-query output columns.
- Added unified output-column typing for `SelectSetQueryType`, while preserving the branch-type list for lineage consumers.
- Added `MapType` compatibility metadata and generic inference for `map(...)`, `mapFromArrays(...)`, `mapKeys(...)`, `mapValues(...)`, map access, and parsed `Map(K, V)` return types.
- Added resolver binding for higher-order map lambdas, so `mapFilter(...)` and `mapApply(...)` lambda parameters inherit key/value types from the input map.
- Added `mapFilter(...)` result typing and `mapApply(...)` result typing when the lambda returns a typed key/value tuple.
- Added structural array function inference for `arrayZip(...)` and `arrayFlatten(...)`.
- Added array helper inference for array-preserving transforms such as `arrayDistinct(...)`, `arraySort(...)`, and `arrayReverse(...)`, plus scalar helpers such as `arraySum(...)`, `arrayAvg(...)`, `arrayMin(...)`, and `arrayMax(...)`.
- Added `arrayReduce(...)` inference for supported aggregate names such as `sum`, `avg`, `min`, `max`, and `uniq`.
- Added scalar aggregate inference for `argMin(...)`, `argMax(...)`, `quantile*`, `median*`, and `uniq*` variants.
- Added `posthog/hogql/type_diagnostics.py` with a typed-AST diagnostic helper and a function-catalog inventory helper that distinguishes missing legacy signatures from missing type inference.
- Added `posthog/hogql/transforms/type_aware_simplification.py` with an opt-in internal simplifier for conservative redundant casts and nullability wrappers.
- Added `HogQLContext.enable_type_aware_cast_simplification`, which keeps the simplifier disabled by default while letting internal callers exercise it.
- Added emitted-SQL coverage showing typed string and URL helpers such as `base64Encode(...)` and `protocol(...)` no longer need manual `assumeNotNull(...)` to avoid defensive comparison wrapping.
- Added resolver binding for common higher-order array lambdas, so lambda parameters inherit element types from surrounding array arguments and `arrayMap(...)` can infer its return element type from the lambda body.
- Added parsed return-type inference for `JSONExtract(..., 'Type')`, including typed array results that feed higher-order lambda binding.
- Added family-specific JSON helper inference for `JSONExtract*`, `JSON_VALUE`, `JSONHas`, `JSONType`, and `JSONLength`, including typed `JSONExtractKeysAndValues(...)` tuples and `JSONExtractArrayRaw(...)` arrays.
- Added optimizer-blocker diagnostics on `TypeDiagnosticReport`, including grouping by detail/source and representative no-blocker coverage for typed query shapes that optimizer work can now target.
- Added focused tests in `posthog/hogql/test/test_type_system.py` for runtime type parsing, database-field adapters, algebra, resolver inference, set-query unification, diagnostics, and catalog inventory.
- Added `docs/internal/hogql-type-system-now-possible.md`, which documents the new capabilities and the next optimizer hooks.
- Added `posthog/hogql/property_planner.py`, which combines semantic property types, physical property sources, source index metadata, restricted-property materialization rules, and comparison compatibility into optimizer-ready property comparison plans.
- Wired the ClickHouse materialized-column range rewrite through that property comparison plan, so the existing string minmax-friendly rewrite only uses direct physical-source comparisons when the planner says the source type matches the property semantics.
- Materialized-column introspection now carries the ClickHouse physical type reported by `system.columns`, so property planning can distinguish string-backed property materialization from typed physical sources.
- Added typed materialized-property comparison rewrites for physically typed numeric and datetime materialized sources whose physical source columns can support semantic ordering.
- Added a typed materialized-column storage hook for tests and future rollout work, so `materialize(..., column_type=...)` can create physical columns such as `Nullable(Float64)` and `Nullable(DateTime64(6, 'UTC'))` while preserving the default string-backed behavior.
- Added ClickHouse planner integration tests proving minmax skip-index usage for typed numeric and datetime materialized property comparisons.
- Added safe typed `JSONExtract(properties, 'key', 'Type')` materialized-column rewrites when the requested parsed type exactly matches the physical materialized column type.
- `PropertySwapper` now gives generated Float, DateTime, and Boolean property conversion calls explicit return metadata, so aliases and outer calls see the rewritten expression type rather than stale property-source types.
- `PropertyType.resolve_constant_type()` now resolves simple property paths through loaded property-definition metadata when available.
- Property debug notices now derive source/materialization status from the same property access plan used by the optimizer.
- Added explicit `LowCardinality` preservation in structured runtime types, so this wrapper is a distinct type fact instead of being silently erased.
- Added tuple field names to the resolver-facing `TupleType` compatibility layer, plus named `tupleElement(tuple, 'field')` inference for typed tuple metadata such as `JSONExtract(..., 'Tuple(name String, score Float64)')` and struct database fields.
- Added `AggregateStateType` as a compatibility type for aggregate state expressions, with generic inference for common state/merge pairs such as `countState`/`countMerge`, `sumState`/`sumMerge` when the state is typed, `avgState`/`avgMerge`, and `quantilesState`/`quantilesMerge`.
- Extended the opt-in type-aware simplifier to remove redundant `toDateTime(DateTime)` and repeated compatible safe casts when precision, timezone, family, and nullability facts match.
- `TypeDiagnosticReport` now includes typed top-level select-expression diagnostics, including alias, printable expression text, resolver `ConstantType`, and structured runtime type details.
- Added a `toTypeName(...)` companion-query builder and comparison helper so inferred select-expression families/nullability can be checked against ClickHouse type-name output.
- Extended the opt-in type-aware simplifier to fold finite numeric literal arithmetic for typed integer and float constants while preserving divide-by-zero and other unsafe cases.
- Added lambda-aware inference for more common lambda-first array helpers, including `arraySort(...)`, `arrayReverseSort(...)`, `arrayFill(...)`, `arrayReverseFill(...)`, `arraySplit(...)`, `arrayReverseSplit(...)`, and `arrayFold(...)`.
- Added resolver typing for window functions such as `row_number()`, `rank()`, `lag(...)`, `lead(...)`, `first_value(...)`, and `last_value(...)`.
- Expanded generic function inference for date/time part and formatting helpers, readable string helpers, ClickHouse bitmap helpers, vector distance/norm helpers, more map helpers, and explicit date-add/subtract helper families.
- Extended the opt-in type-aware simplifier to fold safe constant conversion calls, simplify literal `NULL` fallbacks in `ifNull(...)`/`coalesce(...)`, and fold exact-present literal JSON-path reads.
- Fixed ClickHouse overload selection to prefer transformed first-argument types over stale call metadata, so typed DateTime property expressions do not re-enter best-effort parsing.
- Added emitted-SQL coverage for type-aware nullability wins in generated person joins, where typed aggregate/tuple expressions no longer need defensive `ifNull(...)` wrappers.
- Extended the opt-in type-aware simplifier to fold day/week date interval arithmetic for literal `Date` expressions while leaving month/year calendar arithmetic untouched.

Still intentionally left as follow-up work:

- Full ClickHouse parity for every function signature and aggregate combinator.
- Full higher-order array parity beyond common lambda-first functions, especially strict lambda arity/return validation and less-used ClickHouse variants.
- Full higher-order map parity beyond key/value binding, especially strict lambda arity and return validation.
- Production rollout policy for when property materialization should create typed physical columns instead of string-backed columns.
- Broader rollout of cast, constant, literal JSON, and nullability wrapper simplification beyond the internal opt-in flag.
- Broader aggregate-state/combinator coverage, especially map/forEach variants and validation of compatible state/merge pairs.
- Strict resolver mode.
- Query-corpus unknown-type baselines and broader ClickHouse integration tests for inferred result types, nullability, timezone-sensitive behavior, and planner/index wins beyond the typed materialized-property cases already covered.

Branch hygiene before merge:

- [ ] Regenerate the revenue analytics `.ambr` snapshots from the full snapshot-bearing test classes.
      The current branch diff drops many live revenue snapshot entries while the Python tests still exist, which looks like a partial snapshot update rather than an intentional type-system change.

The compatibility constraint below still applies.
Unknown or partially-known expressions remain printable by default; missing signatures are optimizer barriers, not user-facing errors.

## Why This Matters

HogQL already has type annotations on AST nodes, but they are mostly good enough for field resolution, printing, nullability checks, and a few local transformations.
They are not yet reliable enough to make broad optimizer decisions.

The motivating example is function boundaries.
We can often know that a field is a `DateTime`, `Float`, `String`, or `Array`, but once that field passes through a function, the resolver only preserves the return type if the function catalog has a matching signature.
If the function has no signatures, or if the signature language cannot express the relationship between the argument and the return type, the call becomes `UnknownType`.
Downstream printers and transforms then add defensive wrappers or skip optimizations.

Concrete symptoms in the current codebase:

- `posthog/hogql/resolver.py` assigns `CallType` only after matching `func_meta.signatures`.
  Missing signatures fall back to `UnknownType`, and the stricter error path is commented out until the mappings are complete.
- `posthog/hogql/printer/test/test_printer.py` has tests showing missing function type inference makes comparisons need `ifNull(...)` wrapping unless the user writes `assumeNotNull(...)`.
- `posthog/hogql/transforms/property_types.py` manually attaches a `DateTimeType` return type to a generated `toDateTime(...)` call so an outer `toDateTime(...)` can avoid reparsing an already-datetime expression.
- `posthog/hogql/printer/clickhouse.py` has to look through aliases because a transform can rewrite an inner expression while the alias's declared type is stale.
- `posthog/hogql/test/test_property_skip_indexes.py` documents cases where typed property conversion makes a query execute correctly, but wrapping a materialized column in `toFloat(...)` or `toDateTime(...)` hides that column from minmax skip indexes.

The intended outcome is not stricter validation for its own sake.
The outcome is trustworthy optimizer input.

## Compatibility Constraint

All existing HogQL and SQL that works today should keep working by default.
The type system should start as better metadata, diagnostics, and opt-in optimizer input, not as a new source of user-facing breakage.

TODO:

- [ ] Keep unknown or partially-known expressions printable unless a caller explicitly opts into strict validation.
- [ ] Keep strict mode limited to tests, diagnostics, selected internal queries, or explicit developer workflows until coverage is high.
- [ ] Treat missing function signatures as optimizer barriers by default, not immediate user-facing errors.
- [ ] Put behavior-changing optimizations behind modifiers, internal flags, or equivalence tests before enabling them broadly.
- [x] Add compatibility tests that compile representative typed HogQL query shapes before optimizer work depends on them.
- [ ] Preserve parser and printer acceptance for existing query shapes, even if the new type diagnostics can explain that a shape is imprecisely typed.

Acceptance criteria:

- Existing queries do not stop compiling because the type system became more precise.
- Any intentional semantic change is documented, tested, and rolled out separately from type metadata work.
- The default path remains permissive until there is enough confidence to make a narrower strict path useful.

## Current State

### Core Type Model

The base type machinery lives in:

- `posthog/hogql/base.py`
- `posthog/hogql/ast.py`
- `posthog/hogql/database/models.py`

Every `Expr` has an optional `type`.
The type hierarchy is split between:

- Scope/table types, such as `TableType`, `LazyJoinType`, `LazyTableType`, `TableAliasType`, `SelectQueryType`, `SelectSetQueryType`, `CTETableType`, and `SelectQueryAliasType`.
- Field and property types, such as `FieldType`, `PropertyType`, `ExpressionFieldType`, `FieldAliasType`, and `UnresolvedFieldType`.
- Constant/runtime expression types, such as `IntegerType`, `FloatType`, `DecimalType`, `StringType`, `StringJSONType`, `StringArrayType`, `BooleanType`, `DateType`, `DateTimeType`, `IntervalType`, `UUIDType`, `ArrayType`, `TupleType`, `MapType`, `CallType`, and `UnknownType`.

`ConstantType` has two important fields today:

- `data_type`
- `nullable`

This is useful, but intentionally coarse.
The structured runtime model now carries ClickHouse precision, scale, timezone, signedness, low cardinality, enum values, named tuple fields, aggregate states, nested nullability, and most first-slice parametric constructors.
The legacy `ConstantType` compatibility model now carries map key/value types, tuple field names, and aggregate-state wrappers, but it still omits most ClickHouse-specific precision details for optimizer decisions.

Database fields map to constant types through `DatabaseField.get_constant_type()`.
The mapping is also coarse.
For example:

- `IntegerDatabaseField` always becomes `IntegerType`, regardless of `UInt8`, `UInt64`, `Int32`, etc.
- `DecimalDatabaseField` becomes `DecimalType`, with no precision or scale.
- `DateTimeDatabaseField` becomes `DateTimeType`, with no `DateTime64` precision or timezone.
- `StringArrayDatabaseField` becomes `StringArrayType`, which is a `StringType` subclass rather than `ArrayType(StringType)`.
- `FloatArrayDatabaseField` now resolves to `ArrayType(FloatType)`.
- `StructDatabaseField` becomes `TupleType`, but tuple field names are not represented in the type object.

### Resolver

The resolver lives in `posthog/hogql/resolver.py`.
It performs several jobs at once:

- Resolves table and field names.
- Resolves CTEs, aliases, subqueries, joins, and lazy table scope.
- Expands asterisk expressions.
- Rewrites selected PostHog-specific functions into lower-level AST.
- Assigns `type` metadata onto returned AST nodes.
- Handles dialect-specific behavior for ClickHouse and the Postgres-family targets (`postgres` and `duckdb`).

Some useful things already work:

- Python constants are typed by `resolve_constant_data_type`.
- Field types flow through subqueries and CTEs via `SelectQueryType.columns`.
- Basic arithmetic infers `IntegerType`, `FloatType`, and `DateTimeType` for selected combinations.
- Boolean operators and comparison operators get boolean result types.
- Some date truncation and conversion functions have signatures.
- Tests in `posthog/hogql/test/test_resolver.py` cover subquery type propagation, arithmetic, booleans, comparisons, selected function types, date truncation return types, and nullability overrides for `assumeNotNull`, `nullIf`, and `toNullable`.

The function boundary behavior has improved, but catalog coverage is still the main limitation.
For a ClickHouse function call, the resolver:

1. Visits all arguments.
2. Resolves each argument to a `ConstantType`.
3. Looks up the function in `HOGQL_CLICKHOUSE_FUNCTIONS`.
4. Asks `infer_function_return_type(...)` for generic return inference.
5. Falls back to the legacy signature list when no generic inference applies.
6. Falls back to `UnknownType` otherwise.

The old signature matcher in `posthog/hogql/functions/core.py` is still class-based.
`UnknownType` in a legacy signature acts as a wildcard.
`StringLiteralType` can constrain constant string values.
The new generic inference path covers many high-value relationships, but it is not a full signature DSL with type variables, overload ranking, aggregate combinators, or strict errors.

### Function Catalog

Function metadata lives mostly in:

- `posthog/hogql/functions/mapping.py`
- `posthog/hogql/functions/aggregations.py`
- `posthog/hogql/functions/clickhouse/*.py`
- `posthog/hogql/functions/posthog.py`
- `posthog/hogql/functions/udfs.py`

`HogQLFunctionMeta` currently records arity, aggregate status, ClickHouse name, overloads, suffix args, timezone behavior, placeholder rendering, parametric first-arg behavior, and optional signatures.

A rough source-level inventory on 2026-06-02 found:

- 881 `HogQLFunctionMeta(...)` constructor occurrences under `posthog/hogql/functions`.
- 148 `signatures=` occurrences under the same tree.

This is not an exact runtime catalog count because some entries are generated through loops and comprehensions.
It is still a useful signal: the signature coverage is far behind function exposure.

Some high-value function groups are partially typed:

- Arithmetic functions have several numeric signatures.
- Many date/time functions have signatures.
- JSON functions use `generate_json_path_signatures`.
- Some string and geo functions have signatures.
- Some PostHog extension functions have signatures.

Many high-value groups are now typed through generic inference, including logical/comparison functions, common conditionals, common array/map helpers, common string and URL helpers, and common scalar aggregates.
The remaining gaps are more specific:

- Aggregate state/merge functions and aggregate combinators.
- Deeper date/time function families beyond the high-use conversion and parsing paths.
- Specialized ClickHouse families that are not common optimizer inputs yet.
- Strict lambda arity and return validation for higher-order array/map functions.
- UDFs.

Aggregate state and merge coverage is still incomplete outside the common typed pairs.
Some entries are marked `aggregate=True` but still have no return type signature or generic inference.
This blocks typed handling for broader preaggregation and aggregation state transformations.

### Property Typing

Property handling currently spans type resolution, transform-time metadata lookup, and printing:

- `FieldType.get_child()` returns `PropertyType` for `StringJSONDatabaseField`, `StringArrayDatabaseField`, and `StructDatabaseField`.
- `PropertyType.resolve_constant_type()` can traverse `StructDatabaseField` fields, propagate nested nullability, and resolve simple property paths through loaded property-definition metadata when available.
- For JSON and array-ish properties without loaded metadata, `PropertyType` still falls back to the underlying field's constant type with `nullable=True`.
- `build_property_swapper()` loads `PropertyDefinition` rows and materialized slot metadata.
- `PropertySwapper` wraps typed properties with conversion calls such as `toFloat(...)`, `toDateTime(...)`, and `toBool(...)`, and generated conversion calls now carry explicit return metadata for downstream aliases and outer calls.
- The printer decides between JSON extraction, materialized columns, dynamic materialized slots, and property group columns.
- Property comparison planning now combines semantic property types, physical source types, source index metadata, and restricted-property rules before materialized comparison rewrites run.
- Exact-type `JSONExtract(properties, 'key', 'Type')` calls can use a materialized column when the requested parsed type matches the physical materialized column type.

This means property type knowledge is more coherent for comparison planning, but it is still not one fully unified type source.
Some type facts are in the schema.
Some are in property definitions.
Some are in materialized column metadata.
Some are only visible in printer logic.

The skip-index tests in `posthog/hogql/test/test_property_skip_indexes.py` show why this matters.
A materialized property column can be directly usable by ClickHouse indexes.
If we add a conversion call around the column because the type system cannot prove the column and literal are already compatible, the query may execute correctly but lose index eligibility.
Typed physical numeric and datetime materialized columns now have integration tests proving that direct range comparisons stay visible to ClickHouse minmax skip indexes.

### Typed Metadata Lifecycle

The current AST typing lifecycle is fragile:

- `resolve_types` returns a cloned/resolved AST and refuses to visit nodes that already have a `type`.
- Some transforms keep types (`clear_types=False`) because they need lineage information.
- Some transforms clear types (`clear_types=True`) because they rewrite expressions enough that old types are unsafe.
- Some transforms mutate type objects directly, such as pruning `SelectQueryType.columns`.
- Some nested transforms call `resolve_types(...)` again on newly constructed subqueries or joins.
- Alias types can become stale when a transform rewrites an inner expression but keeps the alias wrapper.

This is workable for the current pipeline, but a stronger type system needs clearer rules:

- When is a node type authoritative?
- Which transforms are allowed to preserve types?
- Which transforms must invalidate or recompute types?
- How do we avoid stale alias, subquery, and field lineage metadata?

### Existing Consumers Of Types

Types are already used in several non-trivial ways:

- Printers require resolved table and field types before emitting SQL.
- HogQL can print to ClickHouse, Postgres, DuckDB, and HogQL itself, so expression typing should not assume a single SQL backend.
- `BasePrinter._is_nullable()` uses type metadata to decide when comparisons need `ifNull(...)` wrappers.
- `ClickHousePrinter` chooses function overloads based on the first argument type for selected functions.
- `PropertySwapper` uses field types to identify timestamp fields, JSON fields, lazy join fields, and typed property wrappers.
- `resolve_lazy_tables` uses `FieldType` and `PropertyType` to decide which lazy joins and lazy table fields need to be selected.
- Projection pushdown uses `FieldType`, `ExpressionFieldType`, `SelectQueryType`, `SelectSetQueryType`, and CTE types to track column demand.
- Web analytics prefiltering uses resolved events-table field and property types to build a smaller events subquery.
- Workload detection uses table types.
- Data modeling uses ClickHouse result metadata and warehouse mappings to store saved query column types.
- Feature extraction tests explicitly assert that resolved AST types should be used instead of chain-only heuristics.

These consumers are a constraint.
Any type-system work should preserve their current needs while making expression types more useful.

## What Is Missing

### 1. A Canonical SQL Runtime Type Model

TODO:

- [x] Introduce a separate `RuntimeType` model while keeping `ConstantType` as the resolver/printer compatibility surface.
- [x] Represent ClickHouse primitive families with enough detail for the first optimizer work:
  - [x] signed and unsigned integers with bit width
  - [x] floats with width
  - [x] decimals with precision and scale when the type string provides them
  - [x] strings, fixed strings, UUIDs, booleans, enums
  - [x] dates and datetimes, including `DateTime64` precision and timezone
  - [x] preserve low cardinality wrappers as a distinct type fact
  - [x] nullable wrappers
  - [x] arrays with element types and element nullability
  - [x] tuples with positional and optional named fields
  - [x] maps with key and value types
  - [x] JSON/object-ish values
  - [x] aggregate states
  - [x] unknown runtime types with source metadata
- [x] Represent a common cross-dialect type core plus dialect tags for ClickHouse, Postgres, and DuckDB.
- [ ] Define which types are portable and which are backend-specific.
- [x] Define the relationship between storage fields (`DatabaseField`) and expression types through adapters.
- [x] Make type conversion from ClickHouse type strings structured instead of lossy string cleanup.
- [x] Add basic structured type adapters for Postgres and DuckDB metadata where HogQL prints or introspects those backends.
- [ ] Make type conversion from saved query metadata structured instead of routing through field class names.
- [ ] Decide whether `StringArrayType` should become `ArrayType(StringType)` or remain as a storage-specific alias.
- [x] Fix `FloatArrayDatabaseField` so it does not lose the array dimension.
- [x] Preserve struct/tuple field names where available in structured runtime metadata.
- [x] Represent property-definition type facts separately from physical storage type facts in property comparison planning.

Acceptance criteria:

- A typed field can round-trip from database schema or ClickHouse `DESCRIBE` metadata into the type model without losing major type constructors.
- A typed field can carry enough dialect metadata to print correctly to ClickHouse, Postgres, and DuckDB.
- The type model can answer both "what SQL type does this expression return?" and "what physical column expression can the printer emit?"
- Existing field resolution behavior remains compatible with current query execution.

### 2. A Type Algebra

TODO:

- [x] Add a `least_common_supertype(...)` operation for set queries, `if`, `multiIf`, `coalesce`, arrays, tuples, and maps.
- [x] Add initial nullability algebra:
  - [x] nullable input propagation for common generic functions
  - [x] functions that always return nullable in modeled cases
  - [x] functions that never return nullable in modeled cases
  - [x] functions where nullability depends on specific arguments
  - [x] `assumeNotNull`, `toNullable`, `ifNull`, `coalesce`, `nullIf`, and `*OrNull` behavior
- [x] Add numeric promotion rules matching common ClickHouse paths well enough for first optimizer decisions.
- [ ] Add string/date/datetime coercion rules for PostHog-supported syntax by dialect.
- [x] Add array element unification rules.
- [x] Add tuple element lookup rules.
- [x] Add named tuple lookup rules.
- [x] Add map key/value access rules.
- [x] Add comparison compatibility checks that can distinguish:
  - [x] definitely compatible
  - [x] compatible after cheap cast
  - [x] compatible after expensive parse/cast
  - [x] incompatible
  - [x] unknown
- [ ] Keep ClickHouse-specific rules separate from Postgres/DuckDB rules.
- [x] Pass dialect into the first optimizer-facing type APIs.

Acceptance criteria:

- The resolver can infer a type for `if(cond, a, b)` and `coalesce(a, b, c)` without enumerating every primitive combination.
- The resolver can infer a precise result type for common array and tuple expressions.
- Optimizers can ask whether a cast is redundant, required, unsafe, or expensive.

### 3. A Better Function Signature Engine

The legacy signature format is `list[tuple[tuple[AnyConstantType, ...], AnyConstantType]]`.
It still works for simple functions, but generic inference now handles relationships the tuple format cannot express.

TODO:

- [x] Extend legacy signature tuples with a generic inference path.
- [x] Support common type relationships such as `T -> T`, `Array[T] -> T`, `Array[T] -> Array[T]`, and `(T, T) -> Bool` through generic inference.
- [ ] Support constrained type variables, such as numeric-only, orderable-only, string-like-only, date-like-only, and JSON-path-like.
- [ ] Support variadic signatures without exploding into many generated combinations.
- [ ] Support parametric functions and aggregate combinators.
- [x] Support selected literal-driven return types beyond current `StringLiteralType`, such as cast targets and `JSONExtract(..., 'Type')`.
- [x] Support selected return-type functions, for cases like:
  - [x] `toTypeName(T) -> String`
  - [x] `arrayElement(Array[T], Int) -> T`
  - [x] `arrayMap(Lambda[A -> B], Array[A]) -> Array[B]`
  - [x] lambda-first array helpers such as `arraySort(Lambda, Array[T]) -> Array[T]` and `arrayFold(Lambda, Array[T], Acc) -> Acc`
  - [x] `JSONExtract(json, path..., 'Array(String)') -> Array[String]`
  - [x] `if(Bool, T, U) -> least_common_supertype(T, U)`
  - [x] `count(...) -> UInt64` compatibility type
  - [x] `sum(...)` common scalar return typing
  - [x] `uniq(...) -> UInt64` compatibility type
- [ ] Support overload ranking and deterministic error reporting.
- [x] Distinguish "function is known but signature is incomplete" from "function is unsupported" in diagnostics/inventory.
- [ ] Support dialect-specific function signatures, names, and return types where ClickHouse, Postgres, and DuckDB diverge.
- [ ] Add a strict mode that can fail on unknown function return types once coverage is high enough.

Acceptance criteria:

- Function type inference can represent "return the same type as the first argument" without copying dozens of primitive signatures.
- Higher-order array functions can bind lambda argument types from array element types.
- Missing signatures are measurable and visible in diagnostics.

### 4. Function Catalog Coverage

TODO:

- [x] Add a signature coverage inventory helper/test that reports:
  - [x] total function metadata entries
  - [x] entries by dialect/print target
  - [x] entries with precise signatures
  - [x] entries with wildcard signatures
  - [x] entries with unknown return types
  - [x] aggregate entries without return types
  - [ ] functions used in production query corpus but still unknown
- [ ] Prioritize catalog coverage by optimizer value and dialect reach, not by alphabetical order.
- [x] Cover comparisons and logical functions first:
  - [x] `equals`, `notEquals`, `less`, `greater`, `lessOrEquals`, `greaterOrEquals`
  - [x] `in`, `notIn`
  - [x] `and`, `or`, `xor`, `not`
  - [x] `if`, `multiIf`
- [x] Cover conversion and cast functions:
  - [x] `toInt`, `toFloat`, `toDecimal`, `toBool`, `toString`, `toDate`, `toDateTime`, `toDateTime64`, `toUUID`
  - [x] `accurateCast`, `accurateCastOrNull`, `CAST`, `TRY_CAST`
  - [x] `reinterpretAs*`
  - [x] `toNullable`, `assumeNotNull`, `ifNull`, `coalesce`, `nullIf`
- [ ] Cover property and JSON functions:
  - [x] `JSONExtract(...)` parsed return-type literals
  - [x] remaining `JSONExtract*` family-specific precision
  - [x] `JSON_VALUE`
  - [x] `JSONHas`, `JSONType`, `JSONLength`
  - [ ] PostHog property extraction wrappers if any are introduced
- [x] Cover array functions:
  - [x] constructors and element access
  - [x] `arrayConcat`, `arraySlice`, `arrayJoin`, `arrayMap`, `arrayFilter`, `arrayExists`, `arrayAll`, `arrayFirst`, `arrayLast`
  - [x] `arrayReduce` with supported aggregate names
  - [x] `arrayZip`, `arrayFlatten`, `arrayDistinct`, `arraySort`, `arrayReverse`, `arrayReverseSort`, `arrayFill`, `arrayReverseFill`, `arraySplit`, `arrayReverseSplit`, `arrayFold`
  - [x] `arraySum`, `arrayAvg`, `arrayMin`, `arrayMax`
- [ ] Cover tuple and map functions:
  - [x] tuple construction and access
  - [x] named tuple access
  - [x] `map`, `mapFromArrays`, `mapKeys`, `mapValues`, `mapContains`
  - [x] `mapFilter`, `mapApply`, `mapAdd`, `mapSubtract`, `mapUpdate`, `mapExtractKeyLike`, `mapPopulateSeries`
- [ ] Cover aggregate functions:
  - [x] `count`, `countIf`
  - [x] `countState`, `countMerge`
  - [x] `sum`, `sumIf`
  - [x] `sumState`, `sumMerge` for typed state/merge pairs
  - [x] `avg`, `avgIf`
  - [x] `avgState`, `avgMerge`
  - [x] `min`, `max`, `any`, `argMin`, `argMax`
  - [x] `uniq*`
  - [x] scalar `quantile*` and `median*` variants
  - [x] `quantilesState`, `quantilesMerge`
  - [ ] remaining quantile/median state and merge variants
  - [ ] map/forEach aggregate variants
- [x] Cover high-use string and URL functions that unblock emitted-SQL nullability simplification.
- [x] Cover high-use date/time formatting, date-part, and explicit date-add/subtract helper functions that unblock optimizer/nullability decisions.
- [x] Cover high-use bitmap and vector helper families that previously crossed function boundaries as unknowns.
- [x] Cover common window function return types.
- [ ] Cover Postgres and DuckDB functions that HogQL passes through or rewrites, especially casts, date/time functions, string functions, comparisons, and aggregations.
- [ ] Decide how UDFs should be typed:
  - [ ] typed manually
  - [ ] introspected from ClickHouse
  - [ ] intentionally left unknown with optimizer barriers

Acceptance criteria:

- Common product queries resolve without `UnknownType` at function boundaries except for documented cases.
- Aggregation and preaggregation transforms know the type of both state and final expressions.
- The catalog has tests that prevent accidental loss of signatures.

### 5. Casts, Accessors, And Syntax Nodes

Some AST nodes have incomplete or missing type resolution.
These are small but important because optimizers often reason around casts and accessors.

TODO:

- [x] Assign output types for `TypeCast`.
- [x] Assign output types for `TryCast`.
- [x] Represent the target type of casts using structured runtime type parsing, not only `type_name: str`.
- [x] Preserve dialect-specific cast syntax and supported target types.
- [x] Infer `ArrayAccess(Array[T], Int) -> T`.
- [x] Infer `ArraySlice(Array[T], ...) -> Array[T]`.
- [x] Infer `TupleAccess(Tuple[..., T_i, ...], i) -> T_i`.
- [x] Infer named tuple access when the tuple has field names.
- [x] Infer dictionary/map construction and access types.
- [x] Type common higher-order `Lambda` expressions with parameter and return types.
- [x] Make `LambdaArgumentType` resolve from surrounding higher-order function context instead of always `UnknownType`.
- [ ] Type `ColumnsExpr`/`AsteriskType` expansion boundaries more explicitly for projection optimizers.

Acceptance criteria:

- `CAST(x AS DateTime)` and `toDateTime(x)` agree on output type where they should.
- Cast typing remains backwards compatible with currently accepted ClickHouse, Postgres, and DuckDB casts.
- Array and tuple expressions preserve element types through access and slicing.
- Higher-order functions no longer erase argument and return types.

### 6. Subqueries, CTEs, And Set Queries

Subquery field types currently flow through `SelectQueryType.columns`, which is useful.
The missing part is type unification and lifecycle robustness.

TODO:

- [x] For `UNION`, `INTERSECT`, and `EXCEPT`, compute output column types across all branches rather than using the first branch as the effective type source.
- [x] Use `least_common_supertype` for set query columns.
- [ ] Validate column count and type compatibility in set queries when strict mode is enabled.
- [ ] Keep CTE column alias remapping from losing type information.
- [ ] Preserve types through recursive CTE base/recursive branches where supported.
- [ ] Decide how to type correlated subqueries.
- [ ] Make subquery alias types robust against transforms that reorder or prune select columns.
- [ ] Move optimizer metadata that is not a SQL type out of `Type` objects if needed.

Acceptance criteria:

- `SELECT 1 UNION ALL SELECT 2.0` has a predictable numeric output type.
- Projection pushdown can prune columns without leaving stale type metadata behind.
- CTE and subquery consumers do not need to mutate `SelectQueryType.columns` manually after structural rewrites.

### 7. Property Type Integration

Property type information is central to the optimization story because many HogQL queries are property-heavy.

TODO:

- [x] Separate physical storage type from semantic property type.
      For example, an event property may be physically stored as string JSON or a nullable materialized string column, while semantically known as numeric, datetime, boolean, or string.
- [x] Represent typed property access as a typed expression before printing.
- [x] Make materialized column availability part of planning metadata, not only printer behavior.
- [x] Decide when a typed property conversion can be skipped:
  - [x] materialized column is already numeric
  - [x] literal can be safely coerced instead of column-wrapped
  - [x] comparison can remain lexical by design
  - [x] conversion is required for correctness
  - [x] conversion would block an index
  - [x] conversion should move to the literal side
- [x] Use the property comparison planner to guard the existing ClickHouse materialized string-column range rewrite.
- [x] Add a type-aware rule for numeric property comparisons that can use minmax indexes when safe.
- [x] Add a type-aware rule for datetime property comparisons that can use minmax indexes when safe.
- [x] Add a typed physical materialized-column path for tests and future rollout decisions.
- [x] Preserve property group and dynamic materialized column behavior.
- [x] Preserve restricted-property behavior; materialized shortcuts must not bypass access control.
- [x] Make `PropertyType.resolve_constant_type()` more precise for JSON paths when metadata exists.
- [x] Make property type notices derive from the same facts the optimizer uses.

Acceptance criteria:

- Typed materialized property comparisons can use skip indexes where ClickHouse can support them.
- Property conversion wrappers are added for correctness, not because the type system lacks facts.
- Property access control continues to force safe JSON paths when required.

### 8. Type-Aware Optimizations

Once type facts are reliable, optimizer work can be incremental.

TODO:

- [x] Add an opt-in typed cast/nullability simplifier for conservative cases:
  - [x] remove redundant `toString(String)`
  - [x] remove redundant `toDate(Date)`
  - [x] remove redundant `toDateTime(DateTime)`
  - [x] remove redundant `toBool(Boolean)`
  - [x] remove redundant `assumeNotNull(non_nullable_expr)`
  - [x] collapse repeated compatible casts
  - [x] avoid removing casts that change timezone, precision, parsing semantics, or nullability
  - [x] fold safe constant conversions such as `accurateCast('42', 'Int64')`, `toFloat(1)`, `toBool('true')`, and `toUUID('...')`
- [x] Add literal-side conversion rewrites:
  - [x] compare typed column to typed literal without wrapping the column
  - [x] move datetime timezone conversion from column side to constant side where safe
  - [x] preserve existing `toTimeZone` range optimization behavior
- [ ] Add JSON/materialized property extraction rewrites:
  - [x] use materialized columns for typed JSON extraction where safe
  - [x] avoid decompressing full JSON blobs when a simple string property column is available
  - [ ] avoid `JSONExtractRaw` fallback when all required properties are materialized
- [ ] Add broader nullability simplification:
  - [x] avoid selected `ifNull(compare(...), default)` wrappers when both sides are non-nullable
  - [ ] preserve SQL three-valued logic where needed
  - [x] avoid redundant `ifNull`/`coalesce` around functions known to be non-nullable in the opt-in simplifier
  - [x] remove literal `NULL` fallbacks in opt-in `ifNull(...)`/`coalesce(...)` when the remaining expression is unchanged
- [ ] Add aggregate-state typing:
  - [x] allow state/merge transformations to know intermediate and final types for common typed state pairs
  - [ ] validate compatible state/merge pairs
  - [ ] improve preaggregation matching
- [ ] Add projection and lazy-join improvements:
  - [ ] use typed field lineage to identify fields needed only for casts or wrappers
  - [ ] avoid lazy joins when a typed virtual field can be satisfied by an events-table column
  - [ ] keep projection pushdown type-safe after pruning
- [ ] Add constant folding for typed literals where low-risk:
  - [x] simple arithmetic
  - [x] day/week date interval constants
  - [ ] month/year date interval constants
  - [x] safe casted constants and conversion calls
  - [x] exact-present literal JSON paths

Acceptance criteria:

- Optimizations are guarded by explicit type facts.
- Each optimization has tests showing both the optimized and non-optimized cases.
- Query semantics are unchanged unless the existing behavior was relying on a documented bug.

### 9. Type Diagnostics And Developer Tooling

TODO:

- [x] Add a helper that returns a typed AST plus a diagnostic report.
- [x] Count `UnknownType` occurrences by source:
  - [x] unknown field
  - [ ] unknown database field mapping
  - [x] missing function signature
  - [ ] signature mismatch
  - [ ] unsupported AST node
  - [ ] transform invalidated type
  - [ ] dialect-specific unknown
- [x] Add debug output that can explain the inferred type for each select expression.
- [ ] Add a query-corpus job that compiles representative HogQL queries and reports unknown-type rates.
- [ ] Add a way to compare inferred types with ClickHouse result metadata.
- [x] Add a way to compare inferred expression types with `toTypeName(...)` for selected expressions.
- [ ] Include timings so stronger typing does not silently slow query compilation.

Acceptance criteria:

- Engineers can see why a query expression became `UnknownType`.
- Signature coverage can be tracked over time.
- Type-system changes can be evaluated before enabling optimizer behavior.

### 10. Test Strategy

TODO:

- [x] Add unit tests for the type algebra.
- [x] Add resolver tests for:
  - [x] casts
  - [x] arrays
  - [x] tuples
  - [x] maps
  - [x] lambdas
  - [x] `if`, `multiIf`, `coalesce`
  - [x] aggregations
  - [x] set queries
  - [x] typed properties
- [ ] Add dialect compatibility tests for ClickHouse, Postgres, and DuckDB print targets.
- [ ] Add function catalog tests:
  - [ ] every public function has either a precise signature or an explicit unknown marker
  - [ ] aggregate functions declare return type behavior
  - [ ] state/merge pairs are coherent
  - [ ] parametric functions validate literal arguments
- [x] Add printer tests for the first optimized SQL shapes.
- [ ] Add ClickHouse integration tests for:
  - [ ] inferred type vs returned column type
  - [x] skip-index usage on typed materialized property comparisons
  - [ ] nullability behavior
  - [ ] timezone-sensitive datetime behavior
- [ ] Add Postgres/DuckDB smoke tests for type-aware printing where those dialects are supported.
- [ ] Add regression tests for current edge cases:
  - [x] `toDateTime(properties.dt_prop)` does not double-parse
  - [x] aliases rewritten by `PropertySwapper` do not keep stale return types
  - [x] typed string helpers such as `base64Encode(...)` avoid unnecessary comparison wrapping
  - [x] typed URL helpers such as `protocol(...)` avoid unnecessary comparison wrapping
  - [x] `assumeNotNull(unknown_function(...))` avoids unnecessary comparison wrapping
  - [x] property access control does not leak materialized property values in property comparison planning

Acceptance criteria:

- New type inference behavior is covered at the type level and at the emitted SQL level.
- At least one integration test proves an optimizer win against ClickHouse's planner, not just a string diff.

## Migration Plan

### Phase 0: Inventory And Shadow Diagnostics

TODO:

- [x] Add a non-invasive inventory helper/test for function signature coverage.
- [x] Add unknown-type diagnostics without changing query output.
- [ ] Build a small representative query corpus from existing tests and query runners.
- [ ] Record the baseline unknown-type rate by dialect.
- [ ] Record the baseline compile-time cost of resolution.
- [ ] Identify the top 20 unknown-producing functions in representative queries.
- [x] Record focused backwards-compatibility tests for representative typed query shapes that currently compile.

Phase 0 itself does not change optimizer behavior.

### Phase 1: Canonical Type Model

TODO:

- [x] Add the structured SQL runtime type model.
- [x] Add adapters from current `ConstantType` classes to the new model.
- [x] Add adapters from `DatabaseField` to the new model.
- [x] Add parser/adapter for ClickHouse type strings.
- [x] Add basic adapters for Postgres and DuckDB type metadata used by HogQL print targets.
- [x] Add equality, display, and debug serialization for types.
- [x] Keep current public resolver behavior compatible.

This phase should be mostly mechanical and heavily tested.

### Phase 2: Type Algebra And Function Signature Engine

TODO:

- [x] Implement initial nullability algebra.
- [x] Implement least-common-supertype.
- [x] Implement generic function inference.
- [ ] Migrate existing signatures into the new format.
- [x] Preserve the current simple signature format.
- [x] Add diagnostics for unknown or partially-known function calls.

This phase should still avoid broad optimizer rewrites.

### Phase 3: High-Value Function Coverage

TODO:

- [x] Type comparisons and logical functions.
- [x] Type casts and conversion functions.
- [x] Type `if`, `multiIf`, `coalesce`, `ifNull`, `nullIf`, `assumeNotNull`, and `toNullable`.
- [x] Type common aggregate functions.
- [x] Type common string helpers that unblock nullability-wrapper simplification in emitted SQL.
- [x] Type common URL helpers that unblock nullability-wrapper simplification in emitted SQL.
- [x] Type array element access and common higher-order array functions.
- [x] Type JSON extraction functions with parsed return type literals.
- [ ] Type core PostHog extension functions.

This phase should reduce `UnknownType` rates enough to make selective optimizations viable.

### Phase 4: Optimizer Consumers

TODO:

- [x] Add cast simplification behind an internal flag.
- [x] Use property comparison planning as the default guard for the existing materialized string-column range rewrite.
- [x] Add typed property comparison rewrites for physically typed materialized sources while keeping string-backed sources blocked.
- [x] Add conservative nullability wrapper simplification behind an internal flag.
- [x] Add first aggregate state typing support for common state/merge pairs.
- [ ] Extend aggregate state typing into preaggregation matching.
- [ ] Add projection/lazy table improvements only after field lineage is stable.
- [ ] Run query corpus comparisons before and after each rewrite.

Each optimization should have a narrow rollout path.
No optimization should become default unless existing query compatibility is preserved or the behavior change is explicitly accepted.

### Phase 5: Strict Mode And Cleanup

TODO:

- [ ] Add strict resolver mode for tests and selected internal queries.
- [ ] Turn missing function signatures into explicit catalog TODOs.
- [ ] Remove ad hoc type workarounds that are no longer needed.
- [ ] Remove stale-type alias workarounds only after transforms have a clear typed metadata lifecycle.
- [ ] Document how to add a function with a signature.
- [ ] Document how to add a database field with a precise runtime type.

Strict mode should come after coverage, not before.
It should not become the default behavior for user-authored HogQL unless there is a separate compatibility review.

## Open Questions

- [ ] Should expression types live on AST nodes, or should they live in a separate side table keyed by node identity?
- [ ] Should table/scope types and runtime expression types remain in one hierarchy?
- [ ] Should `UnknownType` be a single type or a family of unknowns with provenance?
- [ ] How exact do we need to be compared with each backend?
      Exactness helps optimization but may require frequent updates as ClickHouse, Postgres, and DuckDB behavior changes.
- [ ] How should dialect-specific types be modeled?
      HogQL targets ClickHouse most heavily, but the resolver and printers also support Postgres and DuckDB syntax paths.
- [ ] How much should property definitions be trusted?
      Property definitions can be missing, late, or wrong relative to actual ingested values.
- [ ] Should typed property conversion happen during resolution, a planning pass, or printing?
- [ ] How do we expose inferred types to users or debug tooling without making them a user-facing compatibility contract?
- [ ] Should UDFs be optimizer barriers until typed explicitly?
- [ ] Can ClickHouse function metadata be generated or validated from upstream docs/system tables, or should PostHog curate only the subset it exposes?

## Non-Goals

- Do not build a full SQL validator in the first pass.
- Do not reject all queries with unknown types.
- Do not make backwards-incompatible changes if we can avoid them.
- Do not stop existing HogQL/SQL from compiling by default.
- Do not enable strict mode for user-authored queries as part of the initial type-system work.
- Do not type every ClickHouse function before getting value from high-use functions.
- Do not replace the parser.
- Do not change frontend query schema generation.
- Do not make property definitions the only source of truth for runtime values.
- Do not make optimizer changes that depend on untrusted type facts without ClickHouse integration tests.

## Suggested PR Slices

- [x] Add function signature inventory and unknown-type diagnostics.
- [x] Add a structured SQL runtime type model and adapters from current `ConstantType`/`DatabaseField`.
- [x] Add cross-dialect adapters for ClickHouse, Postgres, and DuckDB type metadata.
- [x] Add type algebra for nullability, common supertypes, numeric promotion, arrays, and tuples.
- [x] Add generic function signature support while keeping existing simple signatures working.
- [x] Type casts, accessors, and higher-order function lambda arguments.
- [x] Type comparisons, logical functions, `if`, `multiIf`, and nullability functions.
- [x] Type common scalar aggregate functions.
- [x] Type property extraction and materialized property planning metadata.
- [x] Add cast simplification with tests and a guarded rollout.
- [x] Guard the existing materialized string range rewrite with property comparison planning.
- [x] Add typed materialized property comparison optimization for typed physical sources.
- [x] Add skip-index integration tests for typed materialized property comparisons.
- [x] Add a typed physical materialized-column test/storage hook.
- [x] Add safe exact-type `JSONExtract(...)` materialized-column rewrites.
- [ ] Add strict mode for internal tests after coverage is high.
- [ ] Remove obsolete ad hoc workarounds and document the new workflow.

## Success Metrics

- `UnknownType` rate across representative HogQL queries goes down.
- Percentage of function calls with precise return types goes up.
- Query compilation overhead remains acceptable.
- Existing representative HogQL queries continue compiling and printing by default.
- Redundant casts and nullability wrappers decrease in emitted ClickHouse SQL.
- Type-aware rewrites are valid for the active print target, including Postgres and DuckDB where applicable.
- Typed property comparisons use skip indexes in cases where ClickHouse supports them.
- Fewer production bugs require local workarounds for stale aliases or lost function return types.
- Adding a new HogQL function requires declaring type behavior or explicitly documenting why it is unknown.

## Immediate Next Step

Phase 0's inventory and diagnostic hook now exists in `posthog/hogql/type_diagnostics.py`, the guarded simplifier exists in `posthog/hogql/transforms/type_aware_simplification.py`, property comparison planning metadata exists in `posthog/hogql/property_planner.py`, the existing materialized string-column range rewrite now consumes that planner, physically typed materialized property columns can now use direct numeric/datetime range comparisons, and ClickHouse planner tests now prove those shapes use minmax skip indexes.
The diagnostics hook now also explains top-level select expression types and can build `toTypeName(...)` companion queries, and the guarded simplifier can fold simple numeric literal arithmetic, safe constant conversions, literal `NULL` fallbacks, and exact-present literal JSON paths.
The next concrete task should be deciding when production property materialization should create typed physical columns instead of string columns, plus expanding semantic-equivalence tests for remaining JSON/materialized extraction rewrites and recording a query-corpus unknown-type baseline before strict resolver mode.
