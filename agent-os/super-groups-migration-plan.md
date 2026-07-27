# Feature enrollment migration: `super_groups` → `feature_enrollment`

## Problem

The `super_groups` field in feature flag `filters` reuses `FlagPropertyGroup`,
a type designed for regular conditions.
This creates semantic confusion:

- `properties` always contains exactly one entry — `$feature_enrollment/{flag_key}` with `exact` operator and `["true"]` value
- `rollout_percentage` is always `100` — the type suggests partial rollouts, but that's never used
- The name "super groups" doesn't appear in the product UI — users see "Early access features" and "Feature enrollment"
- Payloads are larger than necessary — a complex nested structure where a boolean would suffice

### Current production usage

| Region | Flags with super_groups | Teams |
| ------ | ----------------------- | ----- |
| US     | 976                     | 419   |
| EU     | 582                     | 282   |

Higher usage than the holdout migration (~20 rows). Requires batched migration.

## Target format

**Before:**

```json
{
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
```

**After:**

```json
{
  "feature_enrollment": true
}
```

### Why the enrollment key is derivable from the flag key

The enrollment property is **always** `$feature_enrollment/{flag_key}` — this invariant is enforced at every layer:

1. **Every write path** constructs it from the flag key: `f"$feature_enrollment/{feature_flag_key}"` in `products/early_access_features/backend/api.py` (both `create()` and `update()`)
2. **On flag key rename**, `_update_super_groups_for_key_change()` in `posthog/api/feature_flag.py` rewrites the enrollment key to match the new flag key
3. **Migration 0748** (`posthog/migrations/0748_update_featureflag_super_groups.py`) was specifically written to fix historical cases where the enrollment key drifted out of sync — it forced `$feature_enrollment/{flag.key}` for every active flag

There is no case where a flag's super_groups references a _different_ flag's enrollment key. The data is fully redundant with `flag.key`, so evaluation code can construct the key at runtime (same pattern as the Rust service constructing `holdout-{id}` for holdouts).

### Design decisions

- **Boolean `feature_enrollment`, not a string array.**
  Since the enrollment key is derivable (see above), no additional data is needed.
  A boolean is the simplest representation: "this flag has feature enrollment enabled."

- **`feature_enrollment` instead of `feature_enrollments`.**
  A flag either has feature enrollment or it doesn't — it's not a collection.
  The singular form matches the boolean semantics.

- **Not a model field.**
  Keeping it in `filters` JSON avoids a schema migration and keeps the flag definition self-contained for the Rust service
  (which reads filters from Redis/Postgres JSON, not Django model fields).

---

## Migration phases

### Phase 1: Django writes both formats (backwards-compatible)

**Status:** MERGED

**Why first:** Writing is always safer to change first —
it doesn't affect what's currently being read.
If we update Rust first to read `feature_enrollment` before Django writes it,
there's a deployment window where newly created enrollments would only have `super_groups`
while Rust prefers `feature_enrollment`.

**Tasks:**

- [x] Add `feature_enrollment` field support to `FlagFilters` serializer in Django
- [x] Update `super_conditions` lambda in `products/early_access_features/backend/api.py` to also set `feature_enrollment: true`
- [x] Update `_update_super_groups_for_key_change` in `posthog/api/feature_flag.py` — added comment noting `feature_enrollment` is key-independent
- [x] Update `pre_delete` hook in `products/early_access_features/backend/apps.py`
- [x] Add `has_feature_enrollment` property to `FeatureFlag` model
- [x] Tests: all 28 early access feature tests + 1 feature flag key update test pass

### Phase 2: Rust reads new format with fallback

**Status:** MERGED

**Depends on:** Phase 1 deployed

**Tasks:**

- [x] Add `feature_enrollment: Option<bool>` field to `FlagFilters` struct in Rust
- [x] Add `FlagFilters::enrollment_key(flag_key)` shared helper to derive `$feature_enrollment/{flag_key}`
  - Used by both evaluation logic and `requires_db_properties` — avoids format string duplication
- [x] Update super condition evaluation in `flag_matching.rs` to prefer `feature_enrollment` over `super_groups`
  - If `feature_enrollment == Some(true)`: derive enrollment key via helper, check person properties directly
  - Else if `super_groups` present: legacy fallback via `is_super_condition_match`
  - Else: no enrollment, proceed to normal conditions
- [x] Update `requires_db_properties` in `flag_filters.rs` to handle `feature_enrollment`
  - Takes `flag_key` parameter; checks if overrides contain the derived enrollment key
- [x] `SuperConditionEvaluation` kept as-is (still used by legacy fallback, removed in Phase 4)
- [x] Tests:
  - Parameterized `test_feature_enrollment_match_by_property_value` — 4 cases: string `"true"`/`"false"`, boolean `true`/`false`
  - `test_feature_enrollment_no_property_falls_through` — person without enrollment property falls through to regular conditions
  - `test_feature_enrollment_takes_precedence_over_super_groups` — both formats present, new format wins
  - `test_feature_enrollment_requires_db_properties_when_override_missing` / `test_feature_enrollment_skips_db_when_override_present` — unit tests for `requires_db_properties`
  - All 6 existing `super_groups` tests still pass (legacy fallback)
- [x] Updated all `FlagFilters` struct literals across the codebase to include `feature_enrollment: None`

### Phase 3: Backfill existing flags

**Status:** MERGED (1076 was no-op due to bug, 1078 fix verified in production)

**Depends on:** Phase 2 deployed (Rust fallback handles both formats)

**Tasks:**

- [x] Write a Django data migration to convert all existing flags
  - Batched `RunPython` with `.iterator(chunk_size=250)` and `bulk_update` in batches of 250
  - `elidable=True`, `noop` reverse, try/except per flag with logging
  - Defensive Python guards: `isinstance(super_groups, list)`, skip empty, skip already-updated
- [x] Migration 1076 deployed but silently updated 0 rows — `filters__super_groups__isnull=False`
      generates unquoted JSON key in SQL (`filters -> super_groups` instead of `filters -> 'super_groups'`),
      causing the queryset to match nothing
- [x] Migration 1078 fix deployed with corrected queryset:
  - `filters__has_key="super_groups"` + `.exclude(super_groups=None)` + `.exclude(super_groups=[])`
  - `.extra(where=["NOT (filters ? 'feature_enrollment' AND filters->>'feature_enrollment' = 'true')"])`
    for the `feature_enrollment` exclusion (ORM `exclude(filters__feature_enrollment=True)` also
    generates broken SQL with unquoted keys — it excludes ALL rows instead of none)
- [x] Verified in production: ~900 rows updated in both US and EU

**Lesson learned:** Django's JSONField ORM lookups on nested keys (`filters__some_key=value`,
`filters__some_key__isnull=False`) can generate SQL with unquoted key names.
Use `has_key`, `exclude(field=None)`, `exclude(field=[])`, and `.extra(where=[...])` with raw SQL
for reliable JSON key filtering in migrations.

### Phase 4: Remove legacy reading

**Status:** MERGED (#59100)

**Depends on:** Phase 3 complete + verified in production

**Tasks:**

- [x] Remove `super_groups` fallback from Rust evaluation
  - `flag_matching.rs`: only read `feature_enrollment`
  - Remove `super_groups` from `FlagFilters` struct (serde silently ignores unknown JSON keys)
  - Remove `is_super_condition_match` method (replaced by simpler enrollment check)
  - Remove `SuperConditionEvaluation` struct
- [x] Remove `super_groups` reading from Django code
- [x] Update `flag_matching.py` gate and `is_super_condition_match` together to read `feature_enrollment` instead of `super_groups`
  - Replaced `is_super_condition_match` with `is_feature_enrollment_match`: derives enrollment key from flag key, reads from `query_conditions` directly
  - Replaced `_super_condition_matches` and `_super_condition_is_set` with enrollment-aware equivalents
  - Kept `FeatureFlagMatchReason.SUPER_CONDITION_VALUE` — renaming would change the API response string
- [x] Remove `super_conditions` property from `feature_flag.py`
- [x] Tests: deleted 8 legacy super_groups unit tests, 2 filter tests, 1 operations test, 1 cache weigher test; converted 3 integration tests to `feature_enrollment` format; renamed test functions from `super_condition` to `feature_enrollment`; added parameterized Python test for `is_feature_enrollment_match` covering all 4 branches
- [x] Cleaned up all `super_groups: None` struct literals across Rust codebase

**Note:** `SuperConditionValue` reason code rename deferred — changing the serialized string `"super_condition_value"` would break the API response format. Can be revisited independently.

**Note:** One customer (team 361776) has 7 flags with non-standard `super_groups` keys (e.g. `$feature/section-test` instead of `$feature_enrollment/...`). They were emailed in early May to re-save their flags but never did. Their flags will stop matching on the enrollment condition but continue evaluating regular conditions normally.

### Phase 5: Remove legacy writing

**Status:** not started

**Depends on:** Phase 4 deployed + no rollback needed

**Tasks:**

- [ ] Stop writing `super_groups` in early access feature serializer (`products/early_access_features/backend/api.py`)
  - Replace the `super_conditions` lambda with simple `"feature_enrollment": True`
  - All 5 write sites: promote to active (update), create with active stage, GA rollout_to_all, demote/archive, destroy
- [ ] Remove `("super_groups", "rollout_percentage")` from `ROLLOUT_PERCENTAGE_PATHS` in `posthog/approvals/actions/feature_flags.py`
  - Feature enrollment doesn't have a rollout percentage concept — no replacement path needed
- [ ] Remove `_update_super_groups_for_key_change()` from `posthog/api/feature_flag.py`
  - `feature_enrollment` is a boolean — no key-dependent data to update
- [ ] Remove `pre_delete` super_groups cleanup from `products/early_access_features/backend/apps.py`
  - Replace with `feature_enrollment: None` cleanup
- [ ] Update test assertions that check `filters["super_groups"]`:
  - `products/early_access_features/backend/test/test_early_access_feature.py` (multiple tests)
  - `posthog/api/test/test_feature_flag.py` (`test_updating_feature_flag_key_updates_super_groups` — remove or rewrite)
  - `posthog/approvals/tests/test_update_feature_flag_action.py`
- [ ] Update frontend — see [Frontend changes detail](#frontend-changes-detail) below
- [ ] Opportunistic cleanup: strip `super_groups` from `filters` on next flag save (`update()` in `posthog/api/feature_flag.py`)
  - Same pattern as `holdout_groups` cleanup (line 1364)
- [ ] Run `hogli build:openapi` to regenerate TypeScript types

### Phase 6: Data cleanup

**Status:** not started

**Depends on:** Phase 5 deployed

Strip the `super_groups` key from stored `filters` JSON on existing flags. After Phase 5, no code reads or writes `super_groups` — the key is dead data in the JSON column.

**Tasks:**

- [ ] Write a Django data migration to remove `super_groups` from `filters` JSON on all flags
  - Use batched approach: query flags with `filters__has_key="super_groups"`, pop the key, `bulk_update` in batches
  - `elidable=True` since this is purely a data cleanup
  - Consider doing this as a raw SQL migration for efficiency: `UPDATE posthog_featureflag SET filters = filters - 'super_groups' WHERE filters ? 'super_groups'`
- [ ] Alternatively, rely on the opportunistic cleanup from Phase 5 (strip on save) and skip the migration entirely — dead data with no reader impact

---

## Key files to modify

| Component                         | File                                                                     | Phase |
| --------------------------------- | ------------------------------------------------------------------------ | ----- |
| Django serializer schema          | `posthog/api/feature_flag.py`                                            | 1, 5  |
| Early access feature serializer   | `products/early_access_features/backend/api.py`                          | 1, 5  |
| Early access feature app hooks    | `products/early_access_features/backend/apps.py`                         | 1, 5  |
| Feature flag model                | `products/feature_flags/backend/models/feature_flag.py`                  | 1, 4  |
| Python flag matching              | `products/feature_flags/backend/flag_matching.py`                        | 4     |
| Approvals change tracking         | `posthog/approvals/actions/feature_flags.py`                             | 5     |
| Rust flag models                  | `rust/feature-flags/src/flags/flag_models.rs`                            | 2     |
| Rust flag matching                | `rust/feature-flags/src/flags/flag_matching.rs`                          | 2, 4  |
| Rust flag filters                 | `rust/feature-flags/src/flags/flag_filters.rs`                           | 2, 4  |
| Rust flag match reason            | `rust/feature-flags/src/flags/flag_match_reason.rs`                      | 4     |
| Rust API types                    | `rust/feature-flags/src/api/types.rs`                                    | 4     |
| Rust test utilities               | `rust/feature-flags/src/utils/test_utils.rs`                             | 2, 4  |
| Rust flag operations tests        | `rust/feature-flags/src/flags/flag_operations.rs`                        | 2, 4  |
| Rust flag service tests           | `rust/feature-flags/src/flags/flag_service.rs`                           | 2, 4  |
| Rust flag matching tests          | `rust/feature-flags/src/flags/test_flag_matching.rs`                     | 2, 4  |
| Rust integration tests            | `rust/feature-flags/tests/test_flags.rs`                                 | 2, 4  |
| Frontend types                    | `frontend/src/types.ts`                                                  | 5     |
| Frontend flag logic               | `frontend/src/scenes/feature-flags/featureFlagLogic.ts`                  | 5     |
| Frontend release conditions logic | `frontend/src/scenes/feature-flags/featureFlagReleaseConditionsLogic.ts` | 5     |
| Frontend flag UI                  | `frontend/src/scenes/feature-flags/FeatureFlag.tsx`                      | 5     |
| Frontend flag overview            | `frontend/src/scenes/feature-flags/FeatureFlagOverviewV2.tsx`            | 5     |
| Data migration (backfill)         | `posthog/migrations/XXXX_backfill_feature_enrollment.py`                 | 3     |
| Data migration (cleanup)          | `posthog/migrations/XXXX_strip_super_groups.py`                          | 6     |

## Frontend changes detail

> **Reminder:** When starting Phase 5, read this section carefully.
> The frontend changes are a net simplification — the entire `isSuper` code path
> through `featureFlagReleaseConditionsLogic` becomes dead code.
> Instead of rendering a complex property filter card for super conditions,
> you just show a boolean "Feature enrollment enabled" state.

### Files to change

1. **`frontend/src/types.ts`** (line 3874)
   - Add `feature_enrollment?: boolean` to `FeatureFlagFilters`
   - Remove `super_groups?: FeatureFlagGroupType[]`

2. **`frontend/src/scenes/feature-flags/FeatureFlag.tsx`** (line 244)
   - Currently checks `featureFlag.filters.super_groups?.length > 0` to render `<FeatureFlagReleaseConditions readOnly isSuper>`
   - Replace with `featureFlag.filters.feature_enrollment` and render a simpler indicator (no need for the full release conditions component)
   - The existing TODO comment at line 243 already calls for this cleanup

3. **`frontend/src/scenes/feature-flags/FeatureFlagOverviewV2.tsx`** (line 343)
   - Same pattern — checks `super_groups?.length > 0` to render `<FeatureFlagSuperConditionsReadonly>`
   - Replace with a simpler display for `feature_enrollment: true`

4. **`frontend/src/scenes/feature-flags/featureFlagLogic.ts`** (line 363)
   - `cleanFlag()` runs `cleanFilterGroups` on `super_groups` to strip `sort_key` — remove entirely, a boolean has no sort keys

5. **`frontend/src/scenes/feature-flags/featureFlagReleaseConditionsLogic.ts`** (lines 59, 82, 513)
   - `isSuper` prop, the key derivation using it, and the `filterGroups` selector branch that returns `filters.super_groups` — all dead code, remove
   - The entire `isSuper` code path can be deleted

6. **`frontend/src/scenes/feature-flags/FeatureFlagReleaseConditions.tsx`** (lines 93, 608, 787)
   - `isSuper` prop, title branching ("Super release conditions"), and `renderSuperReleaseConditionGroup` — all removable

7. **`frontend/src/scenes/feature-flags/FeatureFlagReleaseConditionsReadonly.tsx`** (line 227)
   - `FeatureFlagSuperConditionsReadonly` component passes `isSuper: true` — can be simplified or removed

8. **`frontend/src/scenes/surveys/surveyLogic.tsx`** (line 1785)
   - Sets `super_groups: undefined` when constructing filter objects — change to `feature_enrollment: undefined`

### How to test the frontend changes

Test each of these flows manually in the browser:

- [ ] **Create early access feature** in ALPHA/BETA stage → open the linked feature flag → confirm it shows "Feature enrollment enabled" (or the new UI) instead of the old super condition property card
- [ ] **Promote CONCEPT → ALPHA** → flag should now show feature enrollment indicator
- [ ] **Promote to GA with "rollout to all"** → flag should clear enrollment indicator, show 100% rollout in regular conditions
- [ ] **Demote ALPHA → CONCEPT** → enrollment indicator should disappear
- [ ] **Archive an early access feature** → enrollment indicator should disappear
- [ ] **Delete an early access feature** → enrollment indicator should disappear from the flag
- [ ] **Rename a flag key** that has enrollment → confirm nothing breaks (no enrollment key to update anymore — boolean is key-independent)
- [ ] **Feature flag overview page** (V2) → repeat the above checks for the readonly display
- [ ] **Survey with targeting flag** → confirm surveys still render correctly

---

## Risks and mitigations

### Cache staleness after backfill migration

**Risk:** `bulk_update` doesn't fire `post_save` signals, so HyperCache may serve stale data.
**Mitigation:** Phase 2's Rust fallback reads `super_groups` when `feature_enrollment` is missing, so stale cache entries behave identically. Cache refreshes naturally on TTL expiry. No explicit invalidation needed.

### Deployment ordering between Django and Rust

**Risk:** If Rust is deployed before Django, new enrollments created during the gap only have `super_groups`.
**Mitigation:** Deploy Django first (Phase 1), then Rust (Phase 2). The fallback in Rust handles both.

### Higher row count than holdout migration

**Risk:** ~1,558 flags vs ~20 for holdouts. Migration takes longer.
**Mitigation:** Use batched `bulk_update` with `batch_size=500`. Still small enough for a synchronous migration (< 2,000 rows). No need for async migration.

### Reason code rename in API responses

**Risk:** Renaming `super_condition_value` to `feature_enrollment_value` in flag match reasons changes the API response.
**Mitigation:** Check if any SDK or dashboard depends on this string. If so, keep `super_condition_value` as the serialized value (Rust serde rename) while using the new internal name. Alternatively, defer the rename to a separate PR.

### Frontend backward compatibility

**Risk:** If a user has an old frontend loaded that reads `super_groups`, the display may break after Phase 5.
**Mitigation:** Phase 5 frontend changes should handle both formats gracefully during rollout. The `feature_enrollment` boolean is additive; old frontends simply won't render it (they'll see no super_groups). New frontends check `feature_enrollment` first.

### Existing data migration 0748

**Risk:** Migration `0748_update_featureflag_super_groups.py` fixes `$feature_enrollment` keys in super_groups. After Phase 5, this migration references a removed field.
**Mitigation:** This migration is already applied in production and won't run again. No action needed — it's historical.

### Coordination with holdout_groups cleanup

**Risk:** Both this migration and holdout opportunistic cleanup touch `filters` JSON.
**Mitigation:** No conflict — they operate on different keys. The opportunistic strip pattern is independent per key.

## Notes from review

- The "only evaluate first super group" pattern (`super_groups[0]`) is now implicit in the boolean — there's nothing to index
- Feature enrollment is not supported by local evaluation — SDKs ignore `super_groups`, so no SDK changes needed
- Static cohort creation from flags ignores `super_groups` — no changes needed there
- The Python flag matching code in `posthog/models/feature_flag/flag_matching.py` is legacy but still actively used for database-backed evaluation. Unlike holdouts, super_groups ARE evaluated in this code path — Phase 4 must update it.
- The Rust service constructs the enrollment property key (`$feature_enrollment/{flag_key}`) internally from the flag key — this is an implementation detail, not data

## Differences from holdout migration

| Aspect                  | Holdout migration                      | Feature enrollment migration                          |
| ----------------------- | -------------------------------------- | ----------------------------------------------------- |
| Scale                   | ~20 rows                               | ~1,558 rows                                           |
| Target format           | `{id, exclusion_percentage}` object    | `true` boolean                                        |
| Key derivation          | `holdout-{id}` variant from holdout ID | `$feature_enrollment/{flag_key}` from flag key        |
| Python flag_matching.py | Ignores holdouts (legacy code)         | Actively evaluates super_groups — must update         |
| Frontend impact         | Minimal                                | Moderate — several components render super conditions |
| Approvals impact        | Had exclusion_percentage path          | Remove rollout_percentage path (no replacement)       |

## Future cleanup (out of scope)

- Consider removing the `$feature_enrollment/{key}` person property pattern entirely and using a dedicated enrollment model. This would decouple enrollment tracking from person properties, but is a much larger change.
- The `FeatureFlagReleaseConditions` component has a TODO comment (FeatureFlag.tsx:244) about cleaning up super_groups rendering — Phase 5 addresses this.
