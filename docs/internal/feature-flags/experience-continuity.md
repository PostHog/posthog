# Feature Flags Experience Continuity

Experience continuity ensures users see consistent feature flag variants when transitioning from anonymous to identified state. Without it, a user might see variant A while anonymous, then suddenly switch to variant B after logging in.

## Why the switch happens

When evaluating a feature flag with multiple variants, PostHog determines which variant a user gets by hashing the `distinct_id`:

1. Takes the user's `distinct_id` (e.g., `"anon_abc123"` or `"user@example.com"`)
2. Combines it with the feature flag key
3. Hashes the result to get a number between 0 and 1
4. Compares that number against the rollout percentage (divided by 100) to assign a variant

For example, with a 50/50 A/B test:

- Hash values 0.0–0.5 → Variant A
- Hash values 0.5–1.0 → Variant B

When a user logs in, their `distinct_id` changes, which produces a different hash value that can land in a different variant bucket:

```text
Anonymous:   hash("anon_abc123" + "my-flag") → 0.23 → Variant A
Logged in:   hash("user@example.com" + "my-flag") → 0.67 → Variant B
```

This is the problem experience continuity solves.

## How It Works

When a user identifies, PostHog stores a "hash key override" that preserves the original anonymous `distinct_id` for future flag evaluations. This ensures the same hash bucket is used before and after identification.

```text
Anonymous visit: distinct_id = "anon_abc123" → hash bucket 42 → variant "control"
User identifies:  distinct_id = "user_456"   → stored override: use "anon_abc123" for hashing
Future requests:  distinct_id = "user_456"   → hash bucket 42 → variant "control" (consistent!)
```

## Key Concepts

### When Overrides Are Written

Hash key overrides are written during `/flags` requests that include `$anon_distinct_id`. They are **not** written during `identify()` calls.

| SDK Type        | Behavior                                                                                              |
| --------------- | ----------------------------------------------------------------------------------------------------- |
| **Web SDK**     | Automatic. When `identify()` is called, the SDK automatically reloads flags with `$anon_distinct_id`. |
| **Server SDKs** | Manual. You must include `$anon_distinct_id` as a top-level field in `/flags` requests.               |

### Flag Configuration

A flag must have `ensure_experience_continuity = true` to participate in the override system. This setting is only meaningful for:

- Person-based flags (not group-based)
- Flags using `distinct_id` bucketing (not `device_id`)

### Database Schema

Overrides are stored in `posthog_featureflaghashkeyoverride`:

```sql
-- Schema (simplified)
CREATE TABLE posthog_featureflaghashkeyoverride (
    team_id          INTEGER,
    person_id        INTEGER,      -- FK to Person (required!)
    feature_flag_key VARCHAR(400),
    hash_key         VARCHAR(400)  -- The original anonymous distinct_id
);
```

## Request Flow

### Web SDK (Automatic)

```text
1. User calls posthog.identify("user_456")
2. SDK stores previous distinct_id internally
3. SDK automatically calls /flags with:
   {
     "distinct_id": "user_456",
     "$anon_distinct_id": "anon_abc123",  // Top-level field!
     ...
   }
4. Server writes hash key overrides for continuity-enabled flags
5. Server returns flag values using stored overrides
```

### Server SDK (Manual)

```python
# You must manually include $anon_distinct_id
requests.post('https://app.posthog.com/flags/', json={
    'token': 'phc_abc123',
    'distinct_id': 'user_456',
    '$anon_distinct_id': 'anon_abc123',  # Top-level, NOT in person_properties
    'person_properties': {}
})
```

## Implementation Details

### Code Locations (Rust - Primary)

| Component             | Location                                              |
| --------------------- | ----------------------------------------------------- |
| Flag evaluation entry | `rust/feature-flags/src/flags/flag_matching.rs`       |
| Override processing   | `rust/feature-flags/src/flags/flag_matching_utils.rs` |
| Request parsing       | `rust/feature-flags/src/handler/properties.rs`        |
| Helper methods        | `rust/feature-flags/src/flags/flag_operations.rs`     |

### Processing Logic

1. **Check eligibility**: Does any flag have `ensure_experience_continuity = true`?
2. **Determine if lookup needed**: See optimization section below
3. **Write overrides**: For flags with continuity enabled, store the hash key
4. **Read overrides**: Load stored overrides for flag evaluation
5. **Apply overrides**: Use stored `hash_key` instead of current `distinct_id` for hashing

### Read-After-Write Consistency

When writing hash key overrides, the system reads from the **writer** database (not the replica) to avoid replication lag issues:

```rust
// flag_matching.rs:427-434
let database_for_reading = if writing_hash_key_override {
    self.router.get_persons_writer().clone()
} else {
    self.router.get_persons_reader().clone()
};
```

## Optimization: Skipping Unnecessary Lookups

**Added in PR #44293**

Flags at 100% rollout with no multivariate variants return the same value for everyone, making the hash bucket irrelevant. The system can skip database lookups for these flags.

### Config

```bash
OPTIMIZE_EXPERIENCE_CONTINUITY_LOOKUPS=true  # Default: true
```

### Helper Methods

```rust
// Does flag have continuity enabled AND is eligible (person-based, distinct_id bucketing)?
flag.has_experience_continuity()

// Does the flag have variants where hashing affects assignment?
flag.has_hash_dependent_variants()

// Does any condition group have < 100% rollout?
flag.has_partial_rollout()

// Final decision: should we do the database lookup?
flag.needs_hash_key_override()
```

### When Lookups Are Skipped

A flag **doesn't need** a hash key override lookup when:

- It's at 100% rollout, AND
- It has no multivariate variants (or a single variant at 100%)

Example: A flag rolled out to everyone (`rollout_percentage: 100`) returns `true` for all users regardless of their hash bucket.

### Metrics

```text
flags_experience_continuity_optimized_total{status="skipped"}   # Lookup was skipped
flags_experience_continuity_optimized_total{status="eligible"}  # Could have been skipped (optimization disabled)
```

### Impact

Query to identify teams that can benefit:

```sql
WITH continuity_flags AS (
    SELECT
        team_id,
        CASE
            WHEN jsonb_array_length(COALESCE(filters->'multivariate'->'variants', '[]'::jsonb)) > 0
            THEN true ELSE false
        END as has_variants,
        CASE
            WHEN EXISTS (
                SELECT 1 FROM jsonb_array_elements(COALESCE(filters->'groups', '[]'::jsonb)) as g
                WHERE (g->>'rollout_percentage')::numeric < 100
            )
            THEN true ELSE false
        END as has_partial_rollout
    FROM posthog_featureflag
    WHERE ensure_experience_continuity = true
        AND active = true
        AND deleted = false
),
team_summary AS (
    SELECT
        team_id,
        bool_and(NOT (has_variants OR has_partial_rollout)) as can_skip_lookup
    FROM continuity_flags
    GROUP BY team_id
)
SELECT
    COUNT(*) as teams_with_continuity,
    SUM(CASE WHEN can_skip_lookup THEN 1 ELSE 0 END) as teams_that_can_skip,
    ROUND(100.0 * SUM(CASE WHEN can_skip_lookup THEN 1 ELSE 0 END) / COUNT(*), 1) as pct_optimizable
FROM team_summary;
```

Common pattern: Teams enable continuity for A/B tests, roll out to 100%, but leave the setting enabled. This optimization handles that automatically.

## Known Limitation: `person_profiles: 'identified_only'`

Experience continuity **does not work** with `person_profiles: 'identified_only'` due to a race condition.

### The Problem

With `identified_only`, no person record exists until the `$identify` event is processed. But:

1. SDK calls `identify()` which sends `$identify` event (async processing)
2. SDK immediately sends `/flags` request with `$anon_distinct_id` (sync)
3. `/flags` request arrives **before** the person is created
4. Hash key override write fails silently (no person_id to reference)
5. Client receives HTTP 200, clears `$anon_distinct_id`
6. Person eventually created, but no retry happens

### Why It Works with `person_profiles: 'always'`

With `always`, a person record already exists from the anonymous visit. The `identify()` call adds the new `distinct_id` to the **existing** person, so the hash key override write succeeds.

### Workaround Options

1. **Use `person_profiles: 'always'`** - Creates person records for anonymous users
2. **Use `$device_id` bucketing** - Stable across identity changes, no person needed
3. **Future: Server signals success** - Client only clears `$anon_distinct_id` when confirmed

## Alternative: Device ID Bucketing

Because experience continuity requires a person record to exist (which doesn't happen with `person_profiles: 'identified_only'` until after identification), we've added a new bucketing identifier: `device_id` to address these issues. This feature is still under construction.

Instead of using experience continuity (which requires database writes and person records), you can configure a flag to use `device_id` as the bucketing identifier. This is a simpler approach that works without person profiles.

### Mechanism

When a flag is configured for `device_id` bucketing:

1. The hash is computed using the `$device_id` instead of `distinct_id`
2. Since `$device_id` is stable across authentication state changes, users always get the same variant
3. No hash key overrides are written or read from the database
4. Works with `person_profiles: 'identified_only'` (no person record needed)

```text
Anonymous:   hash("device_xyz" + "my-flag") → 42 → Variant A
Logged in:   hash("device_xyz" + "my-flag") → 42 → Variant A (same!)
```

### When to Use Device ID Bucketing

| Scenario                                   | Recommendation                  |
| ------------------------------------------ | ------------------------------- |
| Anonymous user experiments (signup flows)  | ✅ device_id bucketing          |
| Using `person_profiles: 'identified_only'` | ✅ device_id bucketing          |
| Experiment must persist across devices     | ❌ Use distinct_id + continuity |
| Already have person records (always mode)  | Either works                    |

### Configuration

Set `bucketing_identifier` on the feature flag:

- `distinct_id` (default) - Uses `distinct_id`, supports experience continuity
- `device_id` - Uses `$device_id`, no experience continuity needed

### Code References

The Rust service determines the hashed identifier in `flag_matching.rs:1260-1289`:

```rust
// Check if flag is configured for device_id bucketing
if feature_flag.get_bucketing_identifier() == BucketingIdentifier::DeviceId {
    if let Some(device_id) = &self.device_id {
        if !device_id.is_empty() {
            return Ok(device_id.clone());
        }
    }
    // Falls back to distinct_id if device_id not provided
}
```

### Current Status

| Component               | Status     | PR/Notes                                          |
| ----------------------- | ---------- | ------------------------------------------------- |
| Rust flag evaluation    | ✅ Shipped | #41281                                            |
| Database field          | ✅ Shipped | #42463                                            |
| UI (behind flag)        | ✅ Shipped | #43576                                            |
| AA test validation      | ✅ Running | #44532 (signup form AA test)                      |
| SDK support             | 🔄 Pending | SDKs need to send `$device_id` in `/flags`        |
| Local evaluation (SDKs) | 🔄 Pending | SDK local eval needs bucketing_identifier support |
| Documentation           | 🔄 Pending | Public docs explaining when to use each approach  |

### Request Payload

The SDK must include `$device_id` as a top-level field in `/flags` requests:

```json
{
  "token": "phc_abc123",
  "distinct_id": "user_456",
  "$device_id": "device_xyz789",
  "person_properties": {}
}
```

### Fallback Behavior

If a flag is configured for `device_id` bucketing but no `$device_id` is provided in the request, the system falls back to using `distinct_id`. This maintains backward compatibility but may result in variant changes during identity transitions.

## Debugging Guide

### Check If Overrides Were Written

```sql
SELECT * FROM posthog_featureflaghashkeyoverride
WHERE team_id = ?
  AND person_id = ?
  AND feature_flag_key = ?;
```

### Check Which Flags Have Continuity Enabled

```sql
SELECT key, ensure_experience_continuity, active, deleted
FROM posthog_featureflag
WHERE team_id = ?
  AND ensure_experience_continuity = TRUE
  AND active = TRUE
  AND deleted = FALSE;
```

### Verify Request Structure

Ensure `$anon_distinct_id` is a **top-level field**, not nested in `person_properties`:

```json
{
  "distinct_id": "user_456",
  "$anon_distinct_id": "anon_abc123",
  "person_properties": {}
}
```

### Common Issues

| Symptom                              | Likely Cause               | Solution                                                    |
| ------------------------------------ | -------------------------- | ----------------------------------------------------------- |
| Variant changes after identify       | Override not written       | Check request includes `$anon_distinct_id` at top level     |
| Only some flags maintain continuity  | Not all flags have setting | Enable `ensure_experience_continuity` on all relevant flags |
| Overrides never written (server SDK) | Manual step missing        | Include `$anon_distinct_id` in `/flags` requests            |
| Race condition failures              | `identified_only` mode     | Switch to `always` or use `device_id` bucketing             |

### Logs to Check

- `/flags` endpoint logs for `anon_distinct_id` processing
- Canonical log field: `hash_key_override_status` (values: `None`, `"skipped"`, `"error"`, `"empty"`, `"found"`)
- Metric: `flags_experience_continuity_optimized_total`
- Metric: `flags_hash_key_query_result_total` (labels: `result="empty"` or `result="has_overrides"`)

## See also

- [Creating feature flags](https://posthog.com/docs/feature-flags/creating-feature-flags) - How to enable "persist flag across authentication steps"
- [Client-side bootstrapping](https://posthog.com/docs/feature-flags/bootstrapping) - Alternative approach (incompatible with experience continuity)
- [Feature flags troubleshooting](https://posthog.com/docs/feature-flags/common-questions) - Common issues and solutions
