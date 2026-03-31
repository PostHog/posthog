# Holdout groups

## What they are

Holdout groups are stable sets of users intentionally excluded from experiment variations to serve as a baseline control group. When a user falls into a holdout group, they are excluded from the experiment entirely—they don't see any experiment variation, including the control. This allows direct comparison between users who experience the experiment and those who experience the product completely unchanged.

Key characteristics:

- **Stable across experiments**: The same users are consistently excluded, enabling cross-experiment analysis
- **Hash-based assignment**: Uses consistent hashing on the bucketing identifier (distinct_id or group key) so assignment is deterministic
- **Pre-condition evaluation**: Evaluated _before_ regular feature flag conditions, acting as a gate
- **Immutable experiment linkage**: Once an experiment starts, its associated holdout cannot be changed (the holdout definition itself may still be edited)

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

When an experiment has a holdout, the holdout configuration is copied into the experiment's feature flag `filters` as `holdout`:

```json
{
  "groups": [...],
  "holdout": {
    "id": 42,
    "exclusion_percentage": 10
  }
}
```

- `id` — the `ExperimentHoldout` primary key
- `exclusion_percentage` — what percentage of users to exclude (0–100)

The variant name `holdout-{id}` is derived at evaluation time, not stored in the payload.

### Data type used

Rust:

```rust
pub struct Holdout {
    pub id: i64,
    pub exclusion_percentage: f64,
}
```

## Key files

| Component         | Path                                            |
| ----------------- | ----------------------------------------------- |
| Model             | `posthog/models/experiment.py`                  |
| Serializer        | `ee/clickhouse/views/experiment_holdouts.py`    |
| Rust evaluation   | `rust/feature-flags/src/flags/flag_matching.rs` |
| Rust type         | `rust/feature-flags/src/flags/flag_models.rs`   |
| Python evaluation | `posthog/models/feature_flag/flag_matching.py`  |
| Frontend types    | `frontend/src/types.ts`                         |
