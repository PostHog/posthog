# Feature enrollment

## What it is

Feature enrollment is a feature flag evaluation mechanism that controls opt-in to early access features.
It is a flag-level boolean marker, `filters.feature_enrollment`.
When it is `true`, the flag matcher checks the person property `$feature_enrollment/{flag_key}`.

The matcher evaluates enrollment **before** holdout groups and **before** the release condition loop.
When the person is enrolled, the matcher returns a match at once and never checks the rollout percentage.
So an early access flag needs **no release condition** to serve enrolled people.

Enrollment takes effect on the **next flag reload**, with no wait for event ingestion.
The client SDK (posthog-js) sends `$feature_enrollment/{flag_key}` as a request property override.
The matcher merges request overrides ahead of the database, so the flag is live on the very next `/flags` call.

## What it is used for

Feature enrollment powers the early access feature (EAF) system.
When a person opts in through the UI, PostHog sets a person property like `$feature_enrollment/my-feature` to the value `"true"` (stored as a string, not a boolean).

PostHog enables enrollment only for features in **active stages**: Alpha, Beta, and General Availability.
The Concept stage lets people register interest, but does not enable enrollment: PostHog does not set `feature_enrollment` on the flag, so opted-in people are not served through the enrollment shortcut.

Concept turns off the enrollment shortcut, not the flag's normal release-condition evaluation.
A flag auto-created for the feature starts at `rollout_percentage: 0`, so it serves nobody until the feature reaches an active stage.
A flag you link yourself keeps its own release conditions, and those still run: a linked flag already rolled out to everyone keeps matching people while the feature sits in Concept.
Demoting a feature back to Concept clears the enrollment marker but leaves the release conditions in place, so a flag previously rolled out to all stays at 100%.

Example flow:

1. A product team creates an early access feature "New Dashboard" in Alpha stage, linked to feature flag `new-dashboard`.
2. PostHog sets `filters.feature_enrollment` to `true` on the flag (only because it is in an active stage).
3. A person opts in through the early access features UI.
4. posthog-js sets `$feature_enrollment/new-dashboard` to `"true"` on the person and sends it as a request override.
5. On the next `/flags` call, the matcher sees the property and the person gets the feature.
6. The matcher never checks the release conditions for this person.

If the feature were in Concept stage instead, steps 3-4 would still happen (the person can register interest), but step 2 would not.
The enrollment shortcut would stay off, so enrollment would not serve the flag to opted-in people.
The flag's normal release conditions still apply: an auto-created flag sits at `rollout_percentage: 0` and serves nobody, but a linked flag keeps evaluating its own conditions.

## How it is stored

Enrollment is a single boolean in the feature flag's `filters` JSON field:

```json
{
  "groups": [
    {
      "properties": [],
      "rollout_percentage": 100
    }
  ],
  "feature_enrollment": true
}
```

The enrollment property key is **derived from the flag key** (`$feature_enrollment/{flag_key}`), so the flag stores no property structure.

### Legacy `super_groups`

Enrollment used to be a `filters.super_groups` block — an array of condition sets, each with a `$feature_enrollment/{flag_key}` property.
The `feature_enrollment` boolean replaced it as the enrollment mechanism.

The **flag matcher** no longer evaluates `super_groups`.
The Rust `FlagFilters` struct keeps unknown keys in its `extra` map, so `super_groups` round-trips through the cache but is never read during matching.

But `super_groups` is **not** fully removed. Stored values persist, and compatibility code outside the matcher still reads them:

- The backfill migrations (`1076_backfill_feature_enrollment`, `1078_backfill_feature_enrollment_fix`) only add `feature_enrollment = true`; they do not strip `super_groups`. The key is removed only opportunistically, when a flag is next saved (`api/feature_flag.py`), so rows nobody has edited still carry it.
- Python still reads it for behavior: `group_cohort_restriction_blocker` (`facade/filters.py`) and `is_unconditionally_fully_rolled_out` (`persisted_flags.py`) treat its presence as a blocker, and the experiment freeze-exposure control renders that blocker as a user-facing message. The resource-transfer visitors walk `("groups", "super_groups")` to collect and rewrite cohort and action ids, and `flags_cache._GROUP_LEVEL_LIST_KEYS` lists it for cache-drift comparison.
- The frontend still declares `super_groups` on `FeatureFlagFilters` (`frontend/src/types.ts`) and reads it: the experiment freeze-exposure guard checks it, and the flag AI context copies its value and count.

Do not add new `super_groups` — write `feature_enrollment` instead. New writes are steered to the marker:

- The Python filters schema lists `super_groups` in `LEGACY_UNKNOWN_FILTER_KEYS`.
- `set_feature_enrollment` (the facade transform) drops any `super_groups` key when it writes the marker.

## The enrollment property

The matcher reads `$feature_enrollment/{flag_key}` from the person properties (request overrides first, then the database).

| Property value              | Result                                                       |
| --------------------------- | ------------------------------------------------------------ |
| `"true"` (string) or `true` | Enrolled — the flag returns a match at once.                 |
| Any other present value     | Opted out — the flag returns no match at once.               |
| Absent                      | Not decided — evaluation falls through to normal conditions. |

`FlagFilters::is_enrolled` in `rust/feature-flags/src/flags/flag_filters.rs` defines the "enrolled" values.
An opted-out person (property `"false"`) does **not** fall through to the release conditions. The flag returns no match right away.

## Evaluation

`get_match` in `rust/feature-flags/src/flags/flag_matching.rs` evaluates enrollment first:

1. If `filters.feature_enrollment` is not `true`, the matcher skips this step.
2. The matcher derives the enrollment key with `FlagFilters::enrollment_key(flag_key)`.
3. The matcher reads the person properties. Enrollment is always person-level, even for group-based flags.
4. If the person **has** the enrollment property, the matcher returns at once with the reason `SuperConditionValue`. The match is `true` when the value means enrolled, and `false` otherwise.
5. If the person does **not** have the property, evaluation falls through to holdout groups and then the release conditions.

The match reason keeps the legacy name `SuperConditionValue` (score 6, the highest priority) — see the reason table in [flag-evaluation-engine.md](flag-evaluation-engine.md).

## Constraints

The serializer and API enforce constraints that the boolean alone does not express:

- Early access features cannot attach to group-based flags.
- Early access features cannot have multivariate variants.

These constraints live in validation code.

## Key files

| Component          | Path                                                                               |
| ------------------ | ---------------------------------------------------------------------------------- |
| Python model       | `products/feature_flags/backend/models/feature_flag.py` (`has_feature_enrollment`) |
| Filters transform  | `products/feature_flags/backend/facade/filters.py` (`set_feature_enrollment`)      |
| Filters validation | `products/feature_flags/backend/api/filters_schema.py`                             |
| Rust evaluation    | `rust/feature-flags/src/flags/flag_matching.rs` (`get_match`)                      |
| Rust helpers       | `rust/feature-flags/src/flags/flag_filters.rs` (`enrollment_key`, `is_enrolled`)   |
| Rust model         | `rust/feature-flags/src/flags/flag_models.rs` (`FlagFilters.feature_enrollment`)   |
| Early access API   | `products/early_access_features/backend/api.py`                                    |
| Frontend types     | `frontend/src/types.ts` (`FeatureFlagFilters.feature_enrollment`)                  |
