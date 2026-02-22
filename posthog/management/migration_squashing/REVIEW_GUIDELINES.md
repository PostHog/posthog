# Bootstrap policy review guidelines

This guide defines how to review entries in `--bootstrap-policy-template` files for migration squashing.
Use it for both human review and LLM-assisted review.

Canonical policy file in this repo:
`posthog/management/migration_squashing/bootstrap_policy.yaml`

Deterministic regeneration path:

- update only the canonical policy file
- run `plan_migration_squash --rebuild-from-raw-history --write --overwrite-existing --prune-stale-squashed`
- do not hand-edit generated `*_squashed_*.py` files

## Goal

Choose a deterministic action per blocker entry so bootstrap squashes are shorter without silent schema drift.
If uncertain, do not guess.
Leave `action: null` so the operation remains a blocker.

## Allowed actions

- `keep`
- `noop`
- `noop_if_empty`

No other values are valid.

## Action semantics

### `keep`

Use when the operation must remain in the squashed migration and is safe to execute during bootstrap.
This only removes the planning blocker.
The operation still runs in the generated squash.

Typical examples:

- schema-only `RunSQL` that changes constraints or indexes
- idempotent `RunSQL` DDL that should still run from zero

### `noop`

Use when the operation is historical-only and can always be skipped for bootstrap.
Planner rewrites:

- `RunPython` -> `RunPython.noop` both directions
- `RunSQL` -> `RunSQL.noop` both directions

Only valid for `RunPython` and `RunSQL`.

### `noop_if_empty`

Use when the operation is only needed for historical data, and bootstrap from empty DB should skip it.
Requires explicit probe tables:

```yaml
action: noop_if_empty
tables:
  - posthog_some_table
  - public.other_table
```

Planner rewrites to a guard SQL block that:

- checks each listed table exists
- checks each listed table has zero rows
- raises if any table is non-empty

Only valid for `RunPython` and `RunSQL`.

## Hard rules

- Missing entry or `action: null` means unresolved blocker.
- Fingerprints are mandatory safety checks.
  If the migration operation changes, policy must be re-reviewed.
- Never use `noop` or `noop_if_empty` for schema-changing operations unless explicitly modeled as `RunSQL`/`RunPython` historical noise and reviewed.
- If uncertain about behavior, leave unresolved.

## Evidence requirements for reviewers

For each resolved entry, include `reason` with concrete evidence:

- what the operation does
- why action is safe for bootstrap
- for `noop_if_empty`, why listed tables are sufficient probes

Good:

- `reason: Backfill only; source table is empty on bootstrap and guard enforces emptiness.`

Bad:

- `reason: probably safe`

## LLM usage constraints

LLMs may propose actions, but final policy is deterministic YAML in git.
LLM output must follow these rules:

- no free-form migration rewrites
- no inferred actions without evidence
- unresolved by default
- include table probes only when directly supported by migration code

## High-gain review order

When prioritizing work, start with blockers that unlock the largest bridge/streak gain.
Then review entries in that order with the same safety bar.
Do not lower evidence standards for high-gain candidates.

## Example entries

```yaml
version: 1
entries:
  - app: posthog
    migration: 0365_update_created_by_flag_constraint
    operation_index: 1
    nested_path: database_operations[0]
    action: keep
    fingerprint: sha256:...
    reason: Schema constraint state management; required in bootstrap path.

  - app: posthog
    migration: 0287_add_session_recording_model
    operation_index: 5
    nested_path: null
    action: noop_if_empty
    tables:
      - posthog_sessionrecordingplaylistitem
    fingerprint: sha256:...
    reason: Historical backfill; bootstrap starts empty and guard enforces emptiness.
```
