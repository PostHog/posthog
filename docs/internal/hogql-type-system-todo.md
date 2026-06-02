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

This branch adds the first implementation slice described by this TODO.
The original document intentionally scoped a multi-phase project; this status section records the pieces that are now real in code and the pieces that remain optimizer or catalog-expansion work.

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
- Added focused tests in `posthog/hogql/test/test_type_system.py` for runtime type parsing, database-field adapters, algebra, resolver inference, set-query unification, diagnostics, and catalog inventory.
- Added `docs/internal/hogql-type-system-now-possible.md`, which documents the new capabilities and the next optimizer hooks.

Still intentionally left as follow-up work:

- Full ClickHouse parity for every function signature and aggregate combinator.
- Full higher-order array parity beyond common lambda-first functions, especially lambda-aware array sorting and strict lambda arity/return validation.
- Full higher-order map parity, including lambda argument binding for `mapFilter(...)` and lambda-return typing for `mapApply(...)`.
- Property-definition planning metadata and materialized-property comparison rewrites.
- Broader rollout of cast simplification and nullability wrapper simplification beyond the internal opt-in flag.
- Strict resolver mode.
- Query-corpus unknown-type baselines and ClickHouse integration tests for planner/index wins.

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
- [ ] Add compatibility tests that compile representative existing HogQL queries before and after type-system changes.
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
It does not represent ClickHouse precision, scale, timezone, signedness, low cardinality, enum values, named tuple fields, aggregate states, nested nullability, or most parametric type details.
Map key/value types now have a compatibility representation, but the legacy `ConstantType` model still omits most ClickHouse-specific map metadata.

Database fields map to constant types through `DatabaseField.get_constant_type()`.
The mapping is also coarse.
For example:

- `IntegerDatabaseField` always becomes `IntegerType`, regardless of `UInt8`, `UInt64`, `Int32`, etc.
- `DecimalDatabaseField` becomes `DecimalType`, with no precision or scale.
- `DateTimeDatabaseField` becomes `DateTimeType`, with no `DateTime64` precision or timezone.
- `StringArrayDatabaseField` becomes `StringArrayType`, which is a `StringType` subclass rather than `ArrayType(StringType)`.
- `FloatArrayDatabaseField` currently resolves to `FloatType`, so the array dimension is lost.
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

The current function boundary behavior is the main limitation.
For a ClickHouse function call, the resolver:

1. Visits all arguments.
2. Resolves each argument to a `ConstantType`.
3. Looks up the function in `HOGQL_CLICKHOUSE_FUNCTIONS`.
4. Tries to find a matching signature.
5. Uses the signature return type if matched.
6. Falls back to `UnknownType` otherwise.
7. Applies a few hard-coded nullability rules for `concat`, `nullIf`, `toNullable`, `*OrNull`, and `assumeNotNull`.

The current signature matcher in `posthog/hogql/functions/core.py` is class-based.
`UnknownType` in a signature acts as a wildcard.
`StringLiteralType` can constrain constant string values.
There is no type variable, unification, generic return type, supertype computation, array element propagation, tuple field propagation, or type-level function.

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

Many high-value groups are not deeply typed:

- Logical functions in `mapping.py`, such as `equals`, `less`, `and`, `or`, `if`, and `multiIf`.
- Map constructors and simple accessors are typed, but higher-order map functions, bitmap helpers, and deeper tuple and array functions are still incomplete.
- URL helper coverage exists for common string, string-array, and `port(...)` return types, but deeper function families are still incomplete.
- Higher-order array functions, such as `arrayMap`, `arrayFilter`, `arrayFirst`, `arrayExists`, and `arrayReduce`.
- Most aggregate functions, including `count`, `sum`, `avg`, `min`, `max`, `uniq`, `quantile`, state functions, and merge functions.
- UDFs.

Aggregate functions are especially incomplete.
Many entries are marked `aggregate=True` but have no return type signature.
This blocks typed handling for preaggregation and aggregation state transformations.

### Property Typing

Property handling currently spans type resolution, transform-time metadata lookup, and printing:

- `FieldType.get_child()` returns `PropertyType` for `StringJSONDatabaseField`, `StringArrayDatabaseField`, and `StructDatabaseField`.
- `PropertyType.resolve_constant_type()` can traverse `StructDatabaseField` fields and propagate nested nullability.
- For JSON and array-ish properties, `PropertyType` mostly returns the underlying field's constant type with `nullable=True`.
- `build_property_swapper()` loads `PropertyDefinition` rows and materialized slot metadata.
- `PropertySwapper` wraps typed properties with conversion calls such as `toFloat(...)`, `toDateTime(...)`, and `toBool(...)`.
- The printer decides between JSON extraction, materialized columns, dynamic materialized slots, and property group columns.

This means property type knowledge is not one coherent type source.
Some type facts are in the schema.
Some are in property definitions.
Some are in materialized column metadata.
Some are only visible in printer logic.

The skip-index tests show why this matters.
A materialized property column can be directly usable by ClickHouse indexes.
If we add a conversion call around the column because the type system cannot prove the column and literal are already compatible, the query may execute correctly but lose index eligibility.

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

- [ ] Decide whether HogQL should keep using `ConstantType` classes as the canonical type model or introduce a separate `HogQLRuntimeType`/`SqlType` model.
- [ ] Represent ClickHouse primitive families with enough detail for optimization:
  - [ ] signed and unsigned integers with bit width
  - [ ] floats with width
  - [ ] decimals with precision and scale
  - [ ] strings, fixed strings, UUIDs, booleans, enums
  - [ ] dates and datetimes, including `DateTime64` precision and timezone
  - [ ] low cardinality wrappers
  - [ ] nullable wrappers
  - [ ] arrays with element types and element nullability
  - [ ] tuples with positional and optional named fields
  - [x] maps with key and value types
  - [ ] JSON/object-ish values
  - [ ] aggregate states
  - [ ] unknown types with a reason/provenance
- [ ] Represent a common cross-dialect type core plus dialect-specific extensions for ClickHouse, Postgres, and DuckDB.
- [ ] Define which types are portable and which are backend-specific.
- [ ] Define the relationship between storage fields (`DatabaseField`) and expression types.
- [ ] Make type conversion from ClickHouse type strings structured instead of lossy string cleanup.
- [ ] Add structured type adapters for Postgres and DuckDB metadata where HogQL prints or introspects those backends.
- [ ] Make type conversion from saved query metadata structured instead of routing through field class names.
- [ ] Decide whether `StringArrayType` should become `ArrayType(StringType)` or remain as a storage-specific alias.
- [ ] Fix `FloatArrayDatabaseField` so it does not lose the array dimension.
- [ ] Preserve struct/tuple field names where available.
- [ ] Represent property-definition type facts separately from physical storage type facts.

Acceptance criteria:

- A typed field can round-trip from database schema or ClickHouse `DESCRIBE` metadata into the type model without losing major type constructors.
- A typed field can carry enough dialect metadata to print correctly to ClickHouse, Postgres, and DuckDB.
- The type model can answer both "what SQL type does this expression return?" and "what physical column expression can the printer emit?"
- Existing field resolution behavior remains compatible with current query execution.

### 2. A Type Algebra

TODO:

- [ ] Add a `least_common_supertype(...)` operation for set queries, `if`, `multiIf`, `coalesce`, arrays, tuples, maps, arithmetic, and comparisons.
- [ ] Add nullability algebra:
  - [ ] nullable input propagation
  - [ ] functions that always return nullable
  - [ ] functions that never return nullable
  - [ ] functions where nullability depends on specific arguments
  - [ ] `assumeNotNull`, `toNullable`, `ifNull`, `coalesce`, `nullIf`, and `*OrNull` behavior
- [ ] Add numeric promotion rules matching each supported backend well enough for optimization.
- [ ] Add string/date/datetime coercion rules for PostHog-supported syntax by dialect.
- [ ] Add array element unification rules.
- [ ] Add tuple element and named-field lookup rules.
- [ ] Add map key/value access rules.
- [ ] Add comparison compatibility checks that can distinguish:
  - [ ] definitely compatible
  - [ ] compatible after cheap cast
  - [ ] compatible after expensive parse/cast
  - [ ] incompatible
  - [ ] unknown
- [ ] Keep ClickHouse-specific rules separate from Postgres/DuckDB rules.
- [ ] Add a way for an optimizer to ask whether a rewrite is valid for the current print target.

Acceptance criteria:

- The resolver can infer a type for `if(cond, a, b)` and `coalesce(a, b, c)` without enumerating every primitive combination.
- The resolver can infer a precise result type for common array and tuple expressions.
- Optimizers can ask whether a cast is redundant, required, unsafe, or expensive.

### 3. A Better Function Signature Engine

The current signature format is `list[tuple[tuple[AnyConstantType, ...], AnyConstantType]]`.
This works for simple functions but cannot express most ClickHouse type relationships.

TODO:

- [ ] Replace or extend signature tuples with a real signature DSL.
- [ ] Support type variables, such as `T -> T`, `Array[T] -> T`, `Array[T] -> Array[T]`, and `(T, T) -> Bool`.
- [ ] Support constrained type variables, such as numeric-only, orderable-only, string-like-only, date-like-only, and JSON-path-like.
- [ ] Support variadic signatures without exploding into many generated combinations.
- [ ] Support parametric functions and aggregate combinators.
- [ ] Support literal constraints beyond current `StringLiteralType`.
- [ ] Support return-type functions, for cases like:
  - [ ] `toTypeName(T) -> String`
  - [ ] `arrayElement(Array[T], Int) -> T`
  - [ ] `arrayMap(Lambda[A -> B], Array[A]) -> Array[B]`
  - [x] `JSONExtract(json, path..., 'Array(String)') -> Array[String]`
  - [ ] `if(Bool, T, U) -> least_common_supertype(T, U)`
  - [ ] `count(...) -> UInt64`
  - [ ] `sum(Int32) -> Int64` or the relevant ClickHouse promotion
  - [ ] `uniq(...) -> UInt64`
- [ ] Support overload ranking and deterministic error reporting.
- [ ] Distinguish "function is known but signature is incomplete" from "function is unsupported".
- [ ] Support dialect-specific function signatures, names, and return types where ClickHouse, Postgres, and DuckDB diverge.
- [ ] Add a strict mode that can fail on unknown function return types once coverage is high enough.

Acceptance criteria:

- Function type inference can represent "return the same type as the first argument" without copying dozens of primitive signatures.
- Higher-order array functions can bind lambda argument types from array element types.
- Missing signatures are measurable and visible in diagnostics.

### 4. Function Catalog Coverage

TODO:

- [ ] Add a signature coverage inventory command or test that reports:
  - [ ] total function metadata entries
  - [ ] entries by dialect/print target
  - [ ] entries with precise signatures
  - [ ] entries with wildcard signatures
  - [ ] entries with unknown return types
  - [ ] aggregate entries without return types
  - [ ] functions used in production query corpus but still unknown
- [ ] Prioritize catalog coverage by optimizer value and dialect reach, not by alphabetical order.
- [ ] Cover comparisons and logical functions first:
  - [ ] `equals`, `notEquals`, `less`, `greater`, `lessOrEquals`, `greaterOrEquals`
  - [ ] `in`, `notIn`
  - [ ] `and`, `or`, `xor`, `not`
  - [ ] `if`, `multiIf`
- [ ] Cover conversion and cast functions:
  - [ ] `toInt`, `toFloat`, `toDecimal`, `toBool`, `toString`, `toDate`, `toDateTime`, `toDateTime64`, `toUUID`
  - [ ] `accurateCast`, `accurateCastOrNull`, `CAST`, `TRY_CAST`
  - [ ] `reinterpretAs*`
  - [ ] `toNullable`, `assumeNotNull`, `ifNull`, `coalesce`, `nullIf`
- [ ] Cover property and JSON functions:
  - [x] `JSONExtract(...)` parsed return-type literals
  - [x] remaining `JSONExtract*` family-specific precision
  - [x] `JSON_VALUE`
  - [x] `JSONHas`, `JSONType`, `JSONLength`
  - [ ] PostHog property extraction wrappers if any are introduced
- [ ] Cover array functions:
  - [x] constructors and element access
  - [x] `arrayConcat`, `arraySlice`, `arrayJoin`, `arrayMap`, `arrayFilter`, `arrayExists`, `arrayAll`, `arrayFirst`, `arrayLast`
  - [x] `arrayReduce` with supported aggregate names
  - [x] `arrayZip`, `arrayFlatten`, `arrayDistinct`, `arraySort`, `arrayReverse`
  - [x] `arraySum`, `arrayAvg`, `arrayMin`, `arrayMax`
- [ ] Cover tuple and map functions:
  - [x] tuple construction and access
  - [ ] named tuple access
  - [x] `map`, `mapFromArrays`, `mapKeys`, `mapValues`, `mapContains`
  - [ ] `mapFilter`, `mapApply`
- [ ] Cover aggregate functions:
  - [x] `count`, `countIf`
  - [ ] `countState`, `countMerge`
  - [x] `sum`, `sumIf`
  - [ ] `sumState`, `sumMerge`
  - [x] `avg`, `avgIf`
  - [ ] `avgState`, `avgMerge`
  - [x] `min`, `max`, `any`, `argMin`, `argMax`
  - [x] `uniq*`
  - [x] scalar `quantile*` and `median*` variants
  - [ ] quantile/median state and merge variants
  - [ ] map/forEach aggregate variants
- [x] Cover high-use string and URL functions that unblock emitted-SQL nullability simplification.
- [ ] Cover high-use date functions after the above.
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

- [ ] Assign output types for `TypeCast`.
- [ ] Assign output types for `TryCast`.
- [ ] Represent the target type of casts using the canonical type model, not only `type_name: str`.
- [ ] Preserve dialect-specific cast syntax and supported target types.
- [ ] Infer `ArrayAccess(Array[T], Int) -> T`.
- [ ] Infer `ArraySlice(Array[T], ...) -> Array[T]`.
- [ ] Infer `TupleAccess(Tuple[..., T_i, ...], i) -> T_i`.
- [ ] Infer named tuple access when the tuple has field names.
- [ ] Infer dictionary/map construction and access types.
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

- [ ] For `UNION`, `INTERSECT`, and `EXCEPT`, compute output column types across all branches rather than using the first branch as the effective type source.
- [ ] Use `least_common_supertype` for set query columns.
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

- [ ] Separate physical storage type from semantic property type.
      For example, an event property may be physically stored as string JSON or a nullable materialized string column, while semantically known as numeric, datetime, boolean, or string.
- [ ] Represent typed property access as a typed expression before printing.
- [ ] Make materialized column availability part of planning metadata, not only printer behavior.
- [ ] Decide when a typed property conversion can be skipped:
  - [ ] materialized column is already numeric
  - [ ] literal can be safely coerced instead of column-wrapped
  - [ ] comparison can remain lexical by design
  - [ ] conversion is required for correctness
  - [ ] conversion would block an index and should move to the literal side
- [ ] Add a type-aware rule for numeric property comparisons that can use minmax indexes when safe.
- [ ] Add a type-aware rule for datetime property comparisons that can use minmax indexes when safe.
- [ ] Preserve property group and dynamic materialized column behavior.
- [ ] Preserve restricted-property behavior; materialized shortcuts must not bypass access control.
- [ ] Make `PropertyType.resolve_constant_type()` more precise for JSON paths when metadata exists.
- [ ] Make property type notices derive from the same facts the optimizer uses.

Acceptance criteria:

- Typed materialized property comparisons can use skip indexes where ClickHouse can support them.
- Property conversion wrappers are added for correctness, not because the type system lacks facts.
- Property access control continues to force safe JSON paths when required.

### 8. Type-Aware Optimizations

Once type facts are reliable, optimizer work can be incremental.

TODO:

- [ ] Add a typed cast simplifier:
  - [ ] remove redundant `toString(String)`
  - [ ] remove redundant `toDate(Date)`
  - [ ] remove redundant `toDateTime(DateTime)`
  - [ ] remove redundant `assumeNotNull(non_nullable_expr)`
  - [ ] collapse repeated compatible casts
  - [ ] avoid removing casts that change timezone, precision, parsing semantics, or nullability
- [ ] Add literal-side conversion rewrites:
  - [ ] compare typed column to typed literal without wrapping the column
  - [ ] move datetime timezone conversion from column side to constant side where safe
  - [ ] preserve existing `toTimeZone` range optimization behavior
- [ ] Add JSON/materialized property extraction rewrites:
  - [ ] use materialized columns for typed JSON extraction where safe
  - [ ] avoid decompressing full JSON blobs when a property column is available
  - [ ] avoid `JSONExtractRaw` fallback when all required properties are materialized
- [ ] Add nullability simplification:
  - [ ] avoid `ifNull(compare(...), default)` when both sides are non-nullable
  - [ ] preserve SQL three-valued logic where needed
  - [ ] avoid redundant `ifNull` around functions known to be non-nullable
- [ ] Add aggregate-state typing:
  - [ ] allow state/merge transformations to know intermediate and final types
  - [ ] validate compatible state/merge pairs
  - [ ] improve preaggregation matching
- [ ] Add projection and lazy-join improvements:
  - [ ] use typed field lineage to identify fields needed only for casts or wrappers
  - [ ] avoid lazy joins when a typed virtual field can be satisfied by an events-table column
  - [ ] keep projection pushdown type-safe after pruning
- [ ] Add constant folding for typed literals where low-risk:
  - [ ] simple arithmetic
  - [ ] date interval constants
  - [ ] casted constants
  - [ ] literal JSON paths

Acceptance criteria:

- Optimizations are guarded by explicit type facts.
- Each optimization has tests showing both the optimized and non-optimized cases.
- Query semantics are unchanged unless the existing behavior was relying on a documented bug.

### 9. Type Diagnostics And Developer Tooling

TODO:

- [ ] Add a helper that returns a typed AST plus a diagnostic report.
- [ ] Count `UnknownType` occurrences by source:
  - [ ] unknown field
  - [ ] unknown database field mapping
  - [ ] missing function signature
  - [ ] signature mismatch
  - [ ] unsupported AST node
  - [ ] transform invalidated type
  - [ ] dialect-specific unknown
- [ ] Add debug output that can explain the inferred type for each select expression.
- [ ] Add a query-corpus job that compiles representative HogQL queries and reports unknown-type rates.
- [ ] Add a way to compare inferred types with ClickHouse result metadata.
- [ ] Add a way to compare inferred expression types with `toTypeName(...)` for selected expressions.
- [ ] Include timings so stronger typing does not silently slow query compilation.

Acceptance criteria:

- Engineers can see why a query expression became `UnknownType`.
- Signature coverage can be tracked over time.
- Type-system changes can be evaluated before enabling optimizer behavior.

### 10. Test Strategy

TODO:

- [ ] Add unit tests for the type algebra.
- [ ] Add resolver tests for:
  - [ ] casts
  - [ ] arrays
  - [ ] tuples
  - [ ] maps
  - [ ] lambdas
  - [ ] `if`, `multiIf`, `coalesce`
  - [ ] aggregations
  - [ ] set queries
  - [ ] typed properties
- [ ] Add dialect compatibility tests for ClickHouse, Postgres, and DuckDB print targets.
- [ ] Add function catalog tests:
  - [ ] every public function has either a precise signature or an explicit unknown marker
  - [ ] aggregate functions declare return type behavior
  - [ ] state/merge pairs are coherent
  - [ ] parametric functions validate literal arguments
- [ ] Add printer tests for optimized SQL shape.
- [ ] Add ClickHouse integration tests for:
  - [ ] inferred type vs returned column type
  - [ ] skip-index usage on typed materialized property comparisons
  - [ ] nullability behavior
  - [ ] timezone-sensitive datetime behavior
- [ ] Add Postgres/DuckDB smoke tests for type-aware printing where those dialects are supported.
- [ ] Add regression tests for current edge cases:
  - [ ] `toDateTime(properties.dt_prop)` does not double-parse
  - [ ] aliases rewritten by `PropertySwapper` do not keep stale return types
  - [x] typed string helpers such as `base64Encode(...)` avoid unnecessary comparison wrapping
  - [x] typed URL helpers such as `protocol(...)` avoid unnecessary comparison wrapping
  - [ ] `assumeNotNull(unknown_function(...))` avoids unnecessary comparison wrapping
  - [ ] property access control does not leak materialized property values

Acceptance criteria:

- New type inference behavior is covered at the type level and at the emitted SQL level.
- At least one integration test proves an optimizer win against ClickHouse's planner, not just a string diff.

## Migration Plan

### Phase 0: Inventory And Shadow Diagnostics

TODO:

- [ ] Add a non-invasive inventory command or test for function signature coverage.
- [ ] Add unknown-type diagnostics without changing query output.
- [ ] Build a small representative query corpus from existing tests and query runners.
- [ ] Record the baseline unknown-type rate by dialect.
- [ ] Record the baseline compile-time cost of resolution.
- [ ] Identify the top 20 unknown-producing functions in representative queries.
- [ ] Record a backwards-compatibility baseline of representative queries that currently compile.

Do not change optimizer behavior in this phase.

### Phase 1: Canonical Type Model

TODO:

- [ ] Add the structured SQL runtime type model.
- [ ] Add adapters from current `ConstantType` classes to the new model, or evolve `ConstantType` directly.
- [ ] Add adapters from `DatabaseField` to the new model.
- [ ] Add parser/adapter for ClickHouse type strings used in warehouse and saved query metadata.
- [ ] Add adapters for Postgres and DuckDB type metadata used by HogQL print targets.
- [ ] Add equality, display, and debug serialization for types.
- [ ] Keep current public resolver behavior compatible.

This phase should be mostly mechanical and heavily tested.

### Phase 2: Type Algebra And Function Signature Engine

TODO:

- [ ] Implement nullability algebra.
- [ ] Implement least-common-supertype.
- [ ] Implement generic function signatures.
- [ ] Migrate existing signatures into the new format.
- [ ] Preserve the current simple signature format temporarily if needed.
- [ ] Add diagnostics for unknown or partially-known function calls.

This phase should still avoid broad optimizer rewrites.

### Phase 3: High-Value Function Coverage

TODO:

- [ ] Type comparisons and logical functions.
- [ ] Type casts and conversion functions.
- [ ] Type `if`, `multiIf`, `coalesce`, `ifNull`, `nullIf`, `assumeNotNull`, and `toNullable`.
- [ ] Type common aggregate functions.
- [x] Type common string helpers that unblock nullability-wrapper simplification in emitted SQL.
- [x] Type common URL helpers that unblock nullability-wrapper simplification in emitted SQL.
- [x] Type array element access and common higher-order array functions.
- [x] Type JSON extraction functions with parsed return type literals.
- [ ] Type core PostHog extension functions.

This phase should reduce `UnknownType` rates enough to make selective optimizations viable.

### Phase 4: Optimizer Consumers

TODO:

- [ ] Add cast simplification behind a modifier or internal flag.
- [ ] Add typed property comparison rewrites behind a modifier or internal flag.
- [ ] Add nullability wrapper simplification behind a modifier or internal flag.
- [ ] Add aggregate state typing support for preaggregation work.
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

1. Add function signature inventory and unknown-type diagnostics.
2. Add a structured SQL runtime type model and adapters from current `ConstantType`/`DatabaseField`.
3. Add cross-dialect adapters for ClickHouse, Postgres, and DuckDB type metadata.
4. Add type algebra for nullability, common supertypes, numeric promotion, arrays, and tuples.
5. Add generic function signature support while keeping existing simple signatures working.
6. Type casts, accessors, and higher-order function lambda arguments.
7. Type comparisons, logical functions, `if`, `multiIf`, and nullability functions.
8. Type common aggregate and aggregate-state functions.
9. Type property extraction and materialized property planning metadata.
10. Add cast simplification with tests and a guarded rollout.
11. Add typed materialized property comparison optimization with skip-index integration tests.
12. Add strict mode for internal tests after coverage is high.
13. Remove obsolete ad hoc workarounds and document the new workflow.

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

Phase 0's inventory and diagnostic hook now exists in `posthog/hogql/type_diagnostics.py`, and the first guarded simplifier exists in `posthog/hogql/transforms/type_aware_simplification.py`.
The next concrete task should be property-planning metadata for materialized property comparisons, followed by ClickHouse planner tests before enabling any property/index rewrite broadly.
