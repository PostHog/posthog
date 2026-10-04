# Holdout groups

## What they are

Holdout groups are stable sets of users intentionally excluded from experiment variations to serve as a baseline control group. When a user falls into a holdout group, they are excluded from the experiment entirely—they don't see any experiment variation, including the control. This allows direct comparison between users who experience the experiment and those who experience the product completely unchanged.

Key characteristics:

- **Stable across experiments**: The same users are consistently excluded, enabling cross-experiment analysis
- **Hash-based assignment**: Uses consistent hashing on the bucketing identifier (distinct_id or group key) so assignment is deterministic
- **Pre-condition evaluation**: Evaluated _before_ regular feature flag conditions, acting as a gate
- **Immutable experiment linkage**: Once an experiment starts, its associated holdout cannot be changed (the holdout definition itself may still be edited)
- **Permanent, not time-boxed**: Membership does not rotate. A holdout applies until it is detached from the experiment, so rotating the held-out users means creating a new holdout for the next experiment

## What they're used for

Holdout groups solve the problem of measuring the cumulative impact of running many experiments. Individual A/B tests measure incremental changes, but holdout groups let you answer: "What's the overall impact of all our experiments compared to users who saw none of them?"

Example use case: An e-commerce site runs dozens of checkout optimization experiments. A 5% holdout group never sees any of these experiments, allowing the team to measure whether the combined effect of all optimizations actually improves conversion compared to the original experience.

## What happens when a winner ships

A holdout keeps excluding its users after the experiment ends and the winning variant rolls out to everyone.
That is the point of a holdout: the shipped feature is measured against a population that never saw it.

`ExperimentService.ship_variant` rewrites the flag's `multivariate` and `groups` and carries the `holdout` object over unchanged.
The Rust evaluator resolves the holdout before the release conditions, so the catch-all condition that `release_to_everyone=True` prepends cannot pull a held-out user into the shipped variant.
Held-out users keep matching the flag with the `holdout-{id}` variant, which is what the SDKs report as the flag's value.
The calling code must therefore keep the original experience reachable.

To end the exclusion, detach the holdout from the experiment or remove the `holdout` key from the flag's filters.

## How they are stored

### Database model

The `ExperimentHoldout` model stores the holdout definition:

```python
class ExperimentHoldout(ModelActivityMixin, RootTeamMixin, models.Model):
    name = models.CharField(max_length=400)
    description = models.CharField(max_length=400, null=True, blank=True)
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="+")
    filters = models.JSONField(default=list)  # List of filter groups
    created_by = models.ForeignKey("posthog.User", on_delete=models.SET_NULL, null=True, related_name="+")
```

Only the first filter group's `rollout_percentage` reaches the linked flags, through the model's `exclusion_percentage` property.

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
`set_holdout` in `products/feature_flags/backend/facade/filters.py` is the only writer of the key.
It writes the key as `None` rather than removing it when the holdout is cleared, so a previously attached holdout stops applying instead of surviving a read-modify-write.

### Data type used

Rust:

```rust
pub struct Holdout {
    pub id: i64,
    pub exclusion_percentage: f64,
}
```

## Key files

| Component       | Path                                                 |
| --------------- | ---------------------------------------------------- |
| Model           | `products/experiments/backend/models/experiment.py`  |
| Serializer      | `ee/clickhouse/views/experiment_holdouts.py`         |
| Flag filters    | `products/feature_flags/backend/facade/filters.py`   |
| Shipping        | `products/experiments/backend/experiment_service.py` |
| Rust evaluation | `rust/feature-flags/src/flags/flag_matching.rs`      |
| Rust type       | `rust/feature-flags/src/flags/flag_models.rs`        |
| Frontend types  | `frontend/src/types.ts`                              |

Flag evaluation happens only in Rust.
The Django evaluator was removed, so no Python path reads the `holdout` object at request time.
