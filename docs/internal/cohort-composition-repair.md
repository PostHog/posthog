# Realtime cohort composition repair

Realtime cohort saves compare the filter definition as well as the behavioral and person-property leaf hashes.
Changes to AND/OR groups, leaf negation, group placement, and nested cohort references can require reconciliation even when the leaf hashes stay the same.
Empty groups remain in the definition fingerprint because the Rust processor excludes cohorts containing them from realtime evaluation.

## Repair selection

A leaf edit that already triggers an eligible backfill needs no extra composition repair.
Otherwise, a changed definition selects a behavioral run when a behavioral leaf hash exists, or an eligible person-property run.
Either run reconciles the whole cohort against the processor's catalog.
Run creation remains behind `COHORT_BACKFILL_TRIGGER_TEAM_ALLOWLIST`, with a 300-second debounce per cohort and kind.
Readiness invalidation and supersession apply to teams in `REALTIME_COHORT_TEAM_ALLOWLIST` independently of run creation.

The selected kind's readiness timestamp and `last_realtime_cohort_calculation_at` are cleared on save.
Kind hashes keep their existing format and meaning so running seeders can continue to compare them.
Before stamping readiness, the finalizer locks the cohort row and checks whether the pinned definition predates a composition repair of that kind.
This prevents an older run from restoring readiness between an edit's commit and its deferred supersession callback.
An edit confined to the other leaf kind can still leave a run valid.
If the current or pinned definition cannot be fingerprinted, the finalizer refuses readiness and supersedes the participation.
For a cohort-scoped run, it also marks the run superseded so malformed filters cannot leave it retrying indefinitely.

## Stored hashes and save cost

Legacy `filters_shape_hash` values describe only the leaf set.
When the stored hash differs, the save path fingerprints the persisted filters before deciding whether the definition changed.
An unchanged first save upgrades the fingerprint without scheduling a repair.
Malformed persisted filters do not prevent a valid replacement from invalidating either kind's readiness, including when legacy kind hashes are NULL.

The comparison retains one indexed database query for an existing tracked cohort.
Postgres filters out rows whose definition hash already matches, so ordinary unchanged saves avoid transferring and hashing the persisted filter JSON.
Checking the persisted hash is necessary because an older model instance can overwrite a concurrent composition edit.

## Existing limits

- The flags service defaults to `REALTIME_COHORT_MEMBERSHIP_STAMP_POLICY=any_backfill_stamp`.
  Under that policy, a mixed cohort's retained person-property stamp can keep old membership rows in use while a behavioral repair is pending.
  `events_or_calculation_stamp` stops using those rows after the events and calculation timestamps are cleared.
  Changing the default is a separate routing rollout; this repair does not change it or claim to stop all stale reads during backfill.
- Reference-only cohorts have neither a behavioral nor a person-property state hash, so neither supported run kind can reconcile them.
  Cascade evaluation can update their stored membership when a referenced membership changes, but a catalog refresh alone does not repair existing rows.
  Direct flag evaluation uses their filter tree; stale reference-only state can still affect realtime cascade dependents.
  Repairing that state requires a reconcile scope and fence that support reference-only cohorts, beyond choosing an existing run kind.
- An empty-group definition is detected and its selected readiness is invalidated, but the processor cannot complete a repair while the definition remains ineligible.
  Remove the empty group to restore an eligible definition.
- Changes made while a cohort is outside realtime tracking are not fully covered by the composition comparison on re-entry.
