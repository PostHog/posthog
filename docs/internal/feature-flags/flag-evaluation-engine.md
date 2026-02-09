# Flag evaluation engine

The Rust feature flags service evaluates flags using a deterministic, hash-based algorithm. This document covers the full evaluation pipeline: dependency resolution, condition matching, rollout hashing, variant selection, super groups, holdout groups, and experience continuity.

## Architecture overview

```text
┌─────────────────────────────────────────────────────────────────┐
│                     evaluate_all_feature_flags                  │
├─────────────────────────────────────────────────────────────────┤
│  1. Build dependency graph (DAG) from all flags                 │
│  2. Filter graph to requested flag_keys (+ transitive deps)    │
│  3. Process experience continuity (hash key overrides)          │
│  4. Fetch person/group properties and cohort memberships        │
│  5. Evaluate flags in topological order (parallel per stage)    │
└─────────────────────────────────────────────────────────────────┘
         │              │                │
         ▼              ▼                ▼
   ┌──────────┐  ┌───────────┐   ┌────────────┐
   │ SHA1     │  │ Property  │   │ Dependency │
   │ hashing  │  │ matching  │   │ graph      │
   │ (rollout │  │ (23       │   │ (petgraph  │
   │  + vars) │  │ operators)│   │  DAG)      │
   └──────────┘  └───────────┘   └────────────┘
```

## Core data model

### FeatureFlag

```rust
pub struct FeatureFlag {
    pub id: FeatureFlagId,                          // i32
    pub team_id: i32,
    pub name: Option<String>,
    pub key: String,
    pub filters: FlagFilters,
    pub deleted: bool,
    pub active: bool,
    pub ensure_experience_continuity: Option<bool>,
    pub version: Option<i32>,
    pub evaluation_runtime: Option<String>,         // "server", "client", or "all"
    pub evaluation_tags: Option<Vec<String>>,
    pub bucketing_identifier: Option<String>,        // "distinct_id" or "device_id"
}
```

### FlagFilters

```rust
pub struct FlagFilters {
    pub groups: Vec<FlagPropertyGroup>,                  // condition sets (OR'd together)
    pub multivariate: Option<MultivariateFlagOptions>,   // variant definitions
    pub aggregation_group_type_index: Option<i32>,       // None=person, 0=project, 1=org, etc.
    pub payloads: Option<serde_json::Value>,             // variant key -> payload map
    pub super_groups: Option<Vec<FlagPropertyGroup>>,    // early access feature gate
    pub holdout_groups: Option<Vec<FlagPropertyGroup>>,  // holdout/control conditions
}
```

### FlagPropertyGroup (a single condition set)

```rust
pub struct FlagPropertyGroup {
    pub properties: Option<Vec<PropertyFilter>>,    // filters (AND'd together)
    pub rollout_percentage: Option<f64>,             // 0.0-100.0, defaults to 100.0
    pub variant: Option<String>,                    // variant override for this condition
}
```

### PropertyFilter

```rust
pub struct PropertyFilter {
    pub key: String,
    pub value: Option<serde_json::Value>,
    pub operator: Option<OperatorType>,
    pub prop_type: PropertyType,                    // Person, Group, Cohort, or Flag
    pub negation: Option<bool>,
    pub group_type_index: Option<i32>,
}
```

## Per-flag evaluation flow

The `get_match` function in `rust/feature-flags/src/flags/flag_matching.rs` evaluates a single flag:

```text
┌────────────────────────────┐
│  Flag active?              │──── No ──▶ false (FlagDisabled)
└────────────────────────────┘
               │ Yes
               ▼
┌────────────────────────────┐
│  Resolve hashed_identifier │
│  (group key, device_id,   │
│   hash override, or       │
│   distinct_id)             │
└────────────────────────────┘
               │
               ▼
┌────────────────────────────┐
│  Group flag with empty     │──── Yes ──▶ false (NoGroupType)
│  group key?                │
└────────────────────────────┘
               │ No
               ▼
┌────────────────────────────┐
│  Evaluate super_groups     │──── Match ──▶ return result (SuperConditionValue)
│  (early access gate)       │
└────────────────────────────┘
               │ No match / not applicable
               ▼
┌────────────────────────────┐
│  Evaluate holdout_groups   │──── In holdout ──▶ true + holdout variant
│  (holdout check)           │                    (HoldoutConditionValue)
└────────────────────────────┘
               │ Not in holdout
               ▼
┌────────────────────────────┐
│  Iterate condition groups  │
│  (OR logic - first match   │
│   wins)                    │
│                            │
│  For each group:           │
│    1. Check flag-value     │
│       filters              │
│    2. Check property       │
│       filters (AND logic)  │
│    3. Check cohort filters │
│    4. Rollout hash check   │
└────────────────────────────┘
               │
       ┌───────┴────────┐
       ▼                 ▼
   Matched            No match
   ┌──────────┐       ┌──────────┐
   │ Resolve  │       │ Return   │
   │ variant  │       │ false    │
   │ + payload│       │ (highest │
   └──────────┘       │  reason) │
                      └──────────┘
```

## Hash-based rollout

Flag rollout uses SHA1 hashing to deterministically assign users to buckets.

### Hash calculation

```rust
// rust/feature-flags/src/flags/flag_matching_utils.rs
pub fn calculate_hash(prefix: &str, hashed_identifier: &str, salt: &str) -> f64 {
    let hash_key = format!("{prefix}{hashed_identifier}{salt}");
    let hash_value = Sha1::digest(hash_key.as_bytes());
    let hash_val: u64 = u64::from_be_bytes(hash_value[..8].try_into().unwrap()) >> 4;
    hash_val as f64 / LONG_SCALE as f64  // LONG_SCALE = 0xfffffffffffffff
}
```

The hash produces a deterministic float in `[0, 1)` from `SHA1("{flag_key}.{identifier}{salt}")`.

### Rollout check

```text
hash = SHA1("{flag_key}.{identifier}") → float [0, 1)

if hash <= rollout_percentage / 100.0 → user is IN the rollout
if hash >  rollout_percentage / 100.0 → user is OUT (OutOfRolloutBound)
```

A 100% rollout skips the hash calculation entirely.

### Identifier resolution priority

The identifier used for hashing depends on the flag configuration:

| Flag type   | Bucketing     | Identifier (in priority order)                                     |
| ----------- | ------------- | ------------------------------------------------------------------ |
| Group flag  | N/A           | Group key from `groups` map                                        |
| Person flag | `device_id`   | `$device_id` from request, fallback to `distinct_id`               |
| Person flag | `distinct_id` | DB hash_key_override > request `$anon_distinct_id` > `distinct_id` |

## Condition matching

Each flag has one or more condition groups (OR'd). Within each group, property filters are AND'd.

### Condition evaluation order

1. **Flag-value filters** (`prop_type: Flag`): Check dependent flag results first. If any fail, the condition fails immediately.
2. **Non-cohort property filters** (`prop_type: Person` or `Group`): Checked next (cheaper than cohort lookups).
3. **Cohort filters** (`prop_type: Cohort`): Checked last (may require DB lookups for static cohorts or recursive property evaluation for dynamic cohorts).
4. **Rollout hash check**: Only performed if all filters pass.

### Property operators

Defined in `rust/feature-flags/src/properties/property_matching.rs`. The service supports 23 operators:

| Category     | Operators                                                                       | Behavior                                                                                                         |
| ------------ | ------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------- |
| Existence    | `is_set`, `is_not_set`                                                          | Key presence check in property map                                                                               |
| Equality     | `exact`, `is_not`                                                               | Case-insensitive comparison. Arrays checked with contains. Boolean normalization for `"true"`/`"false"` strings. |
| String       | `icontains`, `not_icontains`                                                    | ASCII-case-insensitive substring match                                                                           |
| Regex        | `regex`, `not_regex`                                                            | `fancy_regex` with 10,000 step backtrack limit (ReDoS protection)                                                |
| Numeric      | `gt`, `gte`, `lt`, `lte`                                                        | Parse both sides as `f64`                                                                                        |
| Semver       | `semver_gt`, `semver_gte`, `semver_lt`, `semver_lte`, `semver_eq`, `semver_neq` | Direct `Version` comparison                                                                                      |
| Semver range | `semver_tilde`, `semver_caret`, `semver_wildcard`                               | `VersionReq` parsing (`~1.2.3`, `^1.2.3`, `1.2.x`)                                                               |
| Date         | `is_date_exact`, `is_date_after`, `is_date_before`                              | Supports relative dates, ISO 8601, Unix timestamps                                                               |
| Cohort       | `in`, `not_in`                                                                  | Handled by cohort matching, not property matching                                                                |
| Flag         | `flag_evaluates_to`                                                             | Handled by flag dependency matching                                                                              |

## Multivariate flags (variant selection)

Multivariate flags define multiple variants with rollout percentages that must sum to 100%.

### Variant hash

Variant selection uses a **separate hash** from rollout, with salt `"variant"`:

```text
hash = SHA1("{flag_key}.{identifier}variant") → float [0, 1)
```

Variants are walked in order with cumulative percentages:

```text
Variants: [A: 33%, B: 33%, C: 34%]

hash < 0.33        → variant A
hash < 0.66        → variant B
hash < 1.00        → variant C
```

### Variant overrides

A condition group can specify a `variant` field that overrides the computed variant when that condition matches. This allows targeting specific user segments with specific variants.

### Payloads

Each variant (or `"true"` for boolean flags) can have a JSON payload stored in `filters.payloads`. The payload is included in the evaluation result.

## Super groups (early access features)

Super groups act as a gate for early access enrollment. Defined in `filters.super_groups`.

### Evaluation

1. Only the first super group is evaluated
2. Checks if the person has any property mentioned in the super condition (typically `$feature_enrollment/{flag_key}`)
3. If the person has the property, the super condition is evaluated and its result is returned immediately (reason: `SuperConditionValue`)
4. If the person does not have the property, evaluation falls through to normal conditions

Super groups take the highest priority in match reasons (score: 6).

## Holdout groups

Holdout groups exclude users from experiments to serve as a baseline. Defined in `filters.holdout_groups`.

### Evaluation

1. Only the first holdout group is evaluated
2. Uses a **separate hash prefix** `"holdout-"` (not the flag key), so holdout assignment is independent of individual flag rollout
3. If the user's hash falls within the holdout percentage, they are in the holdout and the flag returns `true` with a holdout variant (default: `"holdout"`)
4. If the user is outside the holdout, normal condition evaluation proceeds

Holdout evaluation happens after super groups but before normal conditions.

## Flag dependencies

Flags can depend on other flags via `PropertyFilter` with `prop_type: Flag` and `operator: flag_evaluates_to`.

### Dependency graph

The service builds a directed acyclic graph (DAG) using `petgraph` to determine evaluation order:

1. Extract dependencies from all flag property filters
2. Build a directed graph (edges from dependent -> dependency)
3. Detect and remove cycles (cycle-starting nodes and all their dependents are removed)
4. Track missing dependencies (flags depending on non-existent flags)
5. Compute topological evaluation stages using Kahn's algorithm

### Evaluation stages

Flags are evaluated in batched stages. Each stage contains flags whose dependencies are all resolved:

```text
Stage 0: [flag_A, flag_B]       ← no dependencies
Stage 1: [flag_C, flag_D]       ← depend on flags in stage 0
Stage 2: [flag_E]               ← depends on flags in stage 1
```

Flags within a stage are evaluated in parallel using **Rayon** (`par_iter`).

### Flag value matching

```rust
// How flag dependency filters are resolved:
match filter.value {
    true  => flag_value != Boolean(false)   // "truthy" -- any non-false value
    false => flag_value == Boolean(false)    // "falsy"
    String(s) => flag_value == String(s)    // exact variant match
}
```

Evaluated results are cached in `FlagEvaluationState.flag_evaluation_results` for subsequent dependent flags. Flags with missing or cyclic dependencies evaluate to `false` with reason `MissingDependency`.

### Partial flag evaluation

When `flag_keys` is provided in the request, the dependency graph is filtered to include only the requested flags and their transitive dependencies. This avoids evaluating unrelated flags.

## Experience continuity

Experience continuity ensures users see the same flag value even when their `distinct_id` changes (e.g., anonymous user logs in). See [experience-continuity.md](experience-continuity.md) for the full design.

### When it applies

A flag uses experience continuity when ALL of:

- `ensure_experience_continuity` is true
- The flag is person-based (no group aggregation)
- The flag uses `distinct_id` bucketing (not `device_id`)

### Optimization

Flags at 100% rollout with no hash-dependent variants skip the DB lookup entirely (`OPTIMIZE_EXPERIENCE_CONTINUITY_LOOKUPS=true`). Only flags with partial rollout or multiple variants need the stored hash key.

### Hash key override flow

1. If `$anon_distinct_id` is provided in the request:
   - Check if all active EEC flags already have overrides for this person
   - Write missing overrides in a transaction with `ON CONFLICT DO NOTHING`
   - Read back all overrides (from writer to avoid replication lag)
2. If no `$anon_distinct_id`: read existing overrides from the reader DB

## Cohort matching

### Dynamic cohorts

Dynamic cohorts define membership via property filters. The service resolves them by:

1. Fetching cohort definitions (from moka in-memory cache, backed by PostgreSQL)
2. Building a dependency graph for nested cohorts (cohorts can reference other cohorts)
3. Evaluating cohort property filters against person/group properties

### Static cohorts

Static cohorts have pre-computed membership lists in the `posthog_cohortpeople` table. The service uses a batched query with `unnest` to check membership for multiple cohorts at once:

```sql
WITH cohort_membership AS (
    SELECT c.cohort_id,
           CASE WHEN pc.cohort_id IS NOT NULL THEN true ELSE false END AS is_member
    FROM unnest($1::integer[]) AS c(cohort_id)
    LEFT JOIN posthog_cohortpeople AS pc
      ON pc.person_id = $2 AND pc.cohort_id = c.cohort_id
)
SELECT cohort_id, is_member FROM cohort_membership
```

### Cohort caching

Cohort definitions are cached in-memory using `moka`:

| Parameter       | Default        | Purpose                                |
| --------------- | -------------- | -------------------------------------- |
| Capacity        | 256 MB         | Memory-based eviction                  |
| TTL             | 5 minutes      | Time-based expiration                  |
| Thundering herd | `try_get_with` | Per-key coalescing                     |
| Error caching   | Disabled       | Failed fetches are retried immediately |

## Match reasons

Each evaluation result includes a reason explaining why the flag matched or didn't match:

| Reason                  | Score | Meaning                                           |
| ----------------------- | ----- | ------------------------------------------------- |
| `SuperConditionValue`   | 6     | Matched via super group (early access)            |
| `HoldoutConditionValue` | 5     | In holdout group                                  |
| `ConditionMatch`        | 4     | Matched a condition group + rollout               |
| `NoGroupType`           | 3     | Group flag but no group key provided              |
| `OutOfRolloutBound`     | 2     | Conditions matched but outside rollout percentage |
| `NoConditionMatch`      | 1     | No condition group matched                        |
| `FlagDisabled`          | 0     | Flag is not active                                |
| `MissingDependency`     | -1    | A required dependency flag was not found          |

When multiple conditions are checked, the highest-priority reason is returned even when no condition ultimately matches (e.g., `OutOfRolloutBound` is more informative than `NoConditionMatch`).

## Per-request state

The `FlagEvaluationState` struct caches all data needed for a single request, avoiding redundant DB lookups when evaluating multiple flags:

```rust
pub struct FlagEvaluationState {
    person_id: Option<PersonId>,
    person_properties: Option<HashMap<String, Value>>,
    group_properties: HashMap<GroupTypeIndex, HashMap<String, Value>>,
    cohorts: Option<Vec<Cohort>>,
    static_cohort_matches: Option<HashMap<CohortId, bool>>,
    flag_evaluation_results: HashMap<FeatureFlagId, FlagValue>,
}
```

Property overrides from the request body are merged on top of DB-fetched properties. Request overrides take precedence.

## Data fetching strategy

The evaluation engine follows a lazy-but-batched approach:

1. **Flag definitions**: Fetched once per request from HyperCache (Redis -> S3 -> PostgreSQL)
2. **Group type mappings**: Fetched once per request if any flag uses groups
3. **Person properties**: Fetched once per request from PostgreSQL, merged with request overrides
4. **Group properties**: Fetched once per request from PostgreSQL, merged with request overrides
5. **Cohort definitions**: Fetched from moka cache (backed by PostgreSQL)
6. **Static cohort memberships**: Fetched once per request via batched query
7. **Hash key overrides**: Fetched once per request if any flag uses experience continuity
8. **Flag evaluation results**: Accumulated during evaluation, used for flag-on-flag dependencies

## Related files

| File                                                         | Purpose                                         |
| ------------------------------------------------------------ | ----------------------------------------------- |
| `rust/feature-flags/src/handler/evaluation.rs`               | Entry point: creates matcher and calls evaluate |
| `rust/feature-flags/src/flags/flag_matching.rs`              | Core matching engine: `FeatureFlagMatcher`      |
| `rust/feature-flags/src/flags/flag_matching_utils.rs`        | Hash calculation, property fetching, DB queries |
| `rust/feature-flags/src/properties/property_matching.rs`     | Property filter operator implementations        |
| `rust/feature-flags/src/flags/flag_models.rs`                | Data models                                     |
| `rust/feature-flags/src/flags/flag_operations.rs`            | Flag helper methods, `DependencyProvider` trait |
| `rust/feature-flags/src/flags/flag_match_reason.rs`          | Match reason enum with priority ordering        |
| `rust/feature-flags/src/utils/graph_utils.rs`                | Dependency graph using petgraph                 |
| `rust/feature-flags/src/cohorts/cohort_cache_manager.rs`     | Moka-backed cohort cache                        |
| `rust/feature-flags/src/flags/test_flag_matching.rs`         | Unit tests for flag matching                    |
| `rust/feature-flags/tests/test_flag_matching_consistency.rs` | Cross-language consistency tests                |

## See also

- [Rust service overview](rust-service-overview.md) - Service architecture, endpoints, configuration
- [Experience continuity](experience-continuity.md) - Hash key overrides for consistent flag values
- [Database interaction patterns](database-interaction-patterns.md) - PostgreSQL connection pooling and query routing
- [HyperCache system](hypercache-system.md) - Multi-tier caching
