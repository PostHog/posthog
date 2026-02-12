# Super groups

## What they are

Super groups are a feature flag evaluation mechanism that controls enrollment in early access features. Despite the name suggesting "groups of users," they're actually a single person-level property check that determines whether someone has opted into an early access feature.

When a super group condition matches, it takes precedence over all regular feature flag conditions—hence "super." The evaluation returns immediately without checking other conditions.

## What they're used for

Super groups power the early access feature (EAF) system. When users opt into an early access feature through the UI, PostHog sets a person property like `$feature_enrollment/my-feature = true`. The super group condition checks for this property.

Example flow:

1. Product team creates an early access feature "New Dashboard" linked to feature flag `new-dashboard`
2. PostHog automatically adds a super group to the flag checking `$feature_enrollment/new-dashboard`
3. User opts in via the early access features UI
4. PostHog sets `$feature_enrollment/new-dashboard = true` on their person
5. On next flag evaluation, super group matches → user sees the feature
6. Regular rollout conditions are never checked for this user

This allows opted-in users to see features regardless of percentage rollouts, geography targeting, or other conditions on the flag.

## How they are stored

Super groups are stored in the feature flag's `filters` JSON field alongside regular conditions:

```json
{
  "filters": {
    "groups": [
      {
        "properties": [...],
        "rollout_percentage": 50
      }
    ],
    "super_groups": [
      {
        "properties": [
          {
            "key": "$feature_enrollment/new-dashboard",
            "type": "person",
            "operator": "exact",
            "value": ["true"]
          }
        ],
        "rollout_percentage": 100
      }
    ]
  }
}
```

### Data type used

Super groups use the same `FeatureFlagGroupType` as regular conditions:

```typescript
interface FeatureFlagGroupType {
  properties: AnyPropertyFilter[]
  rollout_percentage: number | null
  variant: string | null
}
```

## Why this causes confusion

### The name doesn't match the purpose

"Super groups" suggests:

- A group-based targeting concept (like "premium users" or "beta testers")
- Something related to PostHog's group analytics feature
- A collection of users

What it actually is:

- A single person property check
- Specifically for `$feature_enrollment/{flag_key}` properties
- An enrollment gate, not a targeting mechanism

A clearer name would be `enrollment_condition` or `early_access_gate`.

### The type allows more than is supported

Using `FeatureFlagGroupType` implies you can:

- Add multiple properties (you can't—only the first is evaluated)
- Use any property key (only `$feature_enrollment/*` makes sense)
- Use different operators (only `exact` with `["true"]` is meaningful)
- Set different rollout percentages (it's always 100% for enrolled users)

The evaluation code only checks the first property:

```python
# From flag_matching.py
prop_key = (condition.get("properties") or [{}])[0].get("key")
```

### It's not group-based at all

This is the most confusing aspect. PostHog has a separate "groups" feature for company-level / account-level analytics. Super groups have nothing to do with that:

| Concept             | What it means                                    |
| ------------------- | ------------------------------------------------ |
| PostHog groups      | Company/account-level entities for B2B analytics |
| Feature flag groups | Release condition sets (targeting rules)         |
| Super groups        | Early access enrollment checks                   |

Three unrelated uses of "group" in feature flags.

### Constraints not enforced by the type

The serializer and API enforce constraints that the type doesn't express:

- Early access features can't attach to group-based flags
- Early access features can't have multivariate variants
- Super groups only support person properties

These constraints live in validation code, not the type system, making the valid configurations unclear from the schema alone.

### A clearer alternative would be

A dedicated type that reflects what super groups actually do:

```typescript
interface EarlyAccessEnrollment {
  featureFlagKey: string // The key checked in $feature_enrollment/{key}
  enabled: boolean // Always true when present
}
```

Or even simpler, a boolean flag on the feature flag model:

```python
class FeatureFlag(models.Model):
    has_early_access_enrollment = models.BooleanField(default=False)
```

The enrollment property key can be derived from the flag key, eliminating the need for a separate structure.

## Key files

| Component         | Path                                                                     |
| ----------------- | ------------------------------------------------------------------------ |
| Python evaluation | `posthog/models/feature_flag/flag_matching.py`                           |
| Rust evaluation   | `rust/feature-flags/src/flags/flag_matching.rs`                          |
| Early access API  | `products/early_access_features/backend/api.py`                          |
| Frontend types    | `frontend/src/types.ts`                                                  |
| Frontend logic    | `frontend/src/scenes/feature-flags/featureFlagReleaseConditionsLogic.ts` |
