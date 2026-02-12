# Holdout groups

## What they are

Holdout groups are stable sets of users intentionally excluded from experiment variations to serve as a baseline control group. When a user falls into a holdout group, they are excluded from the experiment entirely—they don't see any experiment variation, including the control. This allows direct comparison between users who experience the experiment and those who experience the product completely unchanged.

Key characteristics:

- **Stable across experiments**: The same users are consistently excluded, enabling cross-experiment analysis
- **Hash-based assignment**: Uses consistent hashing on `distinct_id` so assignment is deterministic
- **Pre-condition evaluation**: Evaluated _before_ regular feature flag conditions, acting as a gate
- **Immutable after launch**: Cannot be modified once an experiment starts

## What they're used for

Holdout groups solve the problem of measuring the cumulative impact of running many experiments. Individual A/B tests measure incremental changes, but holdout groups let you answer: "What's the overall impact of all our experiments compared to users who saw none of them?"

Example use case: An e-commerce site runs dozens of checkout optimization experiments. A 5% holdout group never sees any of these experiments, allowing the team to measure whether the combined effect of all optimizations actually improves conversion compared to the original experience.

## How they are stored

### Database model

The `ExperimentHoldout` model stores the holdout definition:

```python
class ExperimentHoldout(models.Model):
    name = models.CharField(max_length=400)
    description = models.CharField(max_length=400, null=True, blank=True)
    team = models.ForeignKey("Team", on_delete=models.CASCADE)
    filters = models.JSONField(default=list)  # List of filter groups
    created_by = models.ForeignKey("User", on_delete=models.SET_NULL, null=True)
```

The `Experiment` model links to a holdout via foreign key:

```python
holdout = models.ForeignKey("ExperimentHoldout", on_delete=models.SET_NULL, null=True)
```

### Feature flag integration

When an experiment has a holdout, the holdout configuration is copied into the experiment's feature flag `filters` as `holdout_groups`:

```json
{
  "filters": {
    "groups": [...],
    "holdout_groups": [
      {
        "variant": "holdout-42",
        "properties": [],
        "rollout_percentage": 10
      }
    ]
  }
}
```

### Data type used

Holdout groups use `FlagPropertyGroup` (in Rust) / `FeatureFlagGroupType` (in TypeScript):

```rust
pub struct FlagPropertyGroup {
    pub properties: Option<Vec<PropertyFilter>>,
    pub rollout_percentage: Option<f64>,
    pub variant: Option<String>,
}
```

## Why this causes confusion

### The type doesn't match the data

The `FlagPropertyGroup` type was designed for regular feature flag conditions where you might target users based on properties (e.g., "country = US") with a rollout percentage. Holdout groups reuse this type but only use two of its fields:

| Field                | Regular conditions  | Holdout groups               |
| -------------------- | ------------------- | ---------------------------- |
| `properties`         | Array of filters    | Always empty (not supported) |
| `rollout_percentage` | % of matching users | % of all users to exclude    |
| `variant`            | Not used            | Set to `holdout-{id}`        |

This creates several problems:

1. **The `properties` field is misleading**: The type suggests you could filter holdouts by user properties, but the evaluation code explicitly ignores properties:

   ```rust
   // From flag_matching.rs
   if condition.properties.as_ref().is_some_and(|p| !p.is_empty()) {
       return Ok((false, None, FeatureFlagMatchReason::NoConditionMatch));
   }
   ```

2. **The `variant` field has different semantics**: In regular conditions, variants relate to multivariate flags. In holdout groups, variant is just an identifier (`holdout-{holdout_id}`) used to mark which holdout matched.

3. **`rollout_percentage` means the opposite**: In regular conditions, it's "what percentage should get this flag." In holdout groups, it's "what percentage should be _excluded_ from the experiment."

### Why it was done this way

Holdout groups were added later, and reusing `FlagPropertyGroup` avoided:

- Creating new database columns
- Modifying the feature flag evaluation pipeline significantly
- Adding new types to the Rust/Python/TypeScript codebases

The trade-off was clarity for expediency.

### A clearer alternative would be

A dedicated type that reflects what holdout groups actually support:

```typescript
interface HoldoutCondition {
  holdoutId: number
  exclusionPercentage: number // 0-100, what % to exclude
}
```

## Key files

| Component         | Path                                            |
| ----------------- | ----------------------------------------------- |
| Model             | `posthog/models/experiment.py`                  |
| Serializer        | `ee/clickhouse/views/experiment_holdouts.py`    |
| Rust evaluation   | `rust/feature-flags/src/flags/flag_matching.rs` |
| Python evaluation | `posthog/models/feature_flag/flag_matching.py`  |
| Frontend types    | `frontend/src/types.ts`                         |
