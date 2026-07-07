# Customer analytics — v1 compromises

Shortcuts taken to ship the first version. Revisit when they bite.

## Select custom property option side effects

- **Rename backfill / removal clearing runs inline.** `update_custom_property_definition` rewrites the definition's `CustomPropertyValue` rows synchronously, inside the definition-save transaction (`apply_option_side_effects` in `logic/custom_property_definitions.py`).
  For a definition with many account values this makes the PATCH slow and holds the transaction open.
  Brittle at scale — move to an async backfill job when large value sets bite.
- **Conversion safety lives in a caller-side guard.** Side effects run only while the definition is still `select`: on a select→other conversion the id diff would read every option as removed and wrongly clear all values, which must instead survive as plain strings.
  The guard sits in the facade update path, locked by `test_converting_select_to_text_keeps_values_and_clears_options`; a new write path that skips it would clear values on conversion.

## Custom property view sync

- **Celery, not Temporal.** The sync runs in a Celery task, not a dedicated Temporal workflow. No
  durable retries and no run-level UI inspection — failures surface via `last_sync_error` on the
  source + error tracking. Move to Temporal if we need durable retries, long-running syncs, or
  per-run inspection.
- **No retries.** A failed run is not retried; it records the failure (advancing the auto-disable
  streak) and waits for the next materialization. Only transient write conflicts retry, in-logic.
- **Direct dispatch by task name, not a signal.** Core (`succeed_materialization_activity`) enqueues
  this product's sync task by name via `send_task`. A generic core signal the product subscribes to
  would keep core ignorant of the consumer, but for a single consumer that isn't worth the wiring (a
  signal definition + a receiver + an app-ready hook). By-name dispatch also keeps the product and
  HogQL out of the data-modeling worker's process, since core imports nothing from here. Trade-off:
  core hardcodes this consumer's task name. If a second consumer ever needs the materialization event,
  switch to a core-owned signal (inversion of control) rather than adding another direct dispatch.
- **No save-time column validation.** Creating/updating a source does not check that `source_column`
  / `key_column` exist in the view's schema. A bad column surfaces as a per-source sync error (and
  advances the auto-disable streak) on the next run, not as a 400 on save. Validate against the saved
  query's `columns` at write time if the delayed feedback bites.
- **Initial sync is best-effort.** Saving an enabled source enqueues a sync on commit so values
  populate without waiting for the next materialization. If the broker is down the save still
  succeeds and the enqueue is dropped (logged to error tracking) — the next materialization recovers.
- **v2 materialization only.** v1 `run_workflow.py` is frozen and does not dispatch the sync; v1
  teams get it after migrating to v2.

## Tech debt

- **Legacy role column names map to relationship definitions by NAME.** The accounts list stores
  `csm` / `account_executive` / `account_owner` as bare column names (in the default columns, saved
  views, and shared URLs) and the frontend resolves them onto the team's relationship definitions
  named `CSM` / `Account executive` / `Account owner` at query-build time
  (`translateSelectColumns` in `accountsColumnConfigLogic`). Renaming one of those definitions
  silently drops the column from every legacy view; the renamed definition remains selectable from
  the "Relationships" picker group under a `rel_<id>` alias. A one-off migration of stored view
  columns to `rel_<id>` aliases removes the coupling if renames become common.
- **Account property writes have no single choke point.** `Account._properties` is mutated from
  independent paths: `create_account_for_view` / `update_account_for_view` (via the manager) and the
  Max tool's `_create_account` / `_update_account`. Anything that must happen on every properties
  write has to be repeated per call site, and a new writer can silently forget it. Funneling every
  properties write through `AccountManager` (and hooking cross-cutting behavior there) is the fix if
  account properties grow more derived behavior.
